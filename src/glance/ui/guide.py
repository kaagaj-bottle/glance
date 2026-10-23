"""A dashed frame round the area being recorded.

A Wayland client cannot place a window, and a full-screen one makes the compositor
share only that window, so the frame is drawn by a helper process on X11 (XWayland),
where a window with no decorations can be put at exact coordinates. The frame sits
just outside the area, so it is not in the video, and it is made only of its dashes,
so everything between them is clicked through to the windows beneath.
"""

import os
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QRegion
from PySide6.QtWidgets import QApplication, QWidget

COLOR = "#FF5A5F"
GAP = 3
THICKNESS = 3
DASH = 10
SPACE = 7


def dashes(area: QRect) -> list[QRect]:
    """The dashes of a frame round `area`, in the same coordinates as `area`."""
    outer = area.adjusted(
        -GAP - THICKNESS, -GAP - THICKNESS, GAP + THICKNESS, GAP + THICKNESS
    )
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


class _Frame(QWidget):
    def __init__(self, area: QRect) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.X11BypassWindowManagerHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        bounds = frame_bounds(area)
        self.setGeometry(bounds)
        origin = bounds.topLeft()
        region = QRegion()
        for piece in dashes(area):
            region += QRegion(piece.translated(-origin))
        self.setMask(region)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(COLOR))
        painter.end()


class _Quit(QObject):
    requested = Signal()


def main(argv: list[str]) -> int:
    """Show the frame round the `x y width height` area until stdin closes."""
    x, y, width, height = (int(value) for value in argv)
    app = QApplication([sys.argv[0]])
    frame = _Frame(QRect(QPoint(x, y), QRect(0, 0, width, height).size()))
    frame.show()
    quit_signal = _Quit()
    quit_signal.requested.connect(app.quit)

    def wait_for_parent() -> None:
        # The parent holds the other end open; it closes when the parent ends.
        sys.stdin.buffer.read()
        quit_signal.requested.emit()

    threading.Thread(target=wait_for_parent, daemon=True).start()
    return app.exec()


class RecordingGuide:
    """Runs the frame helper for one recording."""

    def __init__(self, area: QRect) -> None:
        self._area = area
        self._process: subprocess.Popen[bytes] | None = None

    def start(self) -> bool:
        """Show the frame. False if X11 is not available to draw it."""
        if not os.environ.get("DISPLAY"):
            return False
        area = self._area
        try:
            self._process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "glance.ui.guide",
                    *(
                        str(v)
                        for v in (area.x(), area.y(), area.width(), area.height())
                    ),
                ],
                env={**os.environ, "QT_QPA_PLATFORM": "xcb"},
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        return True

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
