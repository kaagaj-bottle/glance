"""The controls shown while recording: a timer and Stop."""

from typing import override

from PySide6.QtCore import QElapsedTimer, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton

from glance.ui.panel import TEXT

RECORD_RED = "#FF5A5F"
_FONT = "Geist, Inter, sans-serif"
_MONO = "'Geist Mono', 'JetBrains Mono', monospace"
TICK_MS = 250

_STYLE = f"""
QFrame#bar {{
    background: rgba(24, 24, 32, 230);
    border: 1px solid rgba(255, 255, 255, 31);
    border-radius: 18px;
}}
QLabel#time {{ background: transparent; color: {TEXT}; font: 500 14px {_MONO}; }}
QLabel#dot {{ background: transparent; color: {RECORD_RED}; font: 14px {_FONT}; }}
QToolButton#stop {{
    background: {RECORD_RED};
    color: #12121A;
    font: 600 13px {_FONT};
    padding: 0 18px;
    border: none;
    border-radius: 12px;
}}
QToolButton#stop:hover {{ background: #FF7377; }}
"""


def format_elapsed(milliseconds: int) -> str:
    seconds = max(0, milliseconds) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


class RecordingControls(QFrame):
    """The timer and Stop, shown while a recording runs.

    A Wayland client cannot choose where a plain window goes, and a full-screen one
    (to frame the area) makes the compositor stop sharing everything beneath it, so
    this is a small bar the compositor places. It can be dragged out of the way; it
    is part of the video only while it is over the recorded area.
    Emits `stop_requested` for the Stop button, Esc, Enter and Space.
    """

    stop_requested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__()
        self.setObjectName("bar")
        self.setStyleSheet(_STYLE)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 6, 6)
        layout.setSpacing(10)
        dot = QLabel("\u25cf")
        dot.setObjectName("dot")
        self._time = QLabel(format_elapsed(0))
        self._time.setObjectName("time")
        stop = QToolButton()
        stop.setObjectName("stop")
        stop.setText("\u25a0  Stop")
        stop.setMinimumHeight(40)
        stop.setCursor(Qt.CursorShape.PointingHandCursor)
        stop.setToolTip("Stop recording (Esc)")
        stop.clicked.connect(self.stop_requested)
        layout.addWidget(dot)
        layout.addWidget(self._time)
        layout.addWidget(stop)

        for key in ("Escape", "Return", "Enter", "Space"):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(self.stop_requested)

    def start(self) -> None:
        self.show()
        self._clock.start()
        self._timer.start()

    def finish(self) -> None:
        self._timer.stop()
        self.close()

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.windowHandle().startSystemMove()

    def _tick(self) -> None:
        self._time.setText(format_elapsed(self._clock.elapsed()))
