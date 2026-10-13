import os
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance.translate.google import (  # noqa: E402
    GoogleTranslator,
    TranslateError,
    parse,
)
from glance.translate.languages import LANGUAGES, supported  # noqa: E402
from glance.translate.types import Translation  # noqa: E402
from glance.translate.worker import TranslateTask  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "google_translate_es_en.json"


class ParseTest(unittest.TestCase):
    def test_sentences_are_joined_with_their_line_breaks(self) -> None:
        translation = parse(FIXTURE.read_text(), "en")

        self.assertEqual(
            translation.text,
            "Hello how are you?\nMy name is Ana. I live in Madrid.\n\nSee you later.",
        )
        self.assertEqual((translation.source, translation.target), ("es", "en"))

    def test_an_unexpected_response_is_an_error(self) -> None:
        for body in ("not json", "[]", '{"sentences": 3}', '{"other": 1}'):
            with self.subTest(body=body), self.assertRaises(TranslateError):
                parse(body, "en")


class GoogleTranslatorTest(unittest.TestCase):
    def _respond(self, body: str) -> MagicMock:
        response = MagicMock()
        response.read.return_value = body.encode()
        response.__enter__.return_value = response
        return response

    def test_the_text_is_posted_and_the_translation_returned(self) -> None:
        with patch(
            "urllib.request.urlopen", return_value=self._respond(FIXTURE.read_text())
        ) as urlopen:
            translation = GoogleTranslator().translate("Hola & más", "en")

        request = urlopen.call_args.args[0]
        self.assertIn("tl=en", request.full_url)
        self.assertEqual(request.data, b"q=Hola+%26+m%C3%A1s")
        self.assertEqual(translation.target, "en")

    def test_rate_limiting_is_explained(self) -> None:
        error = urllib.error.HTTPError("u", 429, "Too Many", None, None)  # pyright: ignore[reportArgumentType]
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(TranslateError, "limiting"):
                GoogleTranslator().translate("hola", "en")

    def test_no_network_is_explained(self) -> None:
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("x")):
            with self.assertRaisesRegex(TranslateError, "reach"):
                GoogleTranslator().translate("hola", "en")


class _Fake:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def translate(self, text: str, target: str) -> Translation:
        if self.fail:
            raise TranslateError("offline")
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
