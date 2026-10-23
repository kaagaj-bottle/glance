"""The marks that show where a recording is happening: a dashed frame and a Stop bar.

A Wayland client cannot place a window, and a full-screen one makes the compositor
share only that window, so these are drawn by a helper process on X11 (XWayland),
where a window with no decorations can be put at exact coordinates. The frame sits
just outside the area, so it is not in the video, and it is made only of its dashes,
so everything between them is clicked through to the windows beneath. The bar, with a
timer and Stop, is centered under the frame's bottom border.

The parent and the helper talk over the helper's pipes, one word per line: the parent
sends `start` when the recording begins, and the helper sends `stop` when Stop is
clicked. The helper ends when the parent closes its end.
"""

import os
import sys
import threading
from typing import override

from PySide6.QtCore import (
    QElapsedTimer,
    QObject,
    QPoint,
    QProcess,
    QProcessEnvironment,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QRegion
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QToolButton, QWidget

from glance.ui.recording import format_elapsed

COLOR = "#FF5A5F"
GAP = 3
THICKNESS = 3
DASH = 10
SPACE = 7
BAR_GAP = 8
TICK_MS = 250

_FONT = "Geist, Inter, sans-serif"
_MONO = "'Geist Mono', 'JetBrains Mono', monospace"
_STYLE = f"""
QLabel#time {{ background: transparent; color: #FFE9EA; font: 600 14px {_MONO}; }}
QLabel#dot {{ background: transparent; color: {COLOR}; font: 14px {_FONT}; }}
QToolButton#stop {{
    background: {COLOR};
    color: #1A0B0D;
    font: 700 13px {_FONT};
    padding: 0 18px;
    border: none;
    border-radius: 12px;
}}
QToolButton#stop:hover {{ background: #FF7377; }}
"""


def dashes(area: QRect) -> list[QRect]:
    """The dashes of a frame round `area`, in the same coordinates as `area`."""
    outer = frame_bounds(area)
    left, top = outer.left(), outer.top()
    width, height = outer.width(), outer.height()
    pieces: list[QRect] = []
    for start in range(0, width, DASH + SPACE):
        length = min(DASH, width - start)
        pieces.append(QRect(left + start, top, length, THICKNESS))
        pieces.append(QRect(left + start, top + height - THICKNESS, length, THICKNESS))
    for start in range(0, height, DASH + SPACE):
        length = min(DASH, height - start)
        pieces.append(QRect(left, top + start, THICKNESS, length))
        pieces.append(QRect(left + width - THICKNESS, top + start, THICKNESS, length))
    return pieces


def frame_bounds(area: QRect) -> QRect:
    margin = GAP + THICKNESS
    return area.adjusted(-margin, -margin, margin, margin)


def bar_position(area: QRect, monitor: QRect, size: QSize, framed: bool) -> QPoint:
    """Where the bar goes: centered under the area's bottom border.

    If the monitor has no room below, it goes above the top border, and if it has
    none there either (a whole monitor), inside the area at the bottom, where it
    is in the video.
    """
    reach = frame_bounds(area) if framed else area
    x = reach.left() + (reach.width() - size.width()) // 2
    x = max(monitor.left(), min(x, monitor.left() + monitor.width() - size.width()))
    below = reach.top() + reach.height() + BAR_GAP
    above = reach.top() - BAR_GAP - size.height()
    if below + size.height() <= monitor.top() + monitor.height():
        y = below
    elif above >= monitor.top():
        y = above
    else:
        y = monitor.top() + monitor.height() - BAR_GAP - size.height()
    return QPoint(x, y)


class _Frame(QWidget):
    def __init__(self, area: QRect) -> None:
        super().__init__()
        self.setWindowFlags(_FLAGS | Qt.WindowType.WindowTransparentForInput)
        bounds = frame_bounds(area)
        self.setGeometry(bounds)
        region = QRegion()
        for piece in dashes(area):
            region += QRegion(piece.translated(-bounds.topLeft()))
        self.setMask(region)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(COLOR))
        painter.end()


