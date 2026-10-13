import ctypes
import gc
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRect, QStandardPaths, QTimer
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication

from glance.actions import copy_text, search_web
from glance.capture.manager import CaptureManager
from glance.capture.types import Screenshot
from glance.ocr.rapid import RapidOcrEngine
from glance.ocr.screen import ScreenOcr, selection_result
from glance.ocr.types import OcrResult
from glance.ocr.worker import OcrTask
from glance.ui.overlay import ScreenshotOverlay

SEARCH_EXIT_MS = 300


def screenshots_dir() -> Path:
    pictures = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.PicturesLocation
    )
    return Path(pictures or Path.home() / "Pictures") / "Screenshots"


def token_file() -> Path:
    data = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(data) / "screencast-token"


def save(image: QImage) -> Path | None:
    """Save the image the way GNOME Screenshot names it. None if it can't be written."""
    folder = screenshots_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"Screenshot From {datetime.now():%Y-%m-%d %H-%M-%S}.png"
    return path if image.save(str(path)) else None


class App:
    def __init__(self, app: QApplication) -> None:
        self._app = app
        self._overlay: ScreenshotOverlay | None = None
        self._screenshot: Screenshot | None = None
        self._screen_ocr: ScreenOcr | None = None
        self._ocr_task: OcrTask | None = None
        self._ocr = RapidOcrEngine()
        self.exit_code = 0

    def start(self) -> None:
        manager = CaptureManager(self._app, token_file())
        manager.captured.connect(self._show_overlay)
        manager.failed.connect(self._fail)
        manager.capture_screen()

    def _show_overlay(self, screenshot: Screenshot) -> None:
        # Read the whole screen while the user chooses, so the text of whatever
        # they select is ready by the time they ask for it.
        self._screenshot = screenshot
        self._screen_ocr = ScreenOcr(self._ocr, screenshot.images, self._app)
        self._screen_ocr.start()
        self._overlay = ScreenshotOverlay(screenshot, self._app)
        self._overlay.captured.connect(self._finish)
        self._overlay.image_copied.connect(self._copy_image)
        self._overlay.image_saved.connect(self._save_image)
        self._overlay.selection_settled.connect(self._read_selection)
        self._overlay.text_copied.connect(self._copy_text)
        self._overlay.text_searched.connect(self._search_text)
        self._overlay.cancelled.connect(self._app.quit)
        self._overlay.show()

    def _finish(self, image: QImage) -> None:
        QGuiApplication.clipboard().setImage(image)
        self._write_image(image)
        self._quit_when_clipboard_taken()

    def _copy_image(self, image: QImage) -> None:
        QGuiApplication.clipboard().setImage(image)
        self._quit_when_clipboard_taken()

    def _save_image(self, image: QImage) -> None:
        self._write_image(image)
        self._app.quit()

    def _write_image(self, image: QImage) -> None:
        path = save(image)
        if path is None:
            print("glance: could not save the screenshot.", file=sys.stderr)
            self.exit_code = 1
        else:
            print(path)

    def _read_selection(self, area: QRect) -> None:
        """Show the text in a selection: from the screen read ahead if it is done."""
        overlay, screenshot = self._overlay, self._screenshot
        if overlay is None or screenshot is None:
            return
        results = self._screen_ocr.results if self._screen_ocr else None
        if results is not None:
            overlay.set_words(selection_result(screenshot, results, area), area)
            return

        # The screen is not read yet (or could not be), so read just the selection.
        task = OcrTask(self._ocr, screenshot.crop(area), self._app)

        def show(result: object) -> None:
            if isinstance(result, OcrResult):
                overlay.set_words(result, area)

        task.done.connect(show)
        task.start()
        self._ocr_task = task

    def _copy_text(self, text: str) -> None:
        copy_text(text)
        self._quit_when_clipboard_taken()

    def _quit_when_clipboard_taken(self) -> None:
        """Stay alive until another app copies something: the copied data lives here."""
        self._release_capture()
        clipboard = QGuiApplication.clipboard()

        def taken() -> None:
            if not clipboard.ownsClipboard():
                self._app.quit()

        clipboard.dataChanged.connect(taken)

    def _release_capture(self) -> None:
        """Drop the screenshots and OCR models: only the clipboard is still needed."""
        self._overlay = None
        self._screenshot = None
        self._screen_ocr = None
        self._ocr_task = None
        self._ocr = RapidOcrEngine()
        gc.collect()
        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass

    def _search_text(self, text: str) -> None:
        search_web(text)
        # Give the browser request time to leave before the app exits.
        QTimer.singleShot(SEARCH_EXIT_MS, self._app.quit)

    def _fail(self, message: str) -> None:
        print(f"glance: {message}", file=sys.stderr)
        self.exit_code = 1
        self._app.quit()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Glance")
    # Closing the overlay must not end the app while OCR is still running.
    app.setQuitOnLastWindowClosed(False)
    glance = App(app)
    glance.start()
    app.exec()
    return glance.exit_code
