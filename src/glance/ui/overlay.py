from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from PySide6.QtCore import (
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    Qt,
    Signal,
    SignalInstance,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QImage,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPolygonF,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWidgets import QLabel, QWidget

from glance.capture.types import Monitor, Screenshot
from glance.ocr.types import OcrResult
from glance.translate.languages import DEFAULT as DEFAULT_LANGUAGE
from glance.translate.types import Translation
from glance.ui import chrome
from glance.ui.chrome import ACCENT, Action, Chrome
from glance.ui.panel import CaptureMode, CapturePanel, hint_pill
from glance.ui.selection import (
    Handle,
    clamp_point,
    hit_test,
    moved,
    rect_from_points,
    resized,
)
from glance.ui.text_selection import TextLayout
from glance.ui.translation import TranslationCard, card_position

HANDLE_TOLERANCE = 10
MIN_SELECTION = 4
PANEL_MARGIN = 32
HINT_MARGIN = 28

DIM = QColor(8, 8, 14, 148)
WORD_TINT = QColor(139, 124, 255, 45)
WORD_FILL = QColor(139, 124, 255, 150)

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

    Emits `captured` with the chosen part of the screenshot to copy and save,
    `image_copied` or `image_saved` to only do one of those, `image_searched` with
    the key of a search engine to look the image up with, `text_copied` or
    `text_searched` with the recognized text the user picked in it, or
    `cancelled`. `translate_requested` also carries picked text, but leaves the
    overlay open: the translation arrives through `set_translation` or
    `set_translation_failed` and is shown on a card beside the selection.

    Once a selection is settled, `selection_settled` asks for its text, which
    arrives through `set_words`. Its words are then outlined and can be selected
    by dragging over them, like text on a page. In every
    case the windows are closed first.
    """

    captured = Signal(QImage)
    image_copied = Signal(QImage)
    image_saved = Signal(QImage)
    image_searched = Signal(QImage, str)
    text_copied = Signal(str)
    text_searched = Signal(str)
    translate_requested = Signal(str, str)
    selection_settled = Signal(QRect)
    cancelled = Signal()

    def __init__(self, screenshot: Screenshot, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._screenshot = screenshot
        self._mode = CaptureMode.SELECTION
        self._selection: QRect | None = None
        self._drag: _Drag | None = None
        self._hovered: Monitor | None = None
        self._finished = False
        self._layout: TextLayout | None = None
        self._shapes: list[QPolygonF] = []
        self._text_scale = 1.0
        self._text_range: tuple[int, int] | None = None
        self._text_anchor: int | None = None
        self._settled: QRect | None = None
        self._chrome = Chrome()
        self._armed: Action | None = None
        self._card: TranslationCard | None = None
        self._card_source = ""
        self._target = DEFAULT_LANGUAGE

        self._windows = [self._make_window(monitor) for monitor in screenshot.monitors]
        self._panel = CapturePanel()
        self._panel.mode_changed.connect(self._set_mode)
        self._panel.capture_requested.connect(self._capture)
        self._panel.copy_image_requested.connect(self._copy_image)
        self._panel.save_requested.connect(self._save_image)
        self._panel.search_requested.connect(self._search_image)
        self._panel_window().attach_panel(self._panel)

        # Only one overlay window has keyboard focus, so the keys are bound to
        # the application rather than to any single window.
        self._shortcut("Escape", self._cancel)
        for key in ("Return", "Enter", "Space"):
            self._shortcut(key, self._capture)
        self._shortcut("C", self._copy_image)
        self._shortcut("S", self._save_image)
        self._shortcut("I", self._panel.show_search_menu)
        self._shortcut("T", self._copy_text)
        self._shortcut("L", self._translate_text)
        self._shortcut("V", self._search_text)
        self._shortcut("Ctrl+A", self._select_all_words)
        self._shortcut("Ctrl+C", self._copy_text)

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
        self._clear_words()
        self._refresh()
        self._settle()

    def _on_press(self, point: QPoint) -> None:
        if self._mode is CaptureMode.SCREEN:
            monitor = self._monitor_at(point)
            if monitor is not None:
                self._finish(self._screenshot.monitor_image(monitor))
            return

        if chrome.blocks(self._chrome, point):
            self._armed = chrome.action_at(self._chrome, point)
            return

        handle = None
        if self._selection is not None:
            handle = hit_test(self._selection, point, HANDLE_TOLERANCE)
        if handle is Handle.MOVE:
            word = self._word_at(point)
            if word is not None:
                self._text_anchor = word
                self._select_words(word, word)
                return
        self._select_words(None)
        if handle is None:
            # A new selection replaces the old one once the pointer moves.
            self._drag = _Drag(None, point, None)
        else:
            self._drag = _Drag(handle, point, self._selection)

    def _on_drag(self, point: QPoint) -> None:
        if self._armed is not None:
            return
        if self._text_anchor is not None and self._layout is not None:
            focus = self._layout.nearest_word(self._to_text(point))
            if focus is not None:
                self._select_words(self._text_anchor, focus)
            return
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
        self._clear_words()
        self._refresh()

    def _on_hover(self, point: QPoint) -> None:
        if self._mode is CaptureMode.SCREEN:
            self._hovered = self._monitor_at(point)
        else:
            handle = None
            if self._selection is not None:
                handle = hit_test(self._selection, point, HANDLE_TOLERANCE)
            shape = Qt.CursorShape.CrossCursor
            if chrome.action_at(self._chrome, point) is not None:
                shape = Qt.CursorShape.PointingHandCursor
            elif handle is not None:
                shape = _CURSORS[handle]
            if (
                shape is not Qt.CursorShape.PointingHandCursor
                and handle is Handle.MOVE
                and self._word_at(point) is not None
            ):
                shape = Qt.CursorShape.IBeamCursor
            for window in self._windows:
                window.setCursor(shape)
        self._refresh()

    def _on_release(self, point: QPoint) -> None:
        if self._armed is not None:
            armed, self._armed = self._armed, None
            if chrome.action_at(self._chrome, point) is armed:
                self._run(armed)
            return
        if self._text_anchor is not None:
            self._text_anchor = None
            self._refresh()
            return
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
        self._settle()

    def _refresh(self) -> None:
        in_selection_mode = self._mode is CaptureMode.SELECTION
        chosen = range(0)
        if self._text_range is not None:
            chosen = range(self._text_range[0], self._text_range[1] + 1)
        self._chrome = self._layout_chrome()
        for window in self._windows:
            window.set_state(
                self._mode,
                self._selection,
                self._chrome,
                self._hovered is not None and self._hovered == window.monitor,
            )
            window.set_words(self._shapes, chosen)
        self._panel.set_capture_enabled(
            not in_selection_mode or self._selection is not None
        )

    def _layout_chrome(self) -> Chrome:
        if self._mode is not CaptureMode.SELECTION or self._selection is None:
            return Chrome()
        size = self._screenshot.pixel_size(self._selection)
        picked = None
        count = 0
        # The bubble waits until the pointer is up, so it doesn't chase the drag.
        # With nothing picked it offers its actions on all the words found.
        if self._shapes and self._text_anchor is None:
            first, last = self._text_range or (0, len(self._shapes) - 1)
            count = last - first + 1
            picked = self._shapes[first].boundingRect()
            for shape in self._shapes[first + 1 : last + 1]:
                picked = picked.united(shape.boundingRect())
        return chrome.layout(
            self._selection,
            f"{size.width()} × {size.height()}",
            len(self._shapes),
            picked.toAlignedRect() if picked is not None else None,
            count,
            self._screenshot.desktop,
        )

    def _run(self, action: Action) -> None:
        match action:
            case Action.ALL_WORDS:
                self._select_all_words()
            case Action.COPY:
                self._copy_text()
            case Action.TRANSLATE:
                self._translate_text()
            case Action.SEARCH:
                self._search_text()

    def _select_all_words(self) -> None:
        if self._layout is not None and self._layout.words:
            self._select_words(0, len(self._layout.words) - 1)

    def _chosen_image(self) -> QImage | None:
        if self._mode is CaptureMode.SCREEN:
            monitor = self._hovered or self._panel_window().monitor
            return self._screenshot.monitor_image(monitor)
        if self._selection is not None:
            return self._screenshot.crop(self._selection)
        return None

    def _capture(self) -> None:
        self._keep(self.captured)

    def _copy_image(self) -> None:
        self._keep(self.image_copied)

    def _save_image(self) -> None:
        self._keep(self.image_saved)

    def _search_image(self, engine: str) -> None:
        self._keep(self.image_searched, engine)

    def _keep(self, signal: SignalInstance, *extra: str) -> None:
        image = self._chosen_image()
        if image is not None and not self._finished:
            # Emit while the overlay still has focus: Wayland only accepts a
            # clipboard change from the focused window.
            signal.emit(image, *extra)
            self._close()

    def set_words(self, result: OcrResult, area: QRect) -> None:
        """Show the text found in `area`, positioned as in `Screenshot.crop(area)`.

        Ignored if the selection has moved on since the text was asked for.
        """
        if area != self._selection or self._mode is not CaptureMode.SELECTION:
            return
        size = self._screenshot.pixel_size(area)
        self._text_scale = max(1, size.width()) / max(1, area.width())
        layout = TextLayout(result)
        self._layout = layout
        self._text_range = None
        self._shapes = [
            QPolygonF(
                [
                    QPointF(
                        area.left() + x / self._text_scale,
                        area.top() + y / self._text_scale,
                    )
                    for x, y in word.box
                ]
            )
            for word in layout.words
        ]
        self._refresh()

    def _settle(self) -> None:
        """Ask for the text of the selection once it has stopped changing."""
        selection = self._selection
        if (
            selection is None
            or self._mode is not CaptureMode.SELECTION
            or selection == self._settled
        ):
            return
        self._settled = selection
        self.selection_settled.emit(selection)

    def _clear_words(self) -> None:
        self._hide_card()
        self._layout = None
        self._shapes = []
        self._text_range = None
        self._text_anchor = None
        self._settled = None

    def _to_text(self, point: QPoint) -> QPointF:
        """A desktop point in the pixels the words are positioned in."""
        selection = self._selection or QRect()
        return QPointF(
            (point.x() - selection.left()) * self._text_scale,
            (point.y() - selection.top()) * self._text_scale,
        )

    def _word_at(self, point: QPoint) -> int | None:
        if self._layout is None or self._selection is None:
            return None
        if not self._selection.contains(point):
            return None
        return self._layout.word_at(self._to_text(point))

    def _select_words(self, first: int | None, last: int | None = None) -> None:
        """Select the words from `first` to `last`, or clear the selection."""
        if first is None or last is None:
            if self._text_range is None:
                return
            self._text_range = None
        else:
            self._text_range = (min(first, last), max(first, last))
        self._refresh()

    def _text(self) -> str:
        """The picked words, or all the words in the selection if none are picked."""
        if self._layout is None or not self._layout.words:
            return ""
        first, last = self._text_range or (0, len(self._layout.words) - 1)
        return self._layout.text(first, last)

    def _copy_text(self) -> None:
        text = self._text()
        if text and not self._finished:
            # Copy while the overlay still has focus: Wayland only accepts a
            # clipboard change from the focused window.
            self.text_copied.emit(text)
            self._close()

    def _translate_text(self) -> None:
        """Ask for a translation. Nothing is sent until the user asks for one."""
        text = self._text()
        if not text or self._finished or self._selection is None:
            return
        if self._card is None:
            self._card = TranslationCard()
            self._card.copy_requested.connect(self._copy_translation)
            self._card.language_changed.connect(self._change_language)
        self._card.set_target(self._target)
        self._card_source = text
        self._request()

    def set_target(self, code: str) -> None:
        """The language to translate into, as a code from `LANGUAGES`."""
        self._target = code

    def _change_language(self, code: str) -> None:
        self._target = code
        if self._card_source:
            self._request()

    def _request(self) -> None:
        if self._card is None:
            return
        self._card.show_pending()
        self._place_card()
        self.translate_requested.emit(self._card_source, self._target)

    def _is_current(self, source: str, target: str) -> bool:
        return (
            self._card is not None
            and source == self._card_source
            and target == self._target
        )

    def set_translation(self, source: str, translation: Translation) -> None:
        """Show the translation of `source`, unless the card has moved on from it."""
        if self._card is not None and self._is_current(source, translation.target):
            self._card.show_translation(translation)
            self._place_card()

    def set_translation_failed(self, source: str, target: str, message: str) -> None:
        if self._card is not None and self._is_current(source, target):
            self._card.show_error(message)
            self._place_card()

    def _place_card(self) -> None:
        if self._card is None or self._selection is None:
            return
        monitor = self._monitor_at(self._selection.center()) or self._windows[0].monitor
        window = next(w for w in self._windows if w.monitor == monitor)
        if self._card.parent() is not window:
            self._card.setParent(window)
        origin = monitor.geometry.topLeft()
        bounds = QRect(QPoint(0, 0), monitor.geometry.size())
        x, y = card_position(self._card, self._selection.translated(-origin), bounds)
        self._card.move(x, y)
        self._card.show()
        self._card.raise_()

    def _hide_card(self) -> None:
        self._card_source = ""
        if self._card is not None:
            self._card.hide()

    def _copy_translation(self, text: str) -> None:
        if text and not self._finished:
            self.text_copied.emit(text)
            self._close()

    def _search_text(self) -> None:
        text = self._text()
        if text and self._close():
            self.text_searched.emit(text)

    def _cancel(self) -> None:
        self._finish(None)

    def _finish(self, image: QImage | None) -> None:
        if not self._close():
            return
        if image is None:
            self.cancelled.emit()
        else:
            self.captured.emit(image)

    def _close(self) -> bool:
        """Close the windows. False if that was already done."""
        if self._finished:
            return False
        self._finished = True
        for window in self._windows:
            window.close()
        return True
