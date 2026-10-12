import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication

from glance.actions import TextAction, copy_text, search_web
from glance.capture.manager import CaptureManager
from glance.capture.types import Screenshot
from glance.ocr.rapid import RapidOcrEngine
from glance.ocr.worker import OcrTask
from glance.ui.overlay import ScreenshotOverlay
from glance.ui.text_result import TextResultWindow
from glance.ui.text_view import TextView


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
        self._ocr_task: OcrTask | None = None
        self._text_view: TextView | None = None
        self._ocr = RapidOcrEngine()
        self.exit_code = 0

    def start(self) -> None:
        manager = CaptureManager(self._app, token_file())
        manager.captured.connect(self._show_overlay)
        manager.failed.connect(self._fail)
        manager.capture_screen()

    def _show_overlay(self, screenshot: Screenshot) -> None:
        self._overlay = ScreenshotOverlay(screenshot, self._app)
        self._overlay.captured.connect(self._finish)
        self._overlay.text_requested.connect(self._read_text)
        self._overlay.cancelled.connect(self._app.quit)
        self._overlay.show()

    def _finish(self, image: QImage) -> None:
        QGuiApplication.clipboard().setImage(image)
        path = save(image)
        if path is None:
            print("glance: could not save the screenshot.", file=sys.stderr)
            self.exit_code = 1
        else:
            print(path)
        self._app.quit()

    def _read_text(self, image: QImage) -> None:
        # The overlay is gone by now, so the view and the task keep the app alive.
        view = TextView(
            image,
            [
                TextAction("Copy", copy_text),
                TextAction("Search", search_web),
                TextAction("Edit", self._edit_text),
            ],
        )
        view.closed.connect(self._app.quit)
        view.show()
        self._text_view = view

        task = OcrTask(self._ocr, image, self._app)
        task.done.connect(view.set_result)
        task.failed.connect(view.set_error)
        task.start()
        self._ocr_task = task

    def _edit_text(self, text: str) -> None:
        window = TextResultWindow(text, self._text_view)
        window.show()

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
