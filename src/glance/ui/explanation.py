"""The card that shows an explanation next to the selection."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from glance.ui.translation import _STYLE, WIDTH  # pyright: ignore[reportPrivateUsage]


class ExplanationCard(QFrame):
    """Shows that an explanation is on its way, then the text or what went wrong.

    Emits `copy_requested` with the explanation.
    """

    copy_requested = Signal(str)

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
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._copy = QPushButton("Copy")
        self._copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy.clicked.connect(lambda: self.copy_requested.emit(self._text.text()))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(self._status)
        layout.addWidget(self._text)
        layout.addWidget(self._copy, alignment=Qt.AlignmentFlag.AlignRight)
        self.show_pending()

    def show_pending(self) -> None:
        self._status.setText("Explaining…")
        self._text.hide()
        self._copy.hide()
        self.adjustSize()

    def show_explanation(self, text: str) -> None:
        self._status.setText("sent to Groq")
        self._text.setText(text)
        self._text.show()
        self._copy.show()
        self.adjustSize()

    def show_error(self, message: str) -> None:
        self._status.setText(message)
        self._text.hide()
        self._copy.hide()
        self.adjustSize()
