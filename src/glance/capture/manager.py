from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication, QImage, QScreen

from glance.capture.portal import PortalScreenshot
from glance.capture.types import Monitor, Screenshot


def _monitor(index: int, screen: QScreen) -> Monitor:
    return Monitor(
        index=index,
        name=screen.name(),
        geometry=screen.geometry(),
    )


def current_monitors() -> tuple[Monitor, ...]:
    return tuple(
        _monitor(index, screen)
        for index, screen in enumerate(QGuiApplication.screens())
    )


class CaptureManager(QObject):
    """Takes a full-screen screenshot and reports it through signals.

    The XDG Desktop Portal is tried first because it works on Wayland, on X11
    and inside Flatpak. Grabbing the screen through Qt is only a fallback for
    X11 sessions without a portal; on Wayland it would return a blank image.
    """

    captured = Signal(Screenshot)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._portal: PortalScreenshot | None = None

    def capture_screen(self) -> None:
        portal = PortalScreenshot(self)
        portal.captured.connect(self._finish_portal)
        portal.failed.connect(self._fail_portal)
        self._portal = portal

        if not portal.start():
            self._discard_portal()
            self._capture_with_qt()

    def _finish_portal(self, image: QImage) -> None:
        self._discard_portal()
        monitors = current_monitors()
        if not monitors:
            self.failed.emit("No monitors were found.")
            return
        self.captured.emit(Screenshot(image, monitors))

    def _fail_portal(self, message: str) -> None:
        self._discard_portal()
        self.failed.emit(message)

    def _discard_portal(self) -> None:
        if self._portal is not None:
            self._portal.deleteLater()
            self._portal = None

    def _capture_with_qt(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if QGuiApplication.platformName() == "wayland" or screen is None:  # pyright: ignore[reportUnnecessaryComparison]
            self.failed.emit("No screenshot method is available on this system.")
            return

        image = screen.grabWindow(0).toImage()
        if image.isNull():
            self.failed.emit("Could not grab the screen.")
            return
        # grabWindow(0) captures this one screen only.
        index = QGuiApplication.screens().index(screen)
        self.captured.emit(Screenshot(image, (_monitor(index, screen),)))
