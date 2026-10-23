"""The small labels drawn on the selection itself: its size, its word count, the
QR code or barcode found in it, and the Copy, Translate and Search bubble that
appears next to picked words.

Everything is laid out in desktop coordinates, so it can sit on any monitor the
selection touches. The overlay windows only paint it; the overlay asks
`action_at` what a click on it means.
"""

from dataclasses import dataclass
from enum import Enum, auto

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen

from glance.ui.panel import icon_pixmap

ACCENT = QColor("#8B7CFF")
ON_ACCENT = QColor("#12121A")
TEXT = QColor("#E8E8EE")
MUTED = QColor("#9A9AA8")
SURFACE = QColor(24, 24, 32, 235)
EDGE = QColor(255, 255, 255, 40)

GAP = 8
PILL_PADDING = 9
BUBBLE_HEIGHT = 38
BUBBLE_GAP = 10
ITEM_PADDING = 12
ICON = 18


class Action(Enum):
    ALL_WORDS = auto()
    COPY = auto()
    TRANSLATE = auto()
    SEARCH = auto()
    EXPLAIN = auto()
    OPEN = auto()
    CODES = auto()


@dataclass(frozen=True, slots=True)
class Pill:
    rect: QRect
    text: str


@dataclass(frozen=True, slots=True)
class Bubble:
    rect: QRect
    count: str
    copy: QRect
    translate: QRect
    search: QRect
    explain: QRect
    # Only when the picked words hold a link or an email address.
    open: QRect | None = None
    open_label: str = ""


@dataclass(frozen=True, slots=True)
class Chrome:
    size: Pill | None = None
    words: Pill | None = None
    codes: Pill | None = None
    bubble: Bubble | None = None


def _mono() -> QFont:
    font = QFont("Geist Mono, JetBrains Mono, monospace")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setWeight(QFont.Weight.Medium)
    font.setPixelSize(12)
    return font


def _sans() -> QFont:
    font = QFont("Geist, Inter, sans-serif")
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setWeight(QFont.Weight.Medium)
    font.setPixelSize(12)
    return font


def _count_text(count: int) -> str:
    return f"{count} word" if count == 1 else f"{count} words"


def layout(
    selection: QRect | None,
    size_text: str,
    word_count: int,
    picked: QRect | None,
    picked_count: int,
    desktop: QRect,
    open_label: str = "",
    code_text: str = "",
) -> Chrome:
    """Where each label goes. `picked` is the bounding box of the picked words.

    `open_label` adds an item to the bubble for opening a link or an address.
    `code_text` adds a pill for a code found in the selection: a mark such as "QR",
    a space, then what to show beside it.
    """
    if selection is None:
        return Chrome()

    mono = QFontMetrics(_mono())
    height = mono.height() + 10
    width = mono.horizontalAdvance(size_text) + 2 * PILL_PADDING
    # Above the selection if there is room, otherwise just inside it.
    top = selection.top() - height - GAP
    if top < desktop.top():
        top = selection.top() + GAP
    size = Pill(QRect(selection.left(), top, width, height), size_text)

    words = None
    # Once every word is covered by the bubble, its own count says it all.
    if word_count and picked_count != word_count:
        text = f"Aa {_count_text(word_count)}"
        sans = QFontMetrics(_sans())
        words = Pill(
            QRect(
                size.rect.right() + 1 + 6,
                top,
                sans.horizontalAdvance(text) + 2 * PILL_PADDING + 2,
                height,
            ),
            text,
        )

    codes = None
    if code_text:
        sans = QFontMetrics(_sans())
        beside = words or size
        codes = Pill(
            QRect(
                beside.rect.right() + 1 + 6,
                top,
                sans.horizontalAdvance(code_text) + 2 * PILL_PADDING + 2,
                height,
            ),
            code_text,
        )

    bubble = None
    if picked is not None and picked_count:
        taken = [pill.rect for pill in (size, words, codes) if pill is not None]
        bubble = _bubble(picked, picked_count, desktop, taken, open_label)
    return Chrome(size, words, codes, bubble)


def _bubble(
    picked: QRect, count: int, desktop: QRect, taken: list[QRect], open_label: str
) -> Bubble:
    sans = QFontMetrics(_sans())
    label = _count_text(count)
    copy_width = ICON + 6 + sans.horizontalAdvance("Copy") + 2 * ITEM_PADDING
    translate_width = ICON + 6 + sans.horizontalAdvance("Translate") + 2 * ITEM_PADDING
    search_width = ICON + 6 + sans.horizontalAdvance("Search") + 2 * ITEM_PADDING
    explain_width = ICON + 6 + sans.horizontalAdvance("Explain text") + 2 * ITEM_PADDING
    open_width = 0
    if open_label:
        open_width = ICON + 6 + sans.horizontalAdvance(open_label) + 2 * ITEM_PADDING
    label_width = sans.horizontalAdvance(label) + 2 * ITEM_PADDING
    width = label_width + 1 + copy_width + translate_width + search_width
    width += explain_width + open_width
    width += 8

    x = picked.center().x() - width // 2
    x = max(desktop.left() + 8, min(x, desktop.right() - width - 8))
    above = QRect(x, picked.top() - BUBBLE_GAP - BUBBLE_HEIGHT, width, BUBBLE_HEIGHT)
    below = QRect(x, picked.bottom() + BUBBLE_GAP, width, BUBBLE_HEIGHT)
    fits_above = above.top() >= desktop.top() and not any(
        above.intersects(rect) for rect in taken
    )
    rect = above if fits_above else below

    inner = rect.adjusted(4, 4, -4, -4)
    copy = QRect(
        rect.left() + 4 + label_width + 1, inner.top(), copy_width, inner.height()
    )
    translate = QRect(copy.right() + 1, inner.top(), translate_width, inner.height())
    search = QRect(translate.right() + 1, inner.top(), search_width, inner.height())
    explain = QRect(search.right() + 1, inner.top(), explain_width, inner.height())
    if not open_label:
        return Bubble(rect, label, copy, translate, search, explain)
    opener = QRect(explain.right() + 1, inner.top(), open_width, inner.height())
    return Bubble(rect, label, copy, translate, search, explain, opener, open_label)


