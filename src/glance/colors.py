"""Colors in a capture: a palette for an area, and the color of one pixel."""

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

PALETTE_SIZE = 6
# Palettes are made from a shrunken copy; this is plenty to find the main colors.
SAMPLE_SIDE = 96
# Colors closer than this (sum of channel differences) count as the same swatch.
SAME_COLOR = 60


@dataclass(frozen=True, slots=True)
class Swatch:
    red: int
    green: int
    blue: int
    # The fraction of the area it covers, from 0 to 1.
    share: float

    @property
    def hex(self) -> str:
        return f"#{self.red:02X}{self.green:02X}{self.blue:02X}"


def pixel_hex(image: QImage, x: int, y: int) -> str | None:
    """The color of the pixel at (x, y) as `#RRGGBB`, or None if it is outside."""
    if not (0 <= x < image.width() and 0 <= y < image.height()):
        return None
    color = image.pixelColor(x, y)
    return f"#{color.red():02X}{color.green():02X}{color.blue():02X}"


def palette(image: QImage, size: int = PALETTE_SIZE) -> list[Swatch]:
    """The main colors of the image, the most common first (median cut)."""
    if image.isNull():
        return []
    small = image.scaled(
        SAMPLE_SIDE,
        SAMPLE_SIDE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    ).convertToFormat(QImage.Format.Format_RGB888)
    width, height, stride = small.width(), small.height(), small.bytesPerLine()
    rows = np.frombuffer(small.constBits(), dtype=np.uint8, count=stride * height)
    pixels = rows.reshape(height, stride)[:, : width * 3].reshape(-1, 3).astype(int)

    # Group the pixels into coarse bins and take the average color of each, so a
    # flat area of a screenshot keeps its exact color.
    keys = (pixels[:, 0] >> 4) * 256 + (pixels[:, 1] >> 4) * 16 + (pixels[:, 2] >> 4)
    _, bin_of, counts = np.unique(keys, return_inverse=True, return_counts=True)
    means = np.stack(
        [np.bincount(bin_of, weights=pixels[:, c]) / counts for c in range(3)], axis=1
    )

    # The most common bins become swatches; a bin close to a swatch, or any bin
    # once the palette is full, adds its pixels to the nearest swatch instead.
    colors: list[np.ndarray[tuple[int], np.dtype[np.float64]]] = []
    covered: list[int] = []
    for index in np.argsort(-counts, kind="stable"):
        color = means[index]
        gaps = [float(np.abs(other - color).sum()) for other in colors]
        nearest = int(np.argmin(gaps)) if gaps else -1
        if gaps and (gaps[nearest] < SAME_COLOR or len(colors) >= size):
            covered[nearest] += int(counts[index])
        else:
            colors.append(color)
            covered.append(int(counts[index]))

    total = len(pixels)
    swatches = [
        Swatch(
            int(round(color[0])),
            int(round(color[1])),
            int(round(color[2])),
            count / total,
        )
        for color, count in zip(colors, covered, strict=True)
    ]
    return sorted(swatches, key=lambda swatch: swatch.share, reverse=True)
