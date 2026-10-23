import json
import os
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance.explain.groq import ExplainError, GroqExplainer, parse  # noqa: E402
from glance.explain.worker import ExplainTask  # noqa: E402

REPLY = json.dumps({"choices": [{"message": {"content": "  It is a greeting.\n"}}]})


class ParseTest(unittest.TestCase):
    def test_the_reply_is_trimmed(self) -> None:
        self.assertEqual(parse(REPLY), "It is a greeting.")

    def test_an_unexpected_response_is_an_error(self) -> None:
        empty = json.dumps({"choices": [{"message": {"content": " "}}]})
        for body in ("not json", "[]", '{"choices": []}', '{"choices": 3}', empty):
            with self.subTest(body=body), self.assertRaises(ExplainError):
                parse(body)


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

    def test_the_key_comes_from_the_environment(self) -> None:
        with (
            patch.dict(os.environ, {"GROQ_API_KEY": "from-env"}),
            patch("urllib.request.urlopen", return_value=self._respond(REPLY)) as o,
        ):
            GroqExplainer().explain("Hola")

        self.assertEqual(
            o.call_args.args[0].get_header("Authorization"), "Bearer from-env"
        )

    def test_a_missing_key_is_explained_and_nothing_is_sent(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("urllib.request.urlopen") as urlopen,
            self.assertRaisesRegex(ExplainError, "GROQ_API_KEY"),
        ):
            GroqExplainer().explain("Hola")

        urlopen.assert_not_called()

    def test_http_errors_are_explained(self) -> None:
        for code, message in ((401, "key"), (429, "limiting"), (500, "HTTP 500")):
            error = urllib.error.HTTPError("u", code, "x", None, None)  # pyright: ignore[reportArgumentType]
            with (
                self.subTest(code=code),
                patch("urllib.request.urlopen", side_effect=error),
                self.assertRaisesRegex(ExplainError, message),
            ):
                GroqExplainer("k").explain("Hola")

    def test_no_network_is_explained(self) -> None:
        with (
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("x")),
            self.assertRaisesRegex(ExplainError, "reach"),
        ):
            GroqExplainer("k").explain("Hola")


class _Fake:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def explain(self, text: str) -> str:
        if self.fail:
            raise ExplainError("offline")
        return text.upper()


class ExplainTaskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QApplication([])

    def _run(self, explainer: _Fake) -> tuple[list[str], list[str]]:
        done: list[str] = []
        failed: list[str] = []
        loop = QEventLoop()

        def on_done(result: str) -> None:
            done.append(result)
            loop.quit()

        def on_failed(message: str) -> None:
            failed.append(message)
            loop.quit()

        task = ExplainTask(explainer, "hola")
        task.done.connect(on_done)
        task.failed.connect(on_failed)
        QTimer.singleShot(5000, loop.quit)
        task.start()
        loop.exec()
        return done, failed

    def test_the_answer_arrives_through_done(self) -> None:
        self.assertEqual(self._run(_Fake()), (["HOLA"], []))

    def test_an_error_arrives_through_failed(self) -> None:
        self.assertEqual(self._run(_Fake(fail=True)), ([], ["offline"]))