def code_pill(text: str, area: QRect) -> Chrome:
    """Just the code pill, in the top-left corner of `area` (for a whole screen)."""
    sans = QFontMetrics(_sans())
    height = QFontMetrics(_mono()).height() + 10
    width = sans.horizontalAdvance(text) + 2 * PILL_PADDING + 2
    rect = QRect(area.left() + 2 * GAP, area.top() + 2 * GAP, width, height)
    return Chrome(codes=Pill(rect, text))


def action_at(chrome: Chrome, point: QPoint) -> Action | None:
    if chrome.bubble is not None:
        if chrome.bubble.copy.contains(point):
            return Action.COPY
        if chrome.bubble.translate.contains(point):
            return Action.TRANSLATE
        if chrome.bubble.search.contains(point):
            return Action.SEARCH
        if chrome.bubble.explain.contains(point):
            return Action.EXPLAIN
        if chrome.bubble.open is not None and chrome.bubble.open.contains(point):
            return Action.OPEN
    if chrome.words is not None and chrome.words.rect.contains(point):
        return Action.ALL_WORDS
    if chrome.codes is not None and chrome.codes.rect.contains(point):
        return Action.CODES
    return None


def blocks(chrome: Chrome, point: QPoint) -> bool:
    """Whether a press here lands on a label and so must not reach the selection."""
    return action_at(chrome, point) is not None or (
        chrome.bubble is not None and chrome.bubble.rect.contains(point)
    )


def paint(painter: QPainter, chrome: Chrome, ratio: float) -> None:
    """Paint in desktop coordinates; the caller translates for its monitor."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    if chrome.size is not None:
        painter.setBrush(ACCENT)
        painter.drawRoundedRect(chrome.size.rect, 8, 8)
        painter.setFont(_mono())
        painter.setPen(ON_ACCENT)
        painter.drawText(
            chrome.size.rect, Qt.AlignmentFlag.AlignCenter, chrome.size.text
        )
    if chrome.words is not None:
        _paint_pill(painter, chrome.words)
    if chrome.codes is not None:
        _paint_pill(painter, chrome.codes)
    if chrome.bubble is not None:
        _paint_bubble(painter, chrome.bubble, ratio)
    painter.restore()


def _paint_pill(painter: QPainter, pill: Pill) -> None:
    """A dark pill: its text's first word in the accent color, the rest in white."""
    mark = pill.text.partition(" ")[0]
    painter.setPen(QPen(EDGE, 1))
    painter.setBrush(QColor(20, 20, 26, 205))
    painter.drawRoundedRect(QRectF(pill.rect).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
    painter.setFont(_sans())
    rect = pill.rect.adjusted(PILL_PADDING, 0, -PILL_PADDING, 0)
    painter.setPen(ACCENT)
    painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, mark)
    offset = QFontMetrics(painter.font()).horizontalAdvance(f"{mark} ")
    painter.setPen(TEXT)
    painter.drawText(
        rect.adjusted(offset, 0, 0, 0),
        Qt.AlignmentFlag.AlignVCenter,
        pill.text.removeprefix(f"{mark} "),
    )


def _paint_bubble(painter: QPainter, bubble: Bubble, ratio: float) -> None:
    painter.setPen(QPen(EDGE, 1))
    painter.setBrush(SURFACE)
    painter.drawRoundedRect(QRectF(bubble.rect).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
    painter.setFont(_sans())

    label = QRect(
        bubble.rect.left(),
        bubble.rect.top(),
        bubble.copy.left() - bubble.rect.left(),
        bubble.rect.height(),
    )
    painter.setPen(TEXT)
    painter.drawText(label, Qt.AlignmentFlag.AlignCenter, bubble.count)
    painter.setPen(QPen(EDGE, 1))
    x = bubble.copy.left() - 0.5
    painter.drawLine(
        QPointF(x, bubble.rect.top() + 9), QPointF(x, bubble.rect.bottom() - 9)
    )

    items = [
        (bubble.copy, "copy", "Copy"),
        (bubble.translate, "translate", "Translate"),
        (bubble.search, "search", "Search"),
        (bubble.explain, "explain", "Explain text"),
    ]
    if bubble.open is not None:
        items.append((bubble.open, "open", bubble.open_label))
    for rect, icon, text in items:
        pixmap = icon_pixmap(icon, "#8B7CFF", ratio)
        painter.drawPixmap(
            QPointF(
                rect.left() + ITEM_PADDING,
                rect.center().y() - ICON / 2 + 1,
            ),
            pixmap,
        )
        painter.setPen(TEXT)
        painter.drawText(
            rect.adjusted(ITEM_PADDING + ICON + 6, 0, 0, 0),
            Qt.AlignmentFlag.AlignVCenter,
            text,
        )
