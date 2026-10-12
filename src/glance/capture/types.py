from dataclasses import dataclass

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage


@dataclass(frozen=True, slots=True)
class Monitor:
    """One physical display, in the desktop's logical coordinate space.

    There is deliberately no pixel ratio: Qt rounds fractional scales (it reports
    2.0 for a 1.25x display), so it cannot be trusted to size an image.
    """

    index: int
    name: str
    geometry: QRect


@dataclass(frozen=True, slots=True, eq=False)
class Screenshot:
    """An image of the whole desktop and the monitors it covers.

    The portal returns a single stitched image with no monitor information, and
    its pixel scale is chosen by the compositor (it may match neither 1x nor any
    monitor's own scale). The scale is therefore derived from the image size
    rather than assumed: it is the image width over the desktop's logical width.

    The compositor renders at the highest scale among the monitors, so monitors
    with a lower scale are upscaled in the image. A 1x monitor beside a 1.25x one
    appears 1.25x larger than its real resolution.
    """

    image: QImage
    monitors: tuple[Monitor, ...]

    def __post_init__(self) -> None:
        if not self.monitors:
            raise ValueError("A screenshot needs at least one monitor.")

    @property
    def desktop(self) -> QRect:
        """The logical rectangle covered by all monitors."""
        desktop = self.monitors[0].geometry
        for monitor in self.monitors[1:]:
            desktop = desktop.united(monitor.geometry)
        return desktop

    @property
    def scale(self) -> float:
        """Image pixels per logical unit."""
        return self.image.width() / self.desktop.width()

    def image_rect(self, logical: QRect) -> QRect:
        """Convert a logical desktop rectangle to a rectangle in image pixels."""
        desktop = self.desktop
        scale = self.scale
        # Round the edges, not the size, so neighbouring rectangles never leave
        # a gap or overlap by a pixel.
        left = round((logical.left() - desktop.left()) * scale)
        top = round((logical.top() - desktop.top()) * scale)
        right = round((logical.left() + logical.width() - desktop.left()) * scale)
        bottom = round((logical.top() + logical.height() - desktop.top()) * scale)
        return QRect(left, top, right - left, bottom - top)

    def crop(self, logical: QRect) -> QImage:
        """The part of the image under a logical desktop rectangle."""
        return self.image.copy(self.image_rect(logical))

    def monitor_image(self, monitor: Monitor) -> QImage:
        """The part of the image showing one monitor."""
        return self.crop(monitor.geometry)
