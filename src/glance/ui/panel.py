from enum import Enum, auto

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton, QWidget


class CaptureMode(Enum):
    SELECTION = auto()
    SCREEN = auto()


_STYLE = """
QFrame#panel {
    background: rgba(36, 36, 36, 235);
    border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 22px;
}
QToolButton {
    color: white;
    background: transparent;
    border: none;
    border-radius: 16px;
    padding: 7px 16px;
}
QToolButton:hover { background: rgba(255, 255, 255, 30); }
QToolButton:checked { background: rgba(255, 255, 255, 60); }
QToolButton#capture { background: #3584e4; font-weight: bold; }
QToolButton#capture:hover { background: #4a90e8; }
QToolButton#capture:disabled { background: rgba(255, 255, 255, 25); color: #888; }
"""


class CapturePanel(QFrame):
    """The floating bar with the capture modes and the capture and close buttons."""

    mode_changed = Signal(object)
    capture_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setStyleSheet(_STYLE)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        # Clicks on the bar's padding must not reach the overlay beneath and
        # start a selection.
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        self._selection = self._mode_button("Selection", CaptureMode.SELECTION)
        self._screen = self._mode_button("Screen", CaptureMode.SCREEN)
        self._selection.setChecked(True)
        layout.addWidget(self._selection)
        layout.addWidget(self._screen)

        self._capture = QToolButton()
        self._capture.setObjectName("capture")
        self._capture.setText("Capture")
        self._capture.clicked.connect(self.capture_requested)
        layout.addWidget(self._capture)

        close = QToolButton()
        close.setText("✕")
        close.setToolTip("Cancel (Esc)")
        close.clicked.connect(self.close_requested)
        layout.addWidget(close)

        for button in self.findChildren(QToolButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_capture_enabled(self, enabled: bool) -> None:
        self._capture.setEnabled(enabled)

    def _mode_button(self, text: str, mode: CaptureMode) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.clicked.connect(lambda: self.mode_changed.emit(mode))
        return button
