from dataclasses import dataclass
from typing import Self

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QImage, QPainter


@dataclass(frozen=True, slots=True)
class Monitor:
    """One physical display, in the desktop's logical coordinate space.

    There is deliberately no pixel ratio: Qt rounds fractional scales (it reports
    2.0 for a 1.25x display), so it cannot be trusted to size an image.
    """

    index: int
    name: str
    geometry: QRect


def _scaled(rect: QRect, scale: float) -> QRect:
    # Round the edges, not the size, so neighbouring rectangles never leave a
    # gap or overlap by a pixel.
    left = round(rect.left() * scale)
    top = round(rect.top() * scale)
    right = round((rect.left() + rect.width()) * scale)
    bottom = round((rect.top() + rect.height()) * scale)
    return QRect(left, top, right - left, bottom - top)


@dataclass(frozen=True, slots=True, eq=False)
class Screenshot:
    """One image per monitor, each at that monitor's own pixel resolution.

    The image's scale is derived from its size rather than assumed: it is the
    image width over the monitor's logical width. Monitors may therefore differ,
    for example a 1.25x laptop panel beside a 1x external monitor.
    """

    monitors: tuple[Monitor, ...]
    images: tuple[QImage, ...]

    def __post_init__(self) -> None:
        if not self.monitors:
            raise ValueError("A screenshot needs at least one monitor.")
        if len(self.monitors) != len(self.images):
            raise ValueError("A screenshot needs exactly one image per monitor.")

    @classmethod
    def from_stitched(cls, image: QImage, monitors: tuple[Monitor, ...]) -> Self:
        """Split one image of the whole desktop into per-monitor images.

        The screenshot portal returns a single stitched image with no monitor
        information, and its scale is chosen by the compositor. The compositor
        renders at the highest scale among the monitors, so monitors with a lower
        scale are upscaled in it and look soft. Prefer real per-monitor captures.
        """
        if not monitors:
            raise ValueError("A screenshot needs at least one monitor.")
        desktop = _united(monitors)
        scale = image.width() / desktop.width()
        images = tuple(
            image.copy(_scaled(monitor.geometry.translated(-desktop.topLeft()), scale))
            for monitor in monitors
        )
        return cls(monitors, images)

    @property
    def desktop(self) -> QRect:
        """The logical rectangle covered by all monitors."""
        return _united(self.monitors)

    def monitor_image(self, monitor: Monitor) -> QImage:
        """The monitor's image, at its own resolution."""
        return self.images[self.monitors.index(monitor)]

    def scale(self, monitor: Monitor) -> float:
        """Image pixels per logical unit on one monitor."""
        return self.monitor_image(monitor).width() / monitor.geometry.width()

    def _parts(self, logical: QRect) -> list[tuple[Monitor, QImage, QRect]]:
        parts: list[tuple[Monitor, QImage, QRect]] = []
        for monitor, image in zip(self.monitors, self.images, strict=True):
            overlap = logical.intersected(monitor.geometry)
            if not overlap.isEmpty():
                parts.append((monitor, image, overlap))
        return parts

    def pixel_size(self, logical: QRect) -> QSize:
        """The size in pixels `crop` gives for a logical rectangle."""
        parts = self._parts(logical)
        if not parts:
            return QSize(0, 0)
        scale = max(self.scale(monitor) for monitor, _, _ in parts)
        return _scaled(QRect(QPoint(0, 0), logical.size()), scale).size()

    def crop(self, logical: QRect) -> QImage:
        """The part of the desktop under a logical rectangle.

        Inside one monitor this is a plain copy of that monitor's pixels. When the
        rectangle spans monitors of different scales, the result uses the highest
        scale and the others are enlarged to match.
        """
        parts = self._parts(logical)
        size = self.pixel_size(logical)
        result = QImage(size, QImage.Format.Format_RGB32)
        result.fill(0)
        if not parts:
            return result
        scale = max(self.scale(monitor) for monitor, _, _ in parts)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for monitor, image, overlap in parts:
            source = _scaled(
                overlap.translated(-monitor.geometry.topLeft()), self.scale(monitor)
            )
            target = _scaled(overlap.translated(-logical.topLeft()), scale)
            painter.drawImage(target, image, source)
        painter.end()
        return result


def _united(monitors: tuple[Monitor, ...]) -> QRect:
    desktop = monitors[0].geometry
    for monitor in monitors[1:]:
        desktop = desktop.united(monitor.geometry)
    return desktop
