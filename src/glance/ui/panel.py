from enum import Enum, auto
from typing import override

from PySide6.QtCore import QByteArray, QEvent, QPoint, QSize, Qt, Signal, SignalInstance
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from glance.search.engines import ENGINES

ACCENT = "#8B7CFF"
TEXT = "#E8E8EE"
MUTED = "#9A9AA8"
DISABLED = "#5E5E6B"
ICON_SIZE = 18

_FONT = "Geist, Inter, sans-serif"
_MONO = "'Geist Mono', 'JetBrains Mono', monospace"

# 24x24 stroked paths, the same icons as the design.
_ICONS = {
    "selection": '<path d="M6 3v13a2 2 0 0 0 2 2h13M3 6h13a2 2 0 0 1 2 2v13"/>',
    "translate": (
        '<path d="M4 5h9M8.5 3v2M6 5c.5 4 3 7 6.5 8.5M11 5c-.5 4-3 7-6.5 8.5'
        'M13 20l4-9 4 9M14.5 17h5"/>'
    ),
    "screen": (
        '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>'
    ),
    "copy": (
        '<rect x="9" y="9" width="11" height="11" rx="2"/>'
        '<path d="M5 15V6a2 2 0 0 1 2-2h8"/>'
    ),
    "save": '<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>',
    "open": (
        '<path d="M14 4h6v6M20 4l-9 9M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8'
        'a2 2 0 0 1 2-2h4"/>'
    ),
    "palette": (
        '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.8-.9 1.5-1.9-.3-1 .3-2.1 1.4-2.1H17'
        'a4 4 0 0 0 4-4C21 7 17 3 12 3z"/><circle cx="7.5" cy="11" r="1"/>'
        '<circle cx="10" cy="7.5" r="1"/><circle cx="14.5" cy="7.5" r="1"/>'
    ),
    "search": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.2-4.2"/>',
}


class CaptureMode(Enum):
    SELECTION = auto()
    SCREEN = auto()


def icon_pixmap(name: str, color: str, ratio: float = 1.0) -> QPixmap:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round">{_ICONS[name]}</svg>'
    )
    side = round(ICON_SIZE * ratio)
    pixmap = QPixmap(side, side)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


_STYLE = f"""
QFrame#panel {{
    background: rgba(24, 24, 32, 215);
    border: 1px solid rgba(255, 255, 255, 31);
    border-radius: 18px;
}}
QFrame#modes {{
    background: rgba(255, 255, 255, 18);
    border-radius: 12px;
}}
QToolButton {{
    background: transparent;
    border: none;
    border-radius: 10px;
}}
QToolButton:hover {{ background: rgba(255, 255, 255, 23); }}
QToolButton:checked {{ background: rgba(255, 255, 255, 36); }}
QToolButton:disabled {{ background: transparent; }}
QToolButton QLabel {{
    background: transparent;
    color: {TEXT};
    font: 500 11px {_FONT};
}}
QToolButton QLabel#key {{ color: {MUTED}; font: 500 10px {_MONO}; }}
QToolButton#done {{
    background: {ACCENT};
    color: #12121A;
    font: 600 13px {_FONT};
    padding: 0 18px;
    border-radius: 12px;
}}
QToolButton#done:hover {{ background: #9C8FFF; }}
QToolButton#done:disabled {{ background: rgba(255, 255, 255, 25); color: {DISABLED}; }}
QMenu {{
    background: rgb(24, 24, 32);
    border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 10px;
    padding: 4px;
    color: {TEXT};
    font: 500 12px {_FONT};
}}
QMenu::item {{ padding: 7px 16px; border-radius: 7px; }}
QMenu::item:selected {{ background: rgba(255, 255, 255, 30); }}
QMenu::item:disabled {{ color: {MUTED}; }}
QMenu::separator {{
    height: 1px;
    background: rgba(255, 255, 255, 31);
    margin: 4px 6px;
}}
QFrame#divider {{ background: rgba(255, 255, 255, 31); }}
QLabel#hint {{
    background: rgba(20, 20, 26, 180);
    border: 1px solid rgba(255, 255, 255, 26);
    border-radius: 16px;
    color: {TEXT};
    font: 500 12px {_FONT};
    padding: 8px 14px;
}}
"""


def styled_menu(parent: QWidget) -> QMenu:
    menu = QMenu(parent)
    menu.setStyleSheet(_STYLE)
    return menu


