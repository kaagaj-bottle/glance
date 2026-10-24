import json
import os
import unittest
from collections.abc import Callable
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance.ai.client import GroqError  # noqa: E402
from glance.ai.explain import MAX_INPUT, GroqExplainer  # noqa: E402
from glance.ai.image import MAX_SIDE, png_for_model  # noqa: E402
from glance.ai.models import VISION  # noqa: E402
from glance.ai.worker import ExplainTask  # noqa: E402

REPLY = json.dumps({"choices": [{"message": {"content": "  It is a greeting.\n"}}]})


class GroqExplainerTest(unittest.TestCase):
    def _respond(self, body: str) -> MagicMock:
        response = MagicMock()
        response.read.return_value = body.encode()
        response.__enter__.return_value = response
        return response

    def test_the_text_is_posted_with_the_key(self) -> None:
        with patch(
            "urllib.request.urlopen", return_value=self._respond(REPLY)
        ) as urlopen:
            answer = GroqExplainer("secret").explain("Hola")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(json.loads(request.data)["messages"][-1]["content"], "Hola")
        self.assertEqual(answer, "It is a greeting.")

    def test_a_long_text_is_cut_and_the_answer_is_capped(self) -> None:
        with patch(
            "urllib.request.urlopen", return_value=self._respond(REPLY)
        ) as urlopen:
            GroqExplainer("k").explain("x" * (MAX_INPUT + 500))

        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(len(payload["messages"][-1]["content"]), MAX_INPUT)
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertIn("max_completion_tokens", payload)

    def test_the_answer_is_asked_for_in_english(self) -> None:
        with patch(
            "urllib.request.urlopen", return_value=self._respond(REPLY)
        ) as urlopen:
            GroqExplainer("k").explain("Hola")
            GroqExplainer("k").explain_image(b"png")

        for call in urlopen.call_args_list:
            system = json.loads(call.args[0].data)["messages"][0]["content"]
            self.assertIn("Always answer in English", system)

    def test_an_image_goes_to_the_vision_model_as_a_data_uri(self) -> None:
        with patch(
            "urllib.request.urlopen", return_value=self._respond(REPLY)
        ) as urlopen:
            answer = GroqExplainer("k").explain_image(b"png")

        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["model"], VISION)
        parts = payload["messages"][-1]["content"]
        url = next(p["image_url"]["url"] for p in parts if p["type"] == "image_url")
        self.assertEqual(url, "data:image/png;base64,cG5n")
        self.assertEqual(answer, "It is a greeting.")


def _work(fail: bool = False) -> Callable[[], str]:
    def work() -> str:
        if fail:
            raise GroqError("offline")
        return "HOLA"

    return work


class ExplainTaskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QApplication([])

    def _run(self, work: Callable[[], str]) -> tuple[list[str], list[str]]:
        done: list[str] = []
        failed: list[str] = []
        loop = QEventLoop()

        def on_done(result: str) -> None:
            done.append(result)
            loop.quit()

        def on_failed(message: str) -> None:
            failed.append(message)
            loop.quit()

        task = ExplainTask(work)
        task.done.connect(on_done)
        task.failed.connect(on_failed)
        QTimer.singleShot(5000, loop.quit)
        task.start()
        loop.exec()
        return done, failed

    def test_the_answer_arrives_through_done(self) -> None:
        self.assertEqual(self._run(_work()), (["HOLA"], []))

    def test_an_error_arrives_through_failed(self) -> None:
        self.assertEqual(self._run(_work(fail=True)), ([], ["offline"]))


class PngForModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QApplication([])

    def _decoded(self, width: int, height: int) -> QImage:
        image = QImage()
        image.loadFromData(
            png_for_model(QImage(width, height, QImage.Format.Format_RGB32))
        )
        return image

    def test_a_big_image_is_scaled_down_keeping_its_shape(self) -> None:
        image = self._decoded(2560, 1440)

        self.assertEqual((image.width(), image.height()), (MAX_SIDE, 720))

    def test_a_small_image_is_left_alone(self) -> None:
        image = self._decoded(300, 200)

        self.assertEqual((image.width(), image.height()), (300, 200))
