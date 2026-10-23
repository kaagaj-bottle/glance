from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import (
    QObject,
    QPoint,
    QPointF,
    QRect,
    Qt,
    Signal,
    SignalInstance,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPixmap,
    QPolygonF,
    QShortcut,
)
from PySide6.QtWidgets import QWidget

from glance.capture.types import Monitor, Screenshot
from glance.codes import Code, Item, ItemKind
from glance.colors import Swatch, palette, pixel_hex
from glance.ocr.types import OcrResult
from glance.payloads import Document, Wifi
from glance.smart import Entity, Kind, find_entities
from glance.translate.languages import DEFAULT as DEFAULT_LANGUAGE
from glance.translate.types import Translation
from glance.ui import chrome
from glance.ui.chrome import Action, Chrome
from glance.ui.explanation import ExplanationCard
from glance.ui.panel import (
    HINT,
    PICK_HINT,
    CaptureMode,
    CapturePanel,
    styled_menu,
)
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
from glance.ui.window import CURSORS, OverlayWindow

PICK = "pick"
HANDLE_TOLERANCE = 10
MIN_SELECTION = 4
# What the explanation card is waiting for when it is not a piece of text.
IMAGE_SOURCE = "\0image"
NO_TEXT = "\0no-text"


def _open_label(entities: list[Entity]) -> str:
    """The text of the bubble's open item, or nothing if there is nothing to open."""
    if not entities:
        return ""
    if len(entities) > 1:
        return "Open…"
    return "Email" if entities[0].kind is Kind.EMAIL else "Open link"


def _code_text(codes: list[Code]) -> str:
    """The text of the pill for the codes found: a mark, then what they say."""
    if not codes:
        return ""
    if len(codes) > 1:
        return f"Scan {len(codes)} codes"
    [code] = codes
    return f"{code.mark} {code.label}"