class _Bar(QWidget):
    """A timer and Stop on a dark red tint, so it stands out on any background."""

    stop_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
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
        stop.clicked.connect(self.stop_clicked)
        layout.addWidget(dot)
        layout.addWidget(self._time)
        layout.addWidget(stop)
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    def start_clock(self) -> None:
        self._clock.start()
        self._timer.start()

    def _tick(self) -> None:
        self._time.setText(format_elapsed(self._clock.elapsed()))

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(255, 90, 95, 190))
        painter.setBrush(QColor(52, 17, 21, 242))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 18, 18)
        painter.end()


_FLAGS = (
    Qt.WindowType.Window
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.X11BypassWindowManagerHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowDoesNotAcceptFocus
)


class _Messages(QObject):
    received = Signal(str)


def main(argv: list[str]) -> int:
    """Show the marks for `x y w h  mx my mw mh  framed` until stdin closes."""
    x, y, w, h, mx, my, mw, mh, framed = (int(value) for value in argv)
    area = QRect(x, y, w, h)
    monitor = QRect(mx, my, mw, mh)
    app = QApplication([sys.argv[0]])
    frame = _Frame(area) if framed else None
    bar = _Bar()
    bar.adjustSize()
    bar.move(bar_position(area, monitor, bar.size(), bool(framed)))
    if frame is not None:
        frame.show()
    bar.show()

    def stop() -> None:
        print("stop", flush=True)

    bar.stop_clicked.connect(stop)
    messages = _Messages()

    def handle(line: str) -> None:
        if line == "start":
            bar.start_clock()
        elif line == "quit":
            app.quit()

    messages.received.connect(handle)

    def read_parent() -> None:
        # The parent holds the other end open; it closes when the parent ends.
        for line in sys.stdin:
            messages.received.emit(line.strip())
        messages.received.emit("quit")

    threading.Thread(target=read_parent, daemon=True).start()
    return app.exec()


class RecordingGuide(QObject):
    """Runs the helper that marks where a recording is happening.

    Emits `stop_requested` when Stop is clicked, and `lost` if the helper ends
    while it should be running, so something else can offer a way to stop.
    """

    stop_requested = Signal()
    lost = Signal()

    def __init__(
        self,
        area: QRect,
        monitor: QRect,
        *,
        framed: bool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._args = [
            str(value)
            for value in (
                area.x(),
                area.y(),
                area.width(),
                area.height(),
                monitor.x(),
                monitor.y(),
                monitor.width(),
                monitor.height(),
                int(framed),
            )
        ]
        self._process: QProcess | None = None
        self._buffer = ""

    def start(self) -> bool:
        """Show the marks. False if X11 is not available to draw them."""
        if not os.environ.get("DISPLAY"):
            return False
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("QT_QPA_PLATFORM", "xcb")
        process = QProcess(self)
        process.setProcessEnvironment(environment)
        process.setProgram(sys.executable)
        process.setArguments(["-m", "glance.ui.guide", *self._args])
        process.readyReadStandardOutput.connect(self._read)
        process.finished.connect(self._ended)
        process.start()
        if not process.waitForStarted(3000):
            return False
        self._process = process
        return True

    def begin(self) -> None:
        """The recording has begun: start the timer."""
        if self._process is not None:
            self._process.write(b"start\n")

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        process.finished.disconnect(self._ended)
        process.closeWriteChannel()
        if not process.waitForFinished(2000):
            process.kill()
            process.waitForFinished(1000)

    def _read(self) -> None:
        if self._process is None:
            return
        self._buffer += bytes(self._process.readAllStandardOutput().data()).decode()
        *lines, self._buffer = self._buffer.split("\n")
        if "stop" in lines:
            self.stop_requested.emit()

    def _ended(self) -> None:
        if self._process is not None:
            self._process = None
            self.lost.emit()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
