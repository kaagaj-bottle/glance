from typing import override

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

COPIED_MS = 1500


class TextResultWindow(QWidget):
    """Shows recognized text for editing and copying. Emits `closed` when it goes."""

    closed = Signal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Glance - Recognized text")
        self.resize(520, 360)

        self._edit = QPlainTextEdit(text)
        self._copy = QPushButton("Copy")
        self._copy.setDefault(True)
        self._copy.clicked.connect(self.copy)
        close = QPushButton("Close")
        close.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(close)
        buttons.addWidget(self._copy)
        layout = QVBoxLayout(self)
        layout.addWidget(self._edit)
        layout.addLayout(buttons)

        QShortcut(QKeySequence("Escape"), self, self.close)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.copy)

    def text(self) -> str:
        return self._edit.toPlainText()

    def copy(self) -> None:
        """Copy the edited text, or only the highlighted part if there is one."""
        cursor = self._edit.textCursor()
        QGuiApplication.clipboard().setText(
            cursor.selectedText().replace(" ", "\n")
            if cursor.hasSelection()
            else self.text()
        )
        self._copy.setText("Copied")
        QTimer.singleShot(COPIED_MS, lambda: self._copy.setText("Copy"))

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        super().closeEvent(event)
        self.closed.emit()
