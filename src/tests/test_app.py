import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QThreadPool  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QClipboard,
    QColor,
    QGuiApplication,
    QImage,
    QPainter,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance.app import App, write_document  # noqa: E402
from glance.capture.types import Monitor, Screenshot  # noqa: E402
from glance.ocr.types import OcrResult  # noqa: E402
from glance.payloads import Document, Wifi  # noqa: E402
from glance.smart import Entity, Kind  # noqa: E402
from glance.translate.google import GoogleTranslator  # noqa: E402
from glance.translate.groq import GroqTranslator  # noqa: E402


def _image() -> QImage:
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    return image


class CopyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(QApplication, QApplication.instance() or QApplication([]))

    def setUp(self) -> None:
        self.glance = App(self.app)
        self.quit = MagicMock()
        self.glance._app = MagicMock(quit=self.quit)  # pyright: ignore[reportPrivateUsage]
        self.clipboard = QGuiApplication.clipboard()

    def _quiet(self) -> contextlib.AbstractContextManager[object]:
        return contextlib.redirect_stdout(io.StringIO())

    def _taken_by_another_app(self) -> None:
        with patch.object(QClipboard, "ownsClipboard", return_value=False):
            self.clipboard.dataChanged.emit()

    def test_a_copied_image_is_on_the_clipboard_and_the_app_stays_alive(self) -> None:
        self.glance._copy_image(_image())  # pyright: ignore[reportPrivateUsage]

        image = self.clipboard.image()
        self.assertEqual((image.width(), image.height()), (4, 3))
        self.quit.assert_not_called()

    def test_the_app_quits_once_another_app_takes_the_clipboard(self) -> None:
        self.glance._copy_image(_image())  # pyright: ignore[reportPrivateUsage]

        self._taken_by_another_app()

        self.quit.assert_called_once()

    def test_a_clipboard_change_by_glance_itself_does_not_quit(self) -> None:
        self.glance._copy_image(_image())  # pyright: ignore[reportPrivateUsage]

        with patch.object(QClipboard, "ownsClipboard", return_value=True):
            self.clipboard.dataChanged.emit()

        self.quit.assert_not_called()

    def test_copy_text_stays_alive_the_same_way(self) -> None:
        self.glance._copy_text("hello")  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(self.clipboard.text(), "hello")
        self.quit.assert_not_called()
        self._taken_by_another_app()
        self.quit.assert_called_once()

    def test_opening_a_link_opens_it_and_then_quits(self) -> None:
        entity = Entity(Kind.LINK, "example.org", "https://example.org")

        with (
            patch("glance.app.open_entity") as opened,
            patch("glance.app.QTimer.singleShot") as later,
        ):
            self.glance._open_entity(entity)  # pyright: ignore[reportPrivateUsage]

        opened.assert_called_once_with(entity)
        later.assert_called_once()

    def test_copy_and_save_keeps_the_image_on_the_clipboard(self) -> None:
        with patch("glance.app.save", return_value="shot.png"), self._quiet():
            self.glance._finish(_image())  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(self.clipboard.image().width(), 4)
        self.quit.assert_not_called()

    def test_save_only_quits_right_away(self) -> None:
        with patch("glance.app.save", return_value="shot.png"), self._quiet():
            self.glance._save_image(_image())  # pyright: ignore[reportPrivateUsage]

        self.quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()


class ReadCodesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(QApplication, QApplication.instance() or QApplication([]))

    def test_a_settled_selection_is_scanned_for_codes(self) -> None:
        import numpy as np
        import zxingcpp

        create: Any = zxingcpp.create_barcode  # pyright: ignore
        barcode = np.ascontiguousarray(
            zxingcpp.write_barcode_to_image(
                create("hello", zxingcpp.BarcodeFormat.QRCode), 4
            )
        )
        side = barcode.shape[0]
        code = QImage(barcode.data, side, side, side, QImage.Format.Format_Grayscale8)
        screen = QImage(400, 300, QImage.Format.Format_RGB32)
        screen.fill(QColor("white"))
        painter = QPainter(screen)
        painter.drawImage(50, 40, code)
        painter.end()
        monitor = Monitor(0, "A", QRect(0, 0, 400, 300))
        glance = App(self.app)
        glance._screenshot = Screenshot((monitor,), (screen,))  # pyright: ignore[reportPrivateUsage]
        glance._screen_ocr = MagicMock(results=(OcrResult(()),))  # pyright: ignore[reportPrivateUsage]
        overlay = MagicMock()
        glance._overlay = overlay  # pyright: ignore[reportPrivateUsage]
        area = QRect(0, 0, 300, 200)

        glance._read_selection(area)  # pyright: ignore[reportPrivateUsage]
        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()

        overlay.set_codes.assert_called_once()
        [found], shown = (
            overlay.set_codes.call_args.args[0],
            overlay.set_codes.call_args.args[1],
        )
        self.assertEqual(found.text, "hello")
        self.assertEqual(shown, area)


class ScreenCodesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(QApplication, QApplication.instance() or QApplication([]))

    def test_every_monitor_is_scanned_for_screen_mode(self) -> None:
        screen = QImage(80, 60, QImage.Format.Format_RGB32)
        screen.fill(QColor("white"))
        monitors = (
            Monitor(0, "A", QRect(0, 0, 80, 60)),
            Monitor(1, "B", QRect(80, 0, 80, 60)),
        )
        glance = App(self.app)
        overlay = MagicMock()
        glance._overlay = overlay  # pyright: ignore[reportPrivateUsage]

        glance._read_screen_codes(  # pyright: ignore[reportPrivateUsage]
            overlay, Screenshot(monitors, (screen, screen))
        )
        for _ in range(2):
            QThreadPool.globalInstance().waitForDone(5000)
            self.app.processEvents()

        self.assertEqual(
            [call.args for call in overlay.set_screen_codes.call_args_list],
            [(0, []), (1, [])],
        )


class DocumentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(QApplication, QApplication.instance() or QApplication([]))

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        patcher = patch("glance.app.documents_dir", return_value=Path(self.folder.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_document_is_written_exactly_and_old_ones_are_removed(self) -> None:
        old = Path(self.folder.name) / "glance-old.vcf"
        old.write_text("x")
        os.utime(old, (0, 0))

        path = write_document(Document(".ics", "a\r\nb\r\n"))

        assert path is not None
        self.assertEqual(path.read_bytes(), b"a\r\nb\r\n")
        self.assertEqual(path.suffix, ".ics")
        self.assertFalse(old.exists())

    def test_opening_a_document_hands_the_file_over_and_then_quits(self) -> None:
        glance = App(self.app)
        with (
            patch("glance.app.QDesktopServices.openUrl", return_value=True) as opened,
            patch("glance.app.QTimer.singleShot") as later,
        ):
            glance._open_document(Document(".vcf", "x"))  # pyright: ignore[reportPrivateUsage]

        self.assertTrue(opened.call_args.args[0].toLocalFile().endswith(".vcf"))
        later.assert_called_once()
        self.assertEqual(glance.exit_code, 0)

    def test_nothing_to_open_it_with_is_reported(self) -> None:
        glance = App(self.app)
        with (
            patch("glance.app.QDesktopServices.openUrl", return_value=False),
            patch.object(QApplication, "quit") as quit_,
            contextlib.redirect_stderr(io.StringIO()) as error,
        ):
            glance._open_document(Document(".ics", "x"))  # pyright: ignore[reportPrivateUsage]

        self.assertIn("nothing opens .ics files", error.getvalue())
        self.assertEqual(glance.exit_code, 1)
        quit_.assert_called_once()


class JoinWifiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(QApplication, QApplication.instance() or QApplication([]))

    def _join(self, side_effect: Exception | None) -> tuple[App, MagicMock, MagicMock]:
        glance = App(self.app)
        notified = MagicMock()
        with (
            patch.object(QApplication, "quit") as quit_,
            patch("glance.app.connect_wifi", side_effect=side_effect) as connect,
            patch("glance.app.notify", notified),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            glance._join_wifi(Wifi("Home", "pw", "WPA", False))  # pyright: ignore[reportPrivateUsage]
            QThreadPool.globalInstance().waitForDone(5000)
            self.app.processEvents()
        connect.assert_called_once()
        return glance, quit_, notified

    def test_joining_says_so_and_quits(self) -> None:
        glance, quit_, notified = self._join(None)

        self.assertEqual(notified.call_args.args[0], "Joining Home")
        quit_.assert_called_once()
        self.assertEqual(glance.exit_code, 0)

    def test_a_failure_is_reported_and_exits_with_an_error(self) -> None:
        glance, quit_, notified = self._join(RuntimeError("denied"))

        self.assertEqual(notified.call_args.args[:2], ("Could not join Home", "denied"))
        quit_.assert_called_once()
        self.assertEqual(glance.exit_code, 1)


class ChooseTranslatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(QApplication, QApplication.instance() or QApplication([]))

    def _chosen(self, environment: dict[str, str]) -> object:
        with tempfile.TemporaryDirectory() as config:
            # An empty config folder, so a key file of the developer's own is not found.
            environment = {"XDG_CONFIG_HOME": config, **environment}
            with patch.dict(os.environ, environment, clear=True):
                return App(self.app)._translator()  # pyright: ignore[reportPrivateUsage]

    def test_groq_is_used_when_a_key_is_set(self) -> None:
        self.assertIsInstance(self._chosen({"GROQ_API_KEY": "k"}), GroqTranslator)

    def test_google_is_used_without_a_key(self) -> None:
        self.assertIsInstance(self._chosen({}), GoogleTranslator)
