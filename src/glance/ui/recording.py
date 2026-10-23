"""The controls shown while recording: a timer and Stop, and a frame round the area."""

from typing import override

from PySide6.QtCore import (
    QElapsedTimer,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPen,
    QRegion,
    QShortcut,
)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget

from glance.capture.types import Monitor
from glance.ui.panel import TEXT

RECORD_RED = "#FF5A5F"
_FONT = "Geist, Inter, sans-serif"
_MONO = "'Geist Mono', 'JetBrains Mono', monospace"
GAP = 12
FRAME_MARGIN = 3
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


def bar_position(area: QRect, bounds: QRect, size: QSize) -> QPoint:
    """Where the bar goes, so it stays out of the recording when it can.

    Centered under `area` if there is room below it on the monitor, else above,
    else inside it at the bottom, where it will be in the video.
    """
    x = area.left() + (area.width() - size.width()) // 2
    x = max(bounds.left(), min(x, bounds.left() + bounds.width() - size.width()))
    below = area.top() + area.height() + GAP
    above = area.top() - GAP - size.height()
    if below + size.height() <= bounds.top() + bounds.height():
        y = below
    elif above >= bounds.top():
        y = above
    else:
        y = bounds.top() + bounds.height() - GAP - size.height()
    return QPoint(x, y)


class _Bar(QFrame):
    stop_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bar")
        self.setStyleSheet(_STYLE)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 6, 6)
        layout.setSpacing(10)
        dot = QLabel("●")
        dot.setObjectName("dot")
        self._time = QLabel(format_elapsed(0))
        self._time.setObjectName("time")
        stop = QToolButton()
        stop.setObjectName("stop")
        stop.setText("■  Stop")
        stop.setMinimumHeight(40)
        stop.setCursor(Qt.CursorShape.PointingHandCursor)
        stop.setToolTip("Stop recording (Esc)")
        stop.clicked.connect(self.stop_requested)
        layout.addWidget(dot)
        layout.addWidget(self._time)
        layout.addWidget(stop)

    def set_time(self, text: str) -> None:
        self._time.setText(text)


class _FrameWindow(QWidget):
    """A transparent window over a monitor that draws a dashed frame round the area.

    Only the bar takes the mouse; the mask lets every other click through.
    """

    def __init__(self, area: QRect, bar: _Bar) -> None:
        super().__init__()
        self._area = area
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        bar.setParent(self)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        pen = QPen(QColor(RECORD_RED), 2, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRect(
            self._area.adjusted(
                -FRAME_MARGIN, -FRAME_MARGIN, FRAME_MARGIN, FRAME_MARGIN
            )
        )
        painter.end()

    def pass_clicks_through_except(self, rect: QRect) -> None:
        self.setMask(QRegion(rect))
        self.update()


class RecordingControls(QObject):
    """Shows the timer and Stop while a recording runs.

    Round a selection, a full-screen window draws the frame outside the area (so it
    is not in the video) and the bar sits beside it. For a whole monitor there is
    nothing to frame, so only the bar is shown, and it is in the video.
    Emits `stop_requested` for the Stop button, Esc, Enter and Space.
    """

    stop_requested = Signal()

    def __init__(
        self, area: QRect, monitor: Monitor, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._monitor = monitor
        self._whole = area == monitor.geometry
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._bar = _Bar()
        self._bar.stop_requested.connect(self.stop_requested)
        local = area.translated(-monitor.geometry.topLeft())
        self._window: QWidget
        if self._whole:
            self._window = self._bar
            self._window.setWindowFlag(Qt.WindowType.FramelessWindowHint)
            self._window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        else:
            self._window = _FrameWindow(local, self._bar)
        self._local = local
        for key in ("Escape", "Return", "Enter", "Space"):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(self.stop_requested)

    def show(self) -> None:
        window = self._window
        screens = QGuiApplication.screens()
        handle = window.windowHandle() if window.winId() else None
        if handle is not None and self._monitor.index < len(screens):
            handle.setScreen(screens[self._monitor.index])
        self._bar.adjustSize()
        if isinstance(window, _FrameWindow):
            bounds = QRect(QPoint(0, 0), self._monitor.geometry.size())
            self._bar.move(bar_position(self._local, bounds, self._bar.size()))
            window.showFullScreen()
            window.pass_clicks_through_except(self._bar.geometry())
        else:
            window.show()
        self._clock.start()
        self._timer.start()

    def close(self) -> None:
        self._timer.stop()
        self._window.close()

    def _tick(self) -> None:
        self._bar.set_time(format_elapsed(self._clock.elapsed()))
