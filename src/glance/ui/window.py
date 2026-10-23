from typing import override

from PySide6.QtCore import (
    QPoint,
    QPointF,
    QRect,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPolygonF,
    QResizeEvent,
)
from PySide6.QtWidgets import QLabel, QWidget

from glance.capture.types import Monitor
from glance.ui import chrome
from glance.ui.chrome import ACCENT, Chrome
from glance.ui.panel import (
    CaptureMode,
    CapturePanel,
    hint_pill,
)
from glance.ui.selection import (
    Handle,
)

PANEL_MARGIN = 32
HINT_MARGIN = 28

DIM = QColor(8, 8, 14, 148)
WORD_TINT = QColor(139, 124, 255, 45)
WORD_FILL = QColor(139, 124, 255, 150)

CURSORS = {
    Handle.TOP_LEFT: Qt.CursorShape.SizeFDiagCursor,
    Handle.BOTTOM_RIGHT: Qt.CursorShape.SizeFDiagCursor,
    Handle.TOP_RIGHT: Qt.CursorShape.SizeBDiagCursor,
    Handle.BOTTOM_LEFT: Qt.CursorShape.SizeBDiagCursor,
    Handle.TOP: Qt.CursorShape.SizeVerCursor,
    Handle.BOTTOM: Qt.CursorShape.SizeVerCursor,
    Handle.LEFT: Qt.CursorShape.SizeHorCursor,
    Handle.RIGHT: Qt.CursorShape.SizeHorCursor,
    Handle.MOVE: Qt.CursorShape.SizeAllCursor,
}


class OverlayWindow(QWidget):
    """A frozen copy of one monitor, dimmed, with the shared selection on top.

    The window only draws and reports the pointer, always in logical desktop
    coordinates. `ScreenshotOverlay` owns the selection and decides what it
    means. While a button is held, Wayland keeps delivering the pointer to the
    window where the drag began, so a drag can run past this monitor's edges and
    the coordinates then lie outside it.
    """

    pressed = Signal(QPoint)
    dragged = Signal(QPoint)
    hovered = Signal(QPoint)
    released = Signal(QPoint)

    def __init__(self, monitor: Monitor, image: QImage) -> None:
        super().__init__()
        self.monitor = monitor
        self._image = image
        self._mode = CaptureMode.SELECTION
        self._selection: QRect | None = None
        self._chrome = Chrome()
        self._highlighted = False
        self._panel: CapturePanel | None = None
        self._hint: QLabel | None = None
        self._words: list[QPolygonF] = []
        self._chosen = range(0)

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_state(
        self,
        mode: CaptureMode,
        selection: QRect | None,
        labels: Chrome,
        highlighted: bool,
    ) -> None:
        self._mode = mode
        self._selection = selection
        self._chrome = labels
        self._highlighted = highlighted
        self.update()

    def set_words(self, shapes: list[QPolygonF], chosen: range) -> None:
        """The words to tint, in desktop coordinates, and which are picked."""
        self._words = shapes
        self._chosen = chosen
        self.update()

    def set_hint(self, text: str) -> None:
        if self._hint is not None:
            self._hint.setText(text)
            self._hint.adjustSize()
            self._place_panel()

    def attach_panel(self, panel: CapturePanel) -> None:
        panel.setParent(self)
        self._panel = panel
        self._hint = hint_pill(self)
        self._place_panel()
        panel.show()
        self._hint.show()

    def _to_desktop(self, event: QMouseEvent) -> QPoint:
        return self.monitor.geometry.topLeft() + event.position().toPoint()

    def _place_panel(self) -> None:
        if self._panel is None:
            return
        self._panel.adjustSize()
        self._panel.move(
            (self.width() - self._panel.width()) // 2,
            self.height() - self._panel.height() - PANEL_MARGIN,
        )
        if self._hint is not None:
            self._hint.move((self.width() - self._hint.width()) // 2, HINT_MARGIN)

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_panel()

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit(self._to_desktop(event))

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        point = self._to_desktop(event)
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.dragged.emit(point)
        else:
            self.hovered.emit(point)

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.released.emit(self._to_desktop(event))

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.rect(), self._image)
        if self._mode is CaptureMode.SCREEN:
            self._paint_screen_mode(painter)
        else:
            self._paint_selection(painter)

    def _paint_screen_mode(self, painter: QPainter) -> None:
        if not self._highlighted:
            painter.fillRect(self.rect(), DIM)
        else:
            painter.setPen(QPen(ACCENT, 6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect())
        painter.translate(-QPointF(self.monitor.geometry.topLeft()))
        chrome.paint(painter, self._chrome, self.devicePixelRatioF())

    def _paint_selection(self, painter: QPainter) -> None:
        dim = QPainterPath()
        dim.addRect(QRectF(self.rect()))
        if self._selection is None:
            painter.fillPath(dim, DIM)
            return

        local = self._selection.translated(-self.monitor.geometry.topLeft())
        # The default fill rule is odd-even, so the selection is left undimmed.
        dim.addRect(QRectF(local))
        painter.fillPath(dim, DIM)

        self._paint_words(painter)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(ACCENT, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(local).adjusted(0.75, 0.75, -0.75, -0.75))

        painter.setBrush(Qt.GlobalColor.white)
        painter.setPen(QPen(ACCENT, 2))
        box = QRectF(local)
        for handle in (
            box.topLeft(),
            QPointF(box.center().x(), box.top()),
            box.topRight(),
            QPointF(box.left(), box.center().y()),
            QPointF(box.right(), box.center().y()),
            box.bottomLeft(),
            QPointF(box.center().x(), box.bottom()),
            box.bottomRight(),
        ):
            painter.drawEllipse(handle, 4.5, 4.5)

        painter.translate(-QPointF(self.monitor.geometry.topLeft()))
        chrome.paint(painter, self._chrome, self.devicePixelRatioF())

    def _paint_words(self, painter: QPainter) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(-QPointF(self.monitor.geometry.topLeft()))
        for number, shape in enumerate(self._words):
            if number in self._chosen:
                painter.setPen(QPen(ACCENT, 1))
                painter.setBrush(WORD_FILL)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(WORD_TINT)
            painter.drawPolygon(shape)
        painter.restore()
