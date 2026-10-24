from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from glance.search.worker import png_bytes

# A model reads nothing more from a larger image, and a larger upload is slower.
MAX_SIDE = 1280


def png_for_model(image: QImage) -> bytes:
    """The image as PNG data, scaled down so that its longer side is `MAX_SIDE`."""
    if max(image.width(), image.height()) > MAX_SIDE:
        image = image.scaled(
            MAX_SIDE,
            MAX_SIDE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return png_bytes(image)
