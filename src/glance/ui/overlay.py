from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWidgets import QWidget

from glance.capture.types import Monitor, Screenshot
from glance.ui.panel import CaptureMode, CapturePanel
from glance.ui.selection import (
    Handle,
    clamp_point,
    hit_test,
    moved,
    rect_from_points,
    resized,
)

HANDLE_TOLERANCE = 10
MIN_SELECTION = 4
PANEL_MARGIN = 32

DIM = QColor(0, 0, 0, 140)
ACCENT = QColor("#3584e4")

_CURSORS = {
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
        self._label = ""
        self._highlighted = False
        self._panel: CapturePanel | None = None

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
        label: str,
        highlighted: bool,
    ) -> None:
        self._mode = mode
        self._selection = selection
        self._label = label
        self._highlighted = highlighted
        self.update()

    def attach_panel(self, panel: CapturePanel) -> None:
        panel.setParent(self)
        self._panel = panel
        self._place_panel()
        panel.show()

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
            return
        painter.setPen(QPen(ACCENT, 6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect())

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

        painter.setPen(QPen(Qt.GlobalColor.white, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(local.adjusted(0, 0, -1, -1))

        painter.setBrush(Qt.GlobalColor.white)
        painter.setPen(QPen(QColor(0, 0, 0, 160), 1))
        for corner in (
            local.topLeft(),
            local.topLeft() + QPoint(local.width(), 0),
            local.topLeft() + QPoint(0, local.height()),
            local.topLeft() + QPoint(local.width(), local.height()),
        ):
            painter.drawEllipse(QPointF(corner), 5.0, 5.0)

        if self.rect().contains(local.topLeft()):
            self._paint_label(painter, local)

    def _paint_label(self, painter: QPainter, local: QRect) -> None:
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        size = QSize(metrics.horizontalAdvance(self._label) + 16, metrics.height() + 8)
        # Above the selection if there is room, otherwise just inside it.
        y = local.top() - size.height() - 8
        if y < 0:
            y = local.top() + 8
        box = QRect(QPoint(local.left(), y), size)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 200))
        painter.drawRoundedRect(box, 6, 6)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self._label)


@dataclass(slots=True)
class _Drag:
    """A selection gesture in progress. `handle` is None for a new selection."""

    handle: Handle | None
    origin: QPoint
    start: QRect | None


