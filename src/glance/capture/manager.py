import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication, QImage, QScreen

from glance.capture.portal import PortalScreenshot
from glance.capture.screencast import Frame, Place, ScreenCastWorker
from glance.capture.types import Monitor, Screenshot

log = logging.getLogger(__name__)


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


def soft_monitors(monitors: tuple[Monitor, ...]) -> tuple[Monitor, ...]:
    """The monitors the portal screenshot is likely to show upscaled.

    The compositor renders that image at the highest scale among the monitors,
    so only monitors with a lower scale come out soft. Qt rounds fractional
    scales, so two fractional scales that round alike are not told apart.
    """
    screens = QGuiApplication.screens()
    ratios = {
        monitor: screens[monitor.index].devicePixelRatio() for monitor in monitors
    }
    sharpest = max(ratios.values(), default=1.0)
    return tuple(monitor for monitor in monitors if ratios[monitor] < sharpest)


def with_native_frames(screenshot: Screenshot, frames: list[Frame]) -> Screenshot:
    """Swap in the frame the portal placed at each monitor's spot.

    A monitor with no frame keeps the image it already had.
    """
    images: list[QImage] = []
    for monitor, image in zip(screenshot.monitors, screenshot.images, strict=True):
        geometry = monitor.geometry
        native = next(
            (
                frame.image
                for frame in frames
                if frame.position == (geometry.x(), geometry.y())
                and frame.size == (geometry.width(), geometry.height())
            ),
            None,
        )
        images.append(image if native is None else native)
    return Screenshot(screenshot.monitors, tuple(images))


class CaptureManager(QObject):
    """Takes a full-screen screenshot and reports it through signals.

    On X11, Qt grabs each screen at its real resolution. On Wayland the
    Screenshot portal gives every monitor, but as one image in which low-scale
    monitors are upscaled and blurry. When some monitors would be, the
    ScreenCast portal is asked first for just those at their real resolution,
    and its frames replace the blurry parts. A monitor that sends no frame in
    time keeps the portal image.
    """

    captured = Signal(Screenshot)
    failed = Signal(str)

    def __init__(
        self, parent: QObject | None = None, token_file: Path | None = None
    ) -> None:
        super().__init__(parent)
        self._token_file = token_file
        self._portal: PortalScreenshot | None = None
        self._worker: ScreenCastWorker | None = None
        self._frames: list[Frame] = []
        self._wanted = 0
        self._done = False

    def capture_screen(self) -> None:
        self._done = False
        self._baseline = None
        self._frames = []
        if QGuiApplication.platformName() == "wayland":
            # GNOME flashes the screen white while it takes the portal
            # screenshot, and any ScreenCast frame taken then is washed out. So
            # the native frames are taken first.
            if self._start_screencast():
                return
        elif self._capture_with_qt():
            return
        self._capture_with_portal()

    def _start_screencast(self) -> bool:
        """Start taking native frames of the soft monitors. False if none need it."""
        wanted: list[Place] = []
        for monitor in soft_monitors(current_monitors()):
            geometry = monitor.geometry
            wanted.append(
                ((geometry.x(), geometry.y()), (geometry.width(), geometry.height()))
            )
        if not wanted:
            return False
        self._wanted = len(wanted)
        worker = ScreenCastWorker(self._token_file, wanted)
        worker.grabbed.connect(self._finish_screencast)
        worker.failed.connect(self._fail_screencast)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()
        return True

    def _finish_screencast(self, frames: list[Frame]) -> None:
        if len(frames) < self._wanted:
            log.warning(
                "Native frames arrived for %d of %d soft monitors; "
                "the rest use the portal image.",
                len(frames),
                self._wanted,
            )
        self._frames = frames
        self._capture_with_portal()

    def _fail_screencast(self, message: str) -> None:
        log.warning("Native capture unavailable: %s", message)
        self._capture_with_portal()

    def _capture_with_portal(self) -> None:
        portal = PortalScreenshot(self)
        portal.captured.connect(self._finish_portal)
        portal.failed.connect(self._fail_portal)
        self._portal = portal

        if not portal.start():
            self._discard_portal()
            self._fail("No screenshot method is available on this system.")

    def _finish_portal(self, image: QImage) -> None:
        self._discard_portal()
        monitors = current_monitors()
        if not monitors:
            self._fail("No monitors were found.")
            return
        screenshot = Screenshot.from_stitched(image, monitors)
        self._done = True
        self.captured.emit(with_native_frames(screenshot, self._frames))

    def _fail_portal(self, message: str) -> None:
        self._discard_portal()
        self._fail(message)

    def _discard_portal(self) -> None:
        if self._portal is not None:
            self._portal.deleteLater()
            self._portal = None

    def _fail(self, message: str) -> None:
        if not self._done:
            self._done = True
            self.failed.emit(message)

    def _capture_with_qt(self) -> bool:
        """Grab every screen directly. Returns False if that did not work."""
        monitors = current_monitors()
        if not monitors:
            return False
        screens = QGuiApplication.screens()
        images = tuple(
            screens[monitor.index].grabWindow(0).toImage() for monitor in monitors
        )
        if any(image.isNull() for image in images):
            return False
        self._done = True
        self.captured.emit(Screenshot(monitors, images))
        return True
