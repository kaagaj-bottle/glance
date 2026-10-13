"""QR codes and barcodes found in an image.

Decoding is offline (zxing-cpp). What a code says is untrusted, so only a web
link or an email address is ever offered to be opened, as in `smart`; anything
else can only be copied.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any
from urllib.parse import urlsplit

import numpy as np
import zxingcpp
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from glance.ocr.types import Box
from glance.payloads import Wifi, parse_contact, parse_geo, parse_wifi
from glance.smart import MAX_LABEL, Entity, Kind

# Retail codes: what is printed under them is a product number worth searching.
_PRODUCT = {"EAN-13", "EAN-8", "UPC-A", "UPC-E", "ISBN"}
_EMAIL_PREFIX = "mailto:"


class ItemKind(Enum):
    OPEN = auto()
    COPY = auto()
    SEARCH = auto()
    WIFI = auto()


@dataclass(frozen=True, slots=True)
class Item:
    """One thing the user can do with a code.

    `value` is the `Entity` to open, the `Wifi` to join, or the text to copy or
    search for.
    """

    kind: ItemKind
    label: str
    value: Entity | Wifi | str


def _short(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= MAX_LABEL else line[: MAX_LABEL - 1] + "…"


@dataclass(frozen=True, slots=True)
class Code:
    format: str
    text: str
    # Corners in the decoded image's pixels, clockwise from the top-left.
    box: Box

    @property
    def kind(self) -> str:
        """What the code holds: "Wi-Fi", "Location", "Contact", or its format."""
        if parse_wifi(self.text):
            return "Wi-Fi"
        if parse_geo(self.text):
            return "Location"
        if parse_contact(self.text):
            return "Contact"
        return self.format

    @property
    def label(self) -> str:
        """The content in a few words, on one line: a network, a place, a name."""
        if wifi := parse_wifi(self.text):
            return _short(f"{wifi.ssid} ({wifi.security or 'enterprise'})")
        if geo := parse_geo(self.text):
            return geo.text
        if contact := parse_contact(self.text):
            return _short(contact.name)
        return _short(self.text)

    @property
    def mark(self) -> str:
        """The word that leads the pill: what the code is."""
        kind = self.kind
        if kind == self.format:
            return "QR" if "QR" in kind else "Barcode"
        return kind

    @property
    def items(self) -> list[Item]:
        """What can be done with the code. There is always a way to copy it."""
        if wifi := parse_wifi(self.text):
            items: list[Item] = []
            if wifi.connectable:
                items.append(
                    Item(ItemKind.WIFI, f"Connect to “{_short(wifi.ssid)}”", wifi)
                )
            items.append(Item(ItemKind.COPY, "Copy network name", wifi.ssid))
            if wifi.password:
                items.append(Item(ItemKind.COPY, "Copy password", wifi.password))
            return items
        if geo := parse_geo(self.text):
            place = Entity(Kind.LINK, geo.url, geo.url)
            return [
                Item(ItemKind.OPEN, "Open map", place),
                Item(ItemKind.COPY, "Copy coordinates", geo.text),
            ]
        if contact := parse_contact(self.text):
            items = [Item(ItemKind.COPY, "Copy contact", contact.text)]
            items += [
                Item(ItemKind.COPY, f"Copy phone {_short(phone)}", phone)
                for phone in contact.phones
            ]
            items += [
                Item(ItemKind.COPY, f"Copy email {_short(email)}", email)
                for email in contact.emails
            ]
            return items
        items = []
        if entity := self.entity:
            items.append(
                Item(
                    ItemKind.OPEN,
                    "Email" if entity.kind is Kind.EMAIL else "Open link",
                    entity,
                )
            )
        items.append(Item(ItemKind.COPY, "Copy", self.text))
        if self.searchable:
            items.append(Item(ItemKind.SEARCH, "Search", self.text))
        return items

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
