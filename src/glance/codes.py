"""QR codes and barcodes found in an image.

Decoding is offline (zxing-cpp). What a code says is untrusted, so only a web
link or an email address is ever offered to be opened, as in `smart`; anything
else can only be copied.
"""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import numpy as np
import zxingcpp
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from glance.ocr.types import Box
from glance.smart import MAX_LABEL, Entity, Kind

# Retail codes: what is printed under them is a product number worth searching.
_PRODUCT = {"EAN-13", "EAN-8", "UPC-A", "UPC-E", "ISBN"}
_EMAIL_PREFIX = "mailto:"


@dataclass(frozen=True, slots=True)
class Code:
    format: str
    text: str
    # Corners in the decoded image's pixels, clockwise from the top-left.
    box: Box

    @property
    def label(self) -> str:
        """The text for a menu entry: the content on one line, shortened."""
        line = " ".join(self.text.split())
        return line if len(line) <= MAX_LABEL else line[: MAX_LABEL - 1] + "…"

    @property
    def entity(self) -> Entity | None:
        """What opening the code does, if its whole content is a link or address."""
        text = self.text.strip()
        if text != self.text or any(c.isspace() for c in text):
            return None
        if text.lower().startswith(_EMAIL_PREFIX):
            address = text[len(_EMAIL_PREFIX) :].split("?")[0]
            if "@" not in address:
                return None
            return Entity(Kind.EMAIL, address, text)
        parts = urlsplit(text)
        if parts.scheme.lower() in ("http", "https") and parts.hostname:
            return Entity(Kind.LINK, text, text)
        return None

    @property
    def searchable(self) -> bool:
        return self.format in _PRODUCT


def read_codes(image: QImage) -> list[Code]:
    """The distinct codes in the image, top to bottom."""
    if image.isNull():
        return []
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    width, height, stride = gray.width(), gray.height(), gray.bytesPerLine()
    rows = np.frombuffer(gray.constBits(), dtype=np.uint8, count=stride * height)
    pixels = rows.reshape(height, stride)[:, :width]
    found: dict[str, Code] = {}
    barcodes: list[Any] = zxingcpp.read_barcodes(pixels)
    for barcode in barcodes:
        if not barcode.valid or not barcode.text or barcode.text in found:
            continue
        place = barcode.position
        box = tuple(
            (float(p.x), float(p.y))
            for p in (
                place.top_left,
                place.top_right,
                place.bottom_right,
                place.bottom_left,
            )
        )
        found[barcode.text] = Code(str(barcode.format), str(barcode.text), box)
    return sorted(found.values(), key=lambda code: min(y for _, y in code.box))


class _Signals(QObject):
    done = Signal(object)


class _Job(QRunnable):
    def __init__(self, image: QImage, signals: _Signals) -> None:
        super().__init__()
        self._image = image
        self._signals = signals

    def run(self) -> None:
        self._signals.done.emit(read_codes(self._image))


class CodeTask(QObject):
    """Reads codes off the UI thread. Emits `done` with a list of `Code`."""

    done = Signal(object)

    def __init__(self, image: QImage, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._image = image
        # Held so the signals outlive the worker thread's call to run().
        self._signals = _Signals(self)
        self._signals.done.connect(self.done)

    def start(self) -> None:
        QThreadPool.globalInstance().start(_Job(self._image, self._signals))
