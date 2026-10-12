import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication

from glance.capture.manager import CaptureManager
from glance.capture.types import Screenshot
from glance.ui.overlay import ScreenshotOverlay


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
        self.exit_code = 0

    def start(self) -> None:
        manager = CaptureManager(self._app, token_file())
        manager.captured.connect(self._show_overlay)
        manager.failed.connect(self._fail)
        manager.capture_screen()

    def _show_overlay(self, screenshot: Screenshot) -> None:
        self._overlay = ScreenshotOverlay(screenshot, self._app)
        self._overlay.captured.connect(self._finish)
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

    def _fail(self, message: str) -> None:
        print(f"glance: {message}", file=sys.stderr)
        self.exit_code = 1
        self._app.quit()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Glance")
    glance = App(app)
    glance.start()
    app.exec()
    return glance.exit_code