class ScreenshotOverlay(QObject):
    """Shows a screenshot full-screen and lets the user pick what to keep.

    One `OverlayWindow` covers each monitor, because a Wayland client cannot
    place a window or stretch one across outputs. The selection is kept here in
    desktop coordinates so it can cross monitors.

    Emits `captured` with the chosen part of the screenshot, `text_requested`
    with it when the user asked for its text instead, or `cancelled`. In every
    case the windows are closed first.
    """

    captured = Signal(QImage)
    text_requested = Signal(QImage)
    cancelled = Signal()

    def __init__(self, screenshot: Screenshot, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._screenshot = screenshot
        self._mode = CaptureMode.SELECTION
        self._selection: QRect | None = None
        self._drag: _Drag | None = None
        self._hovered: Monitor | None = None
        self._finished = False

        self._windows = [self._make_window(monitor) for monitor in screenshot.monitors]
        self._panel = CapturePanel()
        self._panel.mode_changed.connect(self._set_mode)
        self._panel.capture_requested.connect(self._capture)
        self._panel.text_requested.connect(self._capture_text)
        self._panel.close_requested.connect(self._cancel)
        self._panel_window().attach_panel(self._panel)

        # Only one overlay window has keyboard focus, so the keys are bound to
        # the application rather than to any single window.
        self._shortcut("Escape", self._cancel)
        for key in ("Return", "Enter", "Space"):
            self._shortcut(key, self._capture)
        self._shortcut("T", self._capture_text)

        self._refresh()

    def show(self) -> None:
        for window in self._windows:
            screens = QGuiApplication.screens()
            # QWidget.setScreen is ignored on Wayland; the screen has to be set
            # on the native window, which only exists once winId() creates it.
            handle = window.windowHandle() if window.winId() else None
            if handle is not None and window.monitor.index < len(screens):
                handle.setScreen(screens[window.monitor.index])
            window.showFullScreen()
        self._panel_window().activateWindow()

    def _make_window(self, monitor: Monitor) -> OverlayWindow:
        window = OverlayWindow(monitor, self._screenshot.monitor_image(monitor))
        window.pressed.connect(self._on_press)
        window.dragged.connect(self._on_drag)
        window.hovered.connect(self._on_hover)
        window.released.connect(self._on_release)
        return window

    def _shortcut(self, key: str, slot: Callable[[], None]) -> None:
        shortcut = QShortcut(QKeySequence(key), self)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut.activated.connect(slot)

    def _panel_window(self) -> OverlayWindow:
        """The window on the monitor the pointer is on."""
        screen = QGuiApplication.screenAt(QCursor.pos())
        for window in self._windows:
            if screen is not None and window.monitor.name == screen.name():
                return window
        return self._windows[0]

    def _monitor_at(self, point: QPoint) -> Monitor | None:
        for monitor in self._screenshot.monitors:
            if monitor.geometry.contains(point):
                return monitor
        return None

    def _set_mode(self, mode: CaptureMode) -> None:
        self._mode = mode
        self._drag = None
        self._refresh()

    def _on_press(self, point: QPoint) -> None:
        if self._mode is CaptureMode.SCREEN:
            monitor = self._monitor_at(point)
            if monitor is not None:
                self._finish(self._screenshot.monitor_image(monitor))
            return

        handle = None
        if self._selection is not None:
            handle = hit_test(self._selection, point, HANDLE_TOLERANCE)
        if handle is None:
            # A new selection replaces the old one once the pointer moves.
            self._drag = _Drag(None, point, None)
        else:
            self._drag = _Drag(handle, point, self._selection)

    def _on_drag(self, point: QPoint) -> None:
        drag = self._drag
        if drag is None:
            return
        desktop = self._screenshot.desktop
        if drag.handle is None:
            self._selection = rect_from_points(drag.origin, clamp_point(point, desktop))
        elif drag.start is not None:
            if drag.handle is Handle.MOVE:
                self._selection = moved(drag.start, point - drag.origin, desktop)
            else:
                self._selection = resized(drag.start, drag.handle, point, desktop)
        self._refresh()

    def _on_hover(self, point: QPoint) -> None:
        if self._mode is CaptureMode.SCREEN:
            self._hovered = self._monitor_at(point)
        else:
            handle = None
            if self._selection is not None:
                handle = hit_test(self._selection, point, HANDLE_TOLERANCE)
            shape = Qt.CursorShape.CrossCursor
            if handle is not None:
                shape = _CURSORS[handle]
            for window in self._windows:
                window.setCursor(shape)
        self._refresh()

    def _on_release(self, point: QPoint) -> None:
        drag, self._drag = self._drag, None
        if drag is None:
            return
        if (
            self._selection is not None
            and drag.handle is None
            and (
                self._selection.width() < MIN_SELECTION
                or self._selection.height() < MIN_SELECTION
            )
        ):
            self._selection = None
        self._refresh()

    def _refresh(self) -> None:
        in_selection_mode = self._mode is CaptureMode.SELECTION
        label = ""
        if self._selection is not None:
            size = self._screenshot.pixel_size(self._selection)
            label = f"{size.width()} × {size.height()}"
        for window in self._windows:
            window.set_state(
                self._mode,
                self._selection,
                label,
                self._hovered is not None and self._hovered == window.monitor,
            )
        self._panel.set_capture_enabled(
            not in_selection_mode or self._selection is not None
        )

    def _chosen_image(self) -> QImage | None:
        if self._mode is CaptureMode.SCREEN:
            monitor = self._hovered or self._panel_window().monitor
            return self._screenshot.monitor_image(monitor)
        if self._selection is not None:
            return self._screenshot.crop(self._selection)
        return None

    def _capture(self) -> None:
        image = self._chosen_image()
        if image is not None:
            self._finish(image)

    def _capture_text(self) -> None:
        image = self._chosen_image()
        if image is not None:
            self._finish(image, text=True)

    def _cancel(self) -> None:
        self._finish(None)

    def _finish(self, image: QImage | None, text: bool = False) -> None:
        if self._finished:
            return
        self._finished = True
        for window in self._windows:
            window.close()
        if image is None:
            self.cancelled.emit()
        elif text:
            self.text_requested.emit(image)
        else:
            self.captured.emit(image)
