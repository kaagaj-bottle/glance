import json
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance.ai.client import GroqError  # noqa: E402
from glance.ai.translate import MAX_INPUT, GroqTranslator  # noqa: E402
from glance.ai.translate import parse as parse_groq  # noqa: E402
from glance.translate.languages import LANGUAGES, supported  # noqa: E402
from glance.translate.types import Translation  # noqa: E402
from glance.translate.worker import TranslateTask  # noqa: E402


class _Fake:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def translate(self, text: str, target: str) -> Translation:
        if self.fail:
            raise GroqError("offline")
        return Translation(text.upper(), "es", target)


class TranslateTaskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QApplication([])

    def _run(self, translator: _Fake) -> tuple[list[object], list[str]]:
        done: list[object] = []
        failed: list[str] = []
        loop = QEventLoop()

        def on_done(result: object) -> None:
            done.append(result)
            loop.quit()

        def on_failed(message: str) -> None:
            failed.append(message)
            loop.quit()

        task = TranslateTask(translator, "hola", "en")
        task.done.connect(on_done)
        task.failed.connect(on_failed)
        QTimer.singleShot(5000, loop.quit)
        task.start()
        loop.exec()
        return done, failed

    def test_the_result_arrives_through_done(self) -> None:
        done, failed = self._run(_Fake())

        self.assertEqual(done, [Translation("HOLA", "es", "en")])
        self.assertEqual(failed, [])

    def test_an_error_arrives_through_failed(self) -> None:
        done, failed = self._run(_Fake(fail=True))

        self.assertEqual((done, failed), ([], ["offline"]))


class LanguagesTest(unittest.TestCase):
    def test_a_locale_maps_to_an_offered_language(self) -> None:
        self.assertEqual(supported("fr_CA"), "fr")
        self.assertEqual(supported("zh_TW"), "zh-TW")
        self.assertEqual(supported("zh_SG"), "zh-CN")
        self.assertEqual(supported("en_US"), "en")

    def test_an_unknown_locale_is_not_offered(self) -> None:
        self.assertIsNone(supported("C"))
        self.assertIsNone(supported(""))

    def test_codes_are_unique(self) -> None:
        codes = [code for code, _ in LANGUAGES]
        self.assertEqual(len(codes), len(set(codes)))


class GroqTranslatorTest(unittest.TestCase):
    def _respond(self, content: str) -> MagicMock:
        response = MagicMock()
        body = json.dumps({"choices": [{"message": {"content": content}}]})
        response.read.return_value = body.encode()
        response.__enter__.return_value = response
        return response

    def test_the_text_is_translated_and_the_source_language_read_from_the_reply(
        self,
    ) -> None:
        reply = "LANG: es\nHello how are you?\nSee you later."
        with patch(
            "urllib.request.urlopen", return_value=self._respond(reply)
        ) as urlopen:
            translation = GroqTranslator("k").translate("Hola", "en")

        self.assertEqual(
            translation,
            Translation("Hello how are you?\nSee you later.", "es", "en", "Groq"),
        )
        messages = json.loads(urlopen.call_args.args[0].data)["messages"]
        self.assertIn("into English", messages[0]["content"])
        self.assertEqual(messages[1]["content"], "Hola")

    def test_the_target_is_named_by_its_language_not_its_code(self) -> None:
        with patch(
            "urllib.request.urlopen", return_value=self._respond("LANG: en\nx")
        ) as urlopen:
            GroqTranslator("k").translate("hi", "zh-TW")

        system = json.loads(urlopen.call_args.args[0].data)["messages"][0]["content"]
        self.assertIn("Chinese (Traditional)", system)

    def test_a_reply_without_the_language_line_is_kept_whole(self) -> None:
        translation = parse_groq("Just the text", "en")

        self.assertEqual(translation, Translation("Just the text", "", "en", "Groq"))

    def test_a_long_text_is_refused_and_nothing_is_sent(self) -> None:
        with (
            patch("urllib.request.urlopen") as urlopen,
            self.assertRaisesRegex(GroqError, "Too long"),
        ):
            GroqTranslator("k").translate("x" * (MAX_INPUT + 1), "en")

        urlopen.assert_not_called()
