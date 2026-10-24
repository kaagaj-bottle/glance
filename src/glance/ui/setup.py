"""The window that asks for the Groq API key, the only thing Glance needs set up."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from glance.ai.client import check_key
from glance.ai.key import CONSOLE_URL, save_key
from glance.background import BackgroundTask
from glance.ui.panel import ACCENT, MUTED, TEXT

_STYLE = f"""
QDialog {{ background: rgb(24, 24, 32); }}
QLabel {{ color: {TEXT}; font: 400 13px sans-serif; }}
QLabel#note {{ color: {MUTED}; font: 400 12px sans-serif; }}
QLabel#error {{ color: #FF8A8A; font: 500 12px sans-serif; }}
QLineEdit {{
    background: rgba(255, 255, 255, 20);
    border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 9px;
    color: {TEXT};
    font: 400 13px monospace;
    padding: 7px 10px;
}}
QPushButton {{
    background: rgba(255, 255, 255, 20);
    border: none;
    border-radius: 9px;
    color: {TEXT};
    font: 600 12px sans-serif;
    padding: 7px 16px;
}}
QPushButton:hover {{ background: rgba(255, 255, 255, 36); }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton#save {{ background: {ACCENT}; color: #12121A; }}
QPushButton#save:disabled {{ background: rgba(255, 255, 255, 25); color: {MUTED}; }}
"""

EXPLANATION = (
    "Translate and Explain are answered by an AI model hosted by Groq. Paste a free "
    f'API key from <a href="{CONSOLE_URL}" style="color: {ACCENT}">'
    "console.groq.com/keys</a> to turn them on."
)
NOTE = (
    "Everything else, including reading text and codes, works without a key. "
    "Text or images are sent to Groq only when you click Translate or Explain."
)


class KeyDialog(QDialog):
    """Asks for the key and keeps it once Groq has accepted it.

    Accepted when a key was saved, rejected on Skip.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Glance: API key")
        self.setStyleSheet(_STYLE)
        self.setMinimumWidth(440)
        self._task: BackgroundTask | None = None

        explanation = QLabel(EXPLANATION)
        explanation.setWordWrap(True)
        explanation.setOpenExternalLinks(True)
        note = QLabel(NOTE)
        note.setObjectName("note")
        note.setWordWrap(True)
        self._key = QLineEdit()
        self._key.setPlaceholderText("gsk_…")
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.returnPressed.connect(self._save)
        self._status = QLabel()
        self._status.setObjectName("error")
        self._status.setWordWrap(True)
        self._skip = QPushButton("Skip")
        self._skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip.clicked.connect(self.reject)
        self._save_button = QPushButton("Save")
        self._save_button.setObjectName("save")
        self._save_button.setDefault(True)
        self._save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_button.clicked.connect(self._save)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self._skip)
        buttons.addWidget(self._save_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(explanation)
        layout.addWidget(self._key)
        layout.addWidget(self._status)
        layout.addWidget(note)
        layout.addLayout(buttons)

    def _save(self) -> None:
        key = self._key.text().strip()
        if not key:
            self._status.setText("Paste your key first, or click Skip")
            return
        self._busy(True, "Checking the key…")
        task = BackgroundTask(lambda: check_key(key), self)
        task.done.connect(lambda: self._accepted(key))
        task.failed.connect(self._rejected)
        task.start()
        self._task = task

    def _rejected(self, message: str) -> None:
        self._busy(False, message)

    def _accepted(self, key: str) -> None:
        try:
            save_key(key)
        except OSError as error:
            self._busy(False, f"Could not save the key ({error.strerror})")
            return
        self.accept()

    def _busy(self, busy: bool, message: str) -> None:
        self._status.setText(message)
        # Red is for errors; "Checking…" is not one.
        self._status.setStyleSheet(f"color: {MUTED}" if busy else "")
        for widget in (self._key, self._skip, self._save_button):
            widget.setEnabled(not busy)