class _ActionButton(QToolButton):
    """An icon over a label over the key that triggers it, as in the design."""

    def __init__(
        self,
        icon: str,
        text: str,
        key: str | None = None,
        *,
        accent: bool = False,
        row: bool = False,
    ) -> None:
        super().__init__()
        self._icon = icon
        self._color = ACCENT if accent else TEXT
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._glyph = QLabel()
        label = QLabel(text)
        parts: list[QLabel] = [self._glyph, label]
        if key:
            hint = QLabel(key)
            hint.setObjectName("key")
            parts.append(hint)

        layout = QHBoxLayout(self) if row else QVBoxLayout(self)
        if row:
            self.setMinimumHeight(34)
            layout.setContentsMargins(12, 0, 14, 0)
            layout.setSpacing(7)
        else:
            self.setMinimumWidth(56)
            layout.setContentsMargins(10, 6, 10, 6)
            layout.setSpacing(3)
        for part in parts:
            part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(
                part,
                alignment=Qt.AlignmentFlag.AlignCenter,
            )
        self._paint_icon()

    @override
    def sizeHint(self) -> QSize:
        # A QToolButton ignores its layout when it has no text or icon.
        layout = self.layout()
        return layout.totalMinimumSize() if layout else super().sizeHint()

    @override
    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _paint_icon(self) -> None:
        color = self._color if self.isEnabled() else DISABLED
        for label in self.findChildren(QLabel):
            if not self.isEnabled():
                label.setStyleSheet(f"color: {DISABLED}")
            else:
                label.setStyleSheet("")
        self._glyph.setPixmap(icon_pixmap(self._icon, color, self.devicePixelRatioF()))

    @override
    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self._paint_icon()


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("divider")
    line.setFixedSize(1, 28)
    return line


class CapturePanel(QFrame):
    """The floating bar: capture mode, the actions on the capture, and Done."""

    mode_changed = Signal(object)
    capture_requested = Signal()
    copy_image_requested = Signal()
    save_requested = Signal()
    search_requested = Signal(str)
    colors_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setStyleSheet(_STYLE)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        # Clicks on the bar's padding must not reach the overlay beneath and
        # start a selection.
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)

        modes = QFrame()
        modes.setObjectName("modes")
        modes_layout = QHBoxLayout(modes)
        modes_layout.setContentsMargins(3, 3, 3, 3)
        modes_layout.setSpacing(2)
        self._selection = self._mode_button(
            "selection", "Selection", CaptureMode.SELECTION
        )
        self._screen = self._mode_button("screen", "Screen", CaptureMode.SCREEN)
        self._selection.setChecked(True)
        modes_layout.addWidget(self._selection)
        modes_layout.addWidget(self._screen)
        layout.addWidget(modes)
        layout.addWidget(_divider())

        self._copy_image = self._action("copy", "Copy", "C", self.copy_image_requested)
        self._save = self._action("save", "Save", "S", self.save_requested)
        layout.addWidget(self._copy_image)
        layout.addWidget(self._save)
        layout.addWidget(_divider())

        self._search = _ActionButton("search", "Search", "I", accent=True)
        self._search.clicked.connect(self.show_search_menu)
        layout.addWidget(self._search)
        self._colors = _ActionButton("palette", "Colors", "K")
        self._colors.clicked.connect(self.colors_requested)
        layout.addWidget(self._colors)
        layout.addWidget(_divider())

        self._done = QToolButton()
        self._done.setObjectName("done")
        self._done.setText("Done")
        self._done.setMinimumHeight(44)
        self._done.setCursor(Qt.CursorShape.PointingHandCursor)
        self._done.setToolTip("Copy and save the capture (Enter)")
        self._done.clicked.connect(self.capture_requested)
        layout.addWidget(self._done)

    def set_capture_enabled(self, enabled: bool) -> None:
        for button in (
            self._copy_image,
            self._save,
            self._search,
            self._colors,
            self._done,
        ):
            button.setEnabled(enabled)

    def show_search_menu(self) -> None:
        """Offer the engines to search the capture with. Choosing one sends it."""
        if not self._search.isEnabled():
            return
        menu = styled_menu(self)
        menu.addAction("Search the image with…").setEnabled(False)
        menu.addSeparator()
        for engine in ENGINES:
            action = menu.addAction(engine.name)
            action.triggered.connect(
                lambda _checked=False, key=engine.key: self.search_requested.emit(key)
            )
        menu.addSeparator()
        menu.addAction("Opens your browser and uploads the image").setEnabled(False)
        # Above the button: the bar sits at the bottom of the screen.
        above = self._search.mapToGlobal(self._search.rect().topLeft())
        menu.exec(above - QPoint(0, menu.sizeHint().height() + 6))

    def _action(
        self,
        icon: str,
        text: str,
        key: str | None,
        signal: SignalInstance,
        *,
        accent: bool = False,
    ) -> _ActionButton:
        button = _ActionButton(icon, text, key, accent=accent)
        button.clicked.connect(signal)
        return button

    def _mode_button(self, icon: str, text: str, mode: CaptureMode) -> _ActionButton:
        button = _ActionButton(icon, text, row=True)
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.clicked.connect(lambda: self.mode_changed.emit(mode))
        return button


def _key(name: str) -> str:
    return f'<span style="font-family:{_MONO};color:{MUTED}">{name}</span>'


HINT = f"Drag to select · {_key('Enter')} keep · {_key('Esc')} cancel"
PICK_HINT = f"Click a pixel to copy its color · {_key('Esc')} back"


def hint_pill(parent: QWidget) -> QLabel:
    """The line of key hints shown at the top of the screen."""
    pill = QLabel(HINT, parent)
    pill.setObjectName("hint")
    pill.setStyleSheet(_STYLE)
    pill.setTextFormat(Qt.TextFormat.RichText)
    pill.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    pill.adjustSize()
    return pill