def _mnemonic_safe(text: str) -> str:
    """Text for a menu entry, where a lone `&` would make the next letter a hotkey."""
    return text.replace("&", "&&")


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
    `text_searched` with the recognized text the user picked in it,
    `entity_opened` with a link or email address found in that text or a code,
    `wifi_requested` with the network of a Wi-Fi code to join,
    `document_opened` with a contact or event file to hand to another app,
    `record_requested` with the area and the monitor to record, or
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
    entity_opened = Signal(object)
    wifi_requested = Signal(object)
    document_opened = Signal(object)
    translate_requested = Signal(str, str)
    explain_requested = Signal(str)
    explain_image_requested = Signal(QImage)
    selection_settled = Signal(QRect)
    record_requested = Signal(QRect, object)
    cancelled = Signal()

    def __init__(self, screenshot: Screenshot, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._screenshot = screenshot
        self._mode = CaptureMode.SELECTION
        self._selection: QRect | None = None
        self._drag: _Drag | None = None
        self._hovered: Monitor | None = None
        self._finished = False
        self._shortcuts: list[QShortcut] = []
        self._layout: TextLayout | None = None
        self._shapes: list[QPolygonF] = []
        self._text_scale = 1.0
        self._text_range: tuple[int, int] | None = None
        self._text_anchor: int | None = None
        self._settled: QRect | None = None
        self._codes: list[Code] = []
        self._screen_codes: dict[int, list[Code]] = {}
        self._picking = False
        self._chrome = Chrome()
        self._armed: Action | None = None
        self._card: TranslationCard | None = None
        self._card_source = ""
        self._explain_card: ExplanationCard | None = None
        self._explain_source = ""
        self._target = DEFAULT_LANGUAGE

        self._windows = [self._make_window(monitor) for monitor in screenshot.monitors]
        self._panel = CapturePanel()
        self._panel.mode_changed.connect(self._set_mode)
        self._panel.capture_requested.connect(self._capture)
        self._panel.copy_image_requested.connect(self._copy_image)
        self._panel.save_requested.connect(self._save_image)
        self._panel.search_requested.connect(self._search_image)
        self._panel.explain_image_requested.connect(self._explain_image)
        self._panel.colors_requested.connect(self._show_colors)
        self._panel.record_requested.connect(self._record)
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
        self._shortcut("E", self._explain_text)
        self._shortcut("Shift+E", self._explain_image)
        self._shortcut("V", self._search_text)
        self._shortcut("Q", self._show_codes)
        self._shortcut("K", self._show_colors)
        self._shortcut("R", self._record)
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
        self._shortcuts.append(shortcut)

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
        if self._picking:
            self._pick_color(point)
            return
        if self._mode is CaptureMode.SCREEN:
            if chrome.blocks(self._chrome, point):
                self._armed = chrome.action_at(self._chrome, point)
                return
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
        if self._picking:
            return
        if self._mode is CaptureMode.SCREEN:
            self._hovered = self._monitor_at(point)
            shape = Qt.CursorShape.CrossCursor
            if chrome.action_at(self._chrome, point) is not None:
                shape = Qt.CursorShape.PointingHandCursor
            for window in self._windows:
                window.setCursor(shape)
        else:
            handle = None
            if self._selection is not None:
                handle = hit_test(self._selection, point, HANDLE_TOLERANCE)
            shape = Qt.CursorShape.CrossCursor
            if chrome.action_at(self._chrome, point) is not None:
                shape = Qt.CursorShape.PointingHandCursor
            elif handle is not None:
                shape = CURSORS[handle]
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

    def _screen_monitor(self) -> Monitor:
        """The monitor Screen mode would capture: the hovered one."""
        return self._hovered or self._panel_window().monitor

    def _current_codes(self) -> list[Code]:
        """The codes in what would be kept: the selection, or the whole monitor."""
        if self._mode is CaptureMode.SCREEN:
            return self._screen_codes.get(self._screen_monitor().index, [])
        return self._codes

    def _layout_chrome(self) -> Chrome:
        if self._mode is CaptureMode.SCREEN:
            codes = self._current_codes()
            if not codes:
                return Chrome()
            area = self._screen_monitor().geometry
            return chrome.code_pill(_code_text(codes), area)
        if self._selection is None:
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
        entities = find_entities(self._text()) if picked is not None else []
        return chrome.layout(
            self._selection,
            f"{size.width()} × {size.height()}",
            len(self._shapes),
            picked.toAlignedRect() if picked is not None else None,
            count,
            self._screenshot.desktop,
            _open_label(entities),
            _code_text(self._codes),
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
            case Action.EXPLAIN:
                self._explain_text()
            case Action.OPEN:
                self._open_entity()
            case Action.CODES:
                self._show_codes()

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

    def _record_target(self) -> tuple[QRect, Monitor] | None:
        """What to record: the monitor in Screen mode, else the selection.

        A recording comes from one monitor, so a selection that spans several is
        cut down to the one holding most of it.
        """
        if self._mode is CaptureMode.SCREEN:
            monitor = self._screen_monitor()
            return monitor.geometry, monitor
        if self._selection is None:
            return None
        best: tuple[int, QRect, Monitor] | None = None
        for monitor in self._screenshot.monitors:
            part = self._selection.intersected(monitor.geometry)
            area = part.width() * part.height()
            if area > 0 and (best is None or area > best[0]):
                best = (area, part, monitor)
        return None if best is None else (best[1], best[2])

    def _record(self) -> None:
        target = self._record_target()
        if target is not None and not self._finished:
            self.record_requested.emit(*target)
            self._close()

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

    def set_codes(self, codes: list[Code], area: QRect) -> None:
        """Show the codes found in `area`. Ignored if the selection has moved on."""
        if area != self._selection or self._mode is not CaptureMode.SELECTION:
            return
        self._codes = codes
        self._refresh()

    def set_screen_codes(self, index: int, codes: list[Code]) -> None:
        """The codes found on the monitor with this index, for Screen mode."""
        self._screen_codes[index] = codes
        self._refresh()

    def _show_codes(self) -> None:
        """Ask what to do with the codes found: open, copy, connect or search."""
        codes = self._current_codes()
        if self._finished or not codes:
            return
        item = self._choose_code(codes)
        if item is None or self._finished:
            return
        # A copy is handed over while the overlay still has focus, as for text.
        if item.kind is ItemKind.COPY and isinstance(item.value, str):
            self.text_copied.emit(item.value)
            self._close()
        elif self._close():
            match item.kind, item.value:
                case ItemKind.OPEN, Entity() as entity:
                    self.entity_opened.emit(entity)
                case ItemKind.WIFI, Wifi() as wifi:
                    self.wifi_requested.emit(wifi)
                case ItemKind.IMPORT, Document() as document:
                    self.document_opened.emit(document)
                case ItemKind.SEARCH, str() as text:
                    self.text_searched.emit(text)
                case _:
                    pass

    def _choose_code(self, codes: list[Code]) -> Item | None:
        """A menu of what each code allows."""
        menu = styled_menu(self._panel_window())
        for index, code in enumerate(codes):
            if index:
                menu.addSeparator()
            menu.addAction(_mnemonic_safe(f"{code.kind} · {code.label}")).setEnabled(
                False
            )
            for item in code.items:
                menu.addAction(_mnemonic_safe(item.label)).setData(item)
        chosen = menu.exec(QCursor.pos())
        return chosen.data() if chosen else None

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
        self._codes = []

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
        self._hide_explanation()
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
        self._place_card(self._card, self._card_anchor())
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
            self._place_card(self._card, self._card_anchor())

    def set_translation_failed(self, source: str, target: str, message: str) -> None:
        if self._card is not None and self._is_current(source, target):
            self._card.show_error(message)
            self._place_card(self._card, self._card_anchor())

    def _explain_text(self) -> None:
        """Ask for an explanation. Nothing is sent until the user asks for one."""
        if self._finished or self._selection is None:
            return
        card = self._open_explain_card()
        text = self._text()
        self._explain_source = text or NO_TEXT
        if not text:
            card.show_error("There is no text in the selection to explain")
            self._place_card(card, self._selection)
            return
        card.show_pending("text")
        self._place_card(card, self._selection)
        self.explain_requested.emit(text)

    def _explain_image(self) -> None:
        """Ask for an explanation of the image. Nothing is sent until asked."""
        image = self._chosen_image()
        if image is None or self._finished:
            return
        card = self._open_explain_card()
        self._explain_source = IMAGE_SOURCE
        card.show_pending("image")
        self._place_card(card, self._anchor())
        self.explain_image_requested.emit(image)

    def _open_explain_card(self) -> ExplanationCard:
        if self._explain_card is None:
            self._explain_card = ExplanationCard()
            self._explain_card.copy_requested.connect(self._copy_translation)
        self._hide_card()
        return self._explain_card

    def _anchor(self) -> QRect:
        """Where a card goes: below the selection, or at the top of a whole screen."""
        if self._mode is CaptureMode.SELECTION and self._selection is not None:
            return self._selection
        bounds = (self._hovered or self._panel_window().monitor).geometry
        return QRect(bounds.center().x(), bounds.top() + 24, 1, 1)

    def set_explanation(self, source: str, explanation: str) -> None:
        """Show the explanation of `source` (the text, or `IMAGE_SOURCE`).

        Ignored if the card has moved on from it.
        """
        if self._explain_card is not None and source == self._explain_source:
            self._explain_card.show_explanation(explanation)
            self._place_card(self._explain_card, self._anchor())

    def set_explanation_failed(self, source: str, message: str) -> None:
        if self._explain_card is not None and source == self._explain_source:
            self._explain_card.show_error(message)
            self._place_card(self._explain_card, self._anchor())

    def _hide_explanation(self) -> None:
        self._explain_source = ""
        if self._explain_card is not None:
            self._explain_card.hide()

    def _card_anchor(self) -> QRect:
        return self._selection if self._selection is not None else QRect()

    def _place_card(self, card: QWidget, anchor: QRect) -> None:
        if anchor.isNull():
            return
        monitor = self._monitor_at(anchor.center()) or self._windows[0].monitor
        window = next(w for w in self._windows if w.monitor == monitor)
        if card.parent() is not window:
            card.setParent(window)
        origin = monitor.geometry.topLeft()
        bounds = QRect(QPoint(0, 0), monitor.geometry.size())
        x, y = card_position(card, anchor.translated(-origin), bounds)
        card.move(x, y)
        card.show()
        card.raise_()

    def _hide_card(self) -> None:
        self._hide_explanation()
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

    def _open_entity(self) -> None:
        """Open the link or address in the picked text, asking which if many."""
        entities = find_entities(self._text())
        if self._finished or not entities:
            return
        entity = entities[0] if len(entities) == 1 else self._choose_entity(entities)
        if entity is not None and self._close():
            self.entity_opened.emit(entity)

    def _choose_entity(self, entities: list[Entity]) -> Entity | None:
        menu = styled_menu(self._panel_window())
        for entity in entities:
            menu.addAction(entity.label).setData(entity)
        chosen = menu.exec(QCursor.pos())
        return chosen.data() if chosen else None

    def _show_colors(self) -> None:
        """Offer the main colors of the capture to copy, or to pick one by hand."""
        image = self._chosen_image()
        if self._finished or image is None:
            return
        choice = self._choose_color(palette(image))
        if choice is None or self._finished:
            return
        if choice == PICK:
            self._set_picking(True)
        else:
            self.text_copied.emit(choice)
            self._close()

    def _choose_color(self, swatches: list[Swatch]) -> str | None:
        """A menu of colors: the hex of the one chosen, `PICK`, or None."""
        menu = styled_menu(self._panel_window())
        menu.addAction("Copy a color").setEnabled(False)
        menu.addSeparator()
        for swatch in swatches:
            pixmap = QPixmap(16, 16)
            pixmap.fill(QColor(swatch.hex))
            action = menu.addAction(
                QIcon(pixmap), f"{swatch.hex}  ·  {swatch.share:.0%}"
            )
            action.setData(swatch.hex)
        if swatches:
            menu.addSeparator()
        menu.addAction("Pick from the screen…").setData(PICK)
        chosen = menu.exec(QCursor.pos())
        return chosen.data() if chosen else None

    def _set_picking(self, picking: bool) -> None:
        self._picking = picking
        self._drag = None
        for window in self._windows:
            window.setCursor(Qt.CursorShape.CrossCursor)
        self._panel_window().set_hint(PICK_HINT if picking else HINT)

    def _pick_color(self, point: QPoint) -> None:
        """Copy the color of the pixel under the pointer, on its own monitor."""
        monitor = self._monitor_at(point)
        if monitor is None:
            return
        image = self._screenshot.monitor_image(monitor)
        scale = self._screenshot.scale(monitor)
        offset = point - monitor.geometry.topLeft()
        x = min(max(int(offset.x() * scale), 0), image.width() - 1)
        y = min(max(int(offset.y() * scale), 0), image.height() - 1)
        color = pixel_hex(image, x, y)
        if color is not None:
            self.text_copied.emit(color)
            self._close()

    def _cancel(self) -> None:
        if self._picking:
            self._set_picking(False)
            return
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
        # The overlay outlives its windows, and a later window (the recording bar)
        # may use the same keys.
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
        for window in self._windows:
            window.close()
        return True
