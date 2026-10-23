"""The card that shows a translation next to the selection."""

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from glance.translate.languages import LANGUAGES
from glance.translate.types import Translation
from glance.ui.panel import ACCENT, MUTED, TEXT

WIDTH = 420
MARGIN = 10

_STYLE = f"""
QFrame#card {{
    background: rgba(24, 24, 32, 235);
    border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 14px;
}}
QLabel {{ background: transparent; color: {TEXT}; font: 400 14px sans-serif; }}
QLabel#status {{ color: {MUTED}; font: 500 11px sans-serif; }}
QComboBox {{
    background: rgba(255, 255, 255, 20);
    border: none;
    border-radius: 9px;
    color: {TEXT};
    font: 500 12px sans-serif;
    padding: 4px 10px;
}}
QComboBox::drop-down {{ border: none; width: 16px; }}
QComboBox QAbstractItemView {{
    background: rgb(24, 24, 32);
    color: {TEXT};
    selection-background-color: rgba(139, 124, 255, 90);
    border: 1px solid rgba(255, 255, 255, 40);
    outline: none;
}}
QPushButton {{
    background: rgba(255, 255, 255, 20);
    border: none;
    border-radius: 9px;
    color: {ACCENT};
    font: 600 12px sans-serif;
    padding: 6px 14px;
}}
QPushButton:hover {{ background: rgba(255, 255, 255, 36); }}
"""


class TranslationCard(QFrame):
    """Shows that a translation is on its way, then the text or what went wrong.

    Emits `copy_requested` with the translated text, and `language_changed` with
    the code of the language picked to translate into.
    """

    copy_requested = Signal(str)
    language_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(_STYLE)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        # Clicks on the card must not reach the overlay beneath and start a selection.
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        self.setFixedWidth(WIDTH)

        self._status = QLabel()
        self._status.setObjectName("status")
        self._language = QComboBox()
        self._language.setCursor(Qt.CursorShape.PointingHandCursor)
        self._language.setMaxVisibleItems(12)
        for code, name in LANGUAGES:
            self._language.addItem(name, code)
        self._language.activated.connect(self._on_picked)
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._copy = QPushButton("Copy")
        self._copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy.clicked.connect(lambda: self.copy_requested.emit(self._text.text()))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(self._status, stretch=1)
        header.addWidget(self._language)
        layout.addLayout(header)
        layout.addWidget(self._text)
        layout.addWidget(self._copy, alignment=Qt.AlignmentFlag.AlignRight)
        self.show_pending()

    def set_target(self, code: str) -> None:
        """Show which language is picked, without asking for a translation."""
        index = self._language.findData(code)
        if index >= 0:
            self._language.setCurrentIndex(index)

    def _on_picked(self, index: int) -> None:
        self.language_changed.emit(str(self._language.itemData(index)))

    def show_pending(self) -> None:
        self._status.setText("Translating…")
        self._text.hide()
        self._copy.hide()
        self.adjustSize()

    def show_translation(self, translation: Translation) -> None:
        source = translation.source or "?"
        self._status.setText(f"from {source} · sent to {translation.service}")
        self._text.setText(translation.text)
        self._text.show()
        self._copy.show()
        self.adjustSize()

    def show_error(self, message: str) -> None:
        self._status.setText(message)
        self._text.hide()
        self._copy.hide()
        self.adjustSize()

    @property
    def translated(self) -> str:
        return self._text.text()


def card_position(card: QWidget, selection: QRect, bounds: QRect) -> tuple[int, int]:
    """Below the selection if the card fits there, else above it, kept on screen."""
    x = max(
        bounds.left() + MARGIN,
        min(selection.left(), bounds.right() - card.width() - MARGIN),
    )
    below = selection.bottom() + MARGIN
    if below + card.height() <= bounds.bottom() - MARGIN:
        return x, below
    above = selection.top() - MARGIN - card.height()
    return x, max(bounds.top() + MARGIN, above)
