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
from glance.library.store import Library  # noqa: E402
from glance.ocr.types import OcrResult  # noqa: E402
from glance.payloads import Document, Wifi  # noqa: E402
from glance.smart import Entity, Kind  # noqa: E402


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
        # The real setting is the user's; a test must not add to their library.
        patcher = patch("glance.app.library_enabled", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

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


class LibraryHookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(QApplication, QApplication.instance() or QApplication([]))

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.shot = self.root / "shot.png"
        self.database = self.root / "data" / "library.db"
        self.glance = App(self.app)
        self.quit = MagicMock()
        self.glance._app = MagicMock(quit=self.quit)  # pyright: ignore[reportPrivateUsage]

    def _save(self, enabled: bool, database: Path | None = None) -> str:
        err = io.StringIO()
        with (
            patch("glance.app.save", return_value=self.shot),
            patch("glance.app.library_enabled", return_value=enabled),
            patch("glance.app.library_path", return_value=database or self.database),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(err),
        ):
            self.glance._save_image(_image())  # pyright: ignore[reportPrivateUsage]
        return err.getvalue()

    def test_a_saved_capture_is_added_when_the_library_is_on(self) -> None:
        self._save(enabled=True)

        with Library(self.database) as library:
            self.assertEqual([p.path for p in library.pending()], [self.shot.resolve()])

    def test_nothing_is_created_when_the_library_is_off(self) -> None:
        self._save(enabled=False)

        self.assertFalse(self.database.exists())

    def test_a_library_that_cannot_be_opened_does_not_fail_the_save(self) -> None:
        blocker = self.root / "blocker"
        blocker.write_text("a file where a folder is needed")

        err = self._save(enabled=True, database=blocker / "library.db")

        self.assertIn("could not add it to the library", err)
        self.assertEqual(self.glance.exit_code, 0)
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


class AskForKeyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(QApplication, QApplication.instance() or QApplication([]))

    def _start(self, environment: dict[str, str], asked: bool) -> MagicMock:
        """Start the app and return the key dialog's `exec`, which stands in for it."""
        with tempfile.TemporaryDirectory() as config:
            # Empty config folders, so a key or settings of the developer's own are
            # not found.
            environment = {"XDG_CONFIG_HOME": config, "HOME": config, **environment}
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("glance.app.QSettings") as settings,
                patch("glance.app.KeyDialog") as dialog,
                patch("glance.app.CaptureManager"),
            ):
                settings.return_value.value.return_value = asked
                App(self.app).start()
                self.settings = settings.return_value
                return dialog.return_value.exec

    def test_the_first_run_without_a_key_asks_for_one_and_remembers_it(self) -> None:
        exec_ = self._start({}, asked=False)

        exec_.assert_called_once()
        self.settings.setValue.assert_called_once_with("setup/asked-for-key", True)

    def test_a_skipped_dialog_is_not_shown_again(self) -> None:
        exec_ = self._start({}, asked=True)

        exec_.assert_not_called()

    def test_nothing_is_asked_when_there_is_a_key(self) -> None:
        exec_ = self._start({"GROQ_API_KEY": "k"}, asked=False)

        exec_.assert_not_called()
