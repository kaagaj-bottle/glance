import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance.capture.types import Monitor, Screenshot  # noqa: E402
from glance.codes import Code, Item, ItemKind  # noqa: E402
from glance.colors import Swatch  # noqa: E402
from glance.ocr.types import Box, OcrLine, OcrResult, OcrWord  # noqa: E402
from glance.payloads import Wifi  # noqa: E402
from glance.smart import Entity  # noqa: E402
from glance.translate.types import Translation  # noqa: E402
from glance.ui.chrome import Chrome  # noqa: E402
from glance.ui.overlay import PICK, OverlayWindow, ScreenshotOverlay  # noqa: E402
from glance.ui.panel import CaptureMode  # noqa: E402
from glance.ui.translation import TranslationCard  # noqa: E402

LEFT = Monitor(0, "A", QRect(0, 0, 400, 300))
RIGHT = Monitor(1, "B", QRect(400, 0, 400, 300))


def _overlay() -> tuple[ScreenshotOverlay, list[QImage], list[bool]]:
    images = tuple(
        QImage(monitor.geometry.size(), QImage.Format.Format_RGB32)
        for monitor in (LEFT, RIGHT)
    )
    overlay = ScreenshotOverlay(Screenshot((LEFT, RIGHT), images))
    captured: list[QImage] = []
    cancelled: list[bool] = []
    overlay.captured.connect(captured.append)
    overlay.cancelled.connect(lambda: cancelled.append(True))
    return overlay, captured, cancelled


def _windows(overlay: ScreenshotOverlay) -> list[OverlayWindow]:
    return overlay._windows  # pyright: ignore[reportPrivateUsage]


def _drag(window: OverlayWindow, start: QPoint, end: QPoint) -> None:
    left = Qt.MouseButton.LeftButton
    QTest.mousePress(window, left, pos=start)
    QTest.mouseMove(window, end)
    QTest.mouseRelease(window, left, pos=end)


def _box(left: float, top: float, right: float, bottom: float) -> Box:
    return ((left, top), (right, top), (right, bottom), (left, bottom))


def _words() -> OcrResult:
    """ "hello world" in crop pixels: hello at x 10-50, world at x 60-100, y 10-30."""
    words = (OcrWord(0, 5, _box(10, 10, 50, 30)), OcrWord(6, 11, _box(60, 10, 100, 30)))
    return OcrResult((OcrLine("hello world", _box(10, 10, 100, 30), 0.9, words),))


def _words_with(text: str) -> OcrResult:
    """`text` as one word per space-separated part, 10 pixels per character."""
    words: list[OcrWord] = []
    start = 0
    for part in text.split(" "):
        words.append(
            OcrWord(
                start,
                start + len(part),
                _box(start * 10, 10, (start + len(part)) * 10, 30),
            )
        )
        start += len(part) + 1
    line = OcrLine(text, _box(0, 10, len(text) * 10, 30), 0.9, tuple(words))
    return OcrResult((line,))


class OverlayTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _settled(
        self,
    ) -> tuple[ScreenshotOverlay, OverlayWindow, list[QRect], list[str]]:
        overlay, _, _ = _overlay()
        left, _ = _windows(overlay)
        asked: list[QRect] = []
        copied: list[str] = []
        overlay.selection_settled.connect(asked.append)
        overlay.text_copied.connect(copied.append)
        # The selection covers x 100-300, y 50-150; the words sit 10 px in.
        _drag(left, QPoint(100, 50), QPoint(300, 150))
        return overlay, left, asked, copied

    def test_a_finished_selection_asks_for_its_text(self) -> None:
        _, _, asked, _ = self._settled()
        self.assertEqual(asked, [QRect(100, 50, 200, 100)])

    def test_nothing_is_asked_while_the_selection_is_being_dragged(self) -> None:
        overlay, _, _ = _overlay()
        left, _ = _windows(overlay)
        asked: list[QRect] = []
        overlay.selection_settled.connect(asked.append)
        QTest.mousePress(left, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        QTest.mouseMove(left, QPoint(100, 100))
        self.assertEqual(asked, [])

    def test_dragging_over_words_picks_them_and_copy_gives_their_text(self) -> None:
        overlay, left, asked, copied = self._settled()
        overlay.set_words(_words(), asked[0])

        # Words are at desktop x 110-150 and 160-200, y 60-80.
        _drag(left, QPoint(115, 70), QPoint(190, 70))
        overlay._copy_text()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(copied, ["hello world"])

    def test_picking_one_word_copies_only_that_word(self) -> None:
        overlay, left, asked, copied = self._settled()
        overlay.set_words(_words(), asked[0])

        _drag(left, QPoint(165, 70), QPoint(190, 70))
        overlay._copy_text()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(copied, ["world"])

    def test_copy_without_a_pick_gives_all_the_text_in_the_selection(self) -> None:
        overlay, _, asked, copied = self._settled()
        overlay.set_words(_words(), asked[0])

        overlay._copy_text()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(copied, ["hello world"])

    def test_dragging_over_words_does_not_move_the_selection(self) -> None:
        overlay, left, asked, _ = self._settled()
        overlay.set_words(_words(), asked[0])

        _drag(left, QPoint(115, 70), QPoint(190, 120))
        overlay._capture()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(overlay._selection, QRect(100, 50, 200, 100))  # pyright: ignore[reportPrivateUsage]

    def test_dragging_off_the_words_still_moves_the_selection(self) -> None:
        overlay, left, asked, _ = self._settled()
        overlay.set_words(_words(), asked[0])

        _drag(left, QPoint(250, 130), QPoint(260, 140))

        self.assertEqual(overlay._selection, QRect(110, 60, 200, 100))  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(len(asked), 2)

    def test_text_for_an_old_selection_is_ignored(self) -> None:
        overlay, left, asked, copied = self._settled()
        _drag(left, QPoint(10, 10), QPoint(60, 60))

        overlay.set_words(_words(), asked[0])
        overlay._copy_text()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(copied, [])


class OverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_dragging_selects_and_capture_crops_that_area(self) -> None:
        overlay, captured, _ = _overlay()
        left, _ = _windows(overlay)

        _drag(left, QPoint(10, 20), QPoint(110, 90))
        overlay._capture()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(len(captured), 1)
        self.assertEqual((captured[0].width(), captured[0].height()), (100, 70))

    def test_a_drag_can_cross_onto_the_next_monitor(self) -> None:
        overlay, captured, _ = _overlay()
        left, _ = _windows(overlay)

        # The pointer stays with the window where the drag began, so it reports
        # coordinates beyond that window's edge.
        _drag(left, QPoint(300, 50), QPoint(500, 150))
        overlay._capture()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual((captured[0].width(), captured[0].height()), (200, 100))

    def test_a_click_without_a_drag_selects_nothing(self) -> None:
        overlay, captured, _ = _overlay()
        left, _ = _windows(overlay)

        _drag(left, QPoint(10, 10), QPoint(11, 11))
        overlay._capture()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(captured, [])

    def test_the_selection_stays_inside_the_desktop(self) -> None:
        overlay, captured, _ = _overlay()
        _, right = _windows(overlay)

        _drag(right, QPoint(300, 200), QPoint(900, 900))
        overlay._capture()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual((captured[0].width(), captured[0].height()), (100, 100))

    def test_screen_mode_captures_the_clicked_monitor(self) -> None:
        overlay, captured, _ = _overlay()
        _, right = _windows(overlay)

        overlay._set_mode(CaptureMode.SCREEN)  # pyright: ignore[reportPrivateUsage]
        QTest.mouseClick(right, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))

        self.assertEqual((captured[0].width(), captured[0].height()), (400, 300))

    def test_cancel_reports_once_and_never_captures(self) -> None:
        overlay, captured, cancelled = _overlay()

        overlay._cancel()  # pyright: ignore[reportPrivateUsage]
        overlay._cancel()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(cancelled, [True])
        self.assertEqual(captured, [])


class OverlayActionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_copy_and_save_each_hand_over_the_selection_once(self) -> None:
        for method, signal in (
            ("_copy_image", "image_copied"),
            ("_save_image", "image_saved"),
        ):
            with self.subTest(method):
                overlay, captured, _ = _overlay()
                left, _ = _windows(overlay)
                got: list[QImage] = []
                getattr(overlay, signal).connect(got.append)

                _drag(left, QPoint(10, 20), QPoint(110, 90))
                getattr(overlay, method)()
                getattr(overlay, method)()

                self.assertEqual(len(got), 1)
                self.assertEqual((got[0].width(), got[0].height()), (100, 70))
                self.assertEqual(captured, [])

    def test_the_image_is_handed_over_before_the_overlay_closes(self) -> None:
        # Wayland only accepts a clipboard change from a focused window.
        overlay, _, _ = _overlay()
        left, _ = _windows(overlay)
        closed_at_emit: list[bool] = []

        def note(_image: QImage) -> None:
            closed_at_emit.append(overlay._finished)  # pyright: ignore[reportPrivateUsage]

        overlay.image_copied.connect(note)

        _drag(left, QPoint(10, 20), QPoint(110, 90))
        overlay._copy_image()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(closed_at_emit, [False])
        self.assertTrue(overlay._finished)  # pyright: ignore[reportPrivateUsage]

    def test_copy_and_save_need_a_selection(self) -> None:
        overlay, _, _ = _overlay()
        got: list[QImage] = []
        overlay.image_copied.connect(got.append)
        overlay.image_saved.connect(got.append)

        overlay._copy_image()  # pyright: ignore[reportPrivateUsage]
        overlay._save_image()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(got, [])


class OverlayBubbleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _ready(self) -> tuple[ScreenshotOverlay, OverlayWindow, list[str], list[str]]:
        overlay, _, _ = _overlay()
        left, _ = _windows(overlay)
        copied: list[str] = []
        searched: list[str] = []
        overlay.text_copied.connect(copied.append)
        overlay.text_searched.connect(searched.append)
        _drag(left, QPoint(100, 50), QPoint(300, 150))
        overlay.set_words(_words(), QRect(100, 50, 200, 100))
        return overlay, left, copied, searched

    def _chrome(self, overlay: ScreenshotOverlay) -> Chrome:
        return overlay._chrome  # pyright: ignore[reportPrivateUsage]

    def test_the_bubble_shows_as_soon_as_words_are_found_and_acts_on_all_of_them(
        self,
    ) -> None:
        overlay, left, copied, _ = self._ready()
        bubble = self._chrome(overlay).bubble
        assert bubble is not None
        self.assertEqual(bubble.count, "2 words")

        QTest.mouseClick(left, Qt.MouseButton.LeftButton, pos=bubble.copy.center())

        self.assertEqual(copied, ["hello world"])

    def test_picking_some_words_narrows_the_bubble_and_offers_all_words_again(
        self,
    ) -> None:
        overlay, left, _, _ = self._ready()

        _drag(left, QPoint(165, 70), QPoint(190, 70))
        chrome = self._chrome(overlay)
        assert chrome.bubble is not None and chrome.words is not None
        self.assertEqual(chrome.bubble.count, "1 word")

        QTest.mouseClick(
            left, Qt.MouseButton.LeftButton, pos=chrome.words.rect.center()
        )

        bubble = self._chrome(overlay).bubble
        assert bubble is not None
        self.assertEqual(bubble.count, "2 words")

    def test_the_search_button_searches_the_picked_words(self) -> None:
        overlay, left, _, searched = self._ready()
        _drag(left, QPoint(165, 70), QPoint(190, 70))
        bubble = self._chrome(overlay).bubble
        assert bubble is not None

        QTest.mouseClick(left, Qt.MouseButton.LeftButton, pos=bubble.search.center())

        self.assertEqual(searched, ["world"])

    def test_pressing_the_bubble_does_not_move_the_selection(self) -> None:
        overlay, left, _, _ = self._ready()
        _drag(left, QPoint(165, 70), QPoint(190, 70))
        bubble = self._chrome(overlay).bubble
        assert bubble is not None

        centre = bubble.rect.center()
        _drag(left, centre, centre + QPoint(30, 30))

        self.assertEqual(overlay._selection, QRect(100, 50, 200, 100))  # pyright: ignore[reportPrivateUsage]


class OverlayOpenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _ready(
        self, text: str
    ) -> tuple[ScreenshotOverlay, OverlayWindow, list[Entity]]:
        overlay, _, _ = _overlay()
        left, _ = _windows(overlay)
        opened: list[Entity] = []
        overlay.entity_opened.connect(opened.append)
        _drag(left, QPoint(100, 50), QPoint(300, 150))
        overlay.set_words(_words_with(text), QRect(100, 50, 200, 100))
        return overlay, left, opened

    def _bubble(self, overlay: ScreenshotOverlay):
        bubble = overlay._chrome.bubble  # pyright: ignore[reportPrivateUsage]
        assert bubble is not None
        return bubble

    def test_plain_text_has_nothing_to_open(self) -> None:
        overlay, _, _ = self._ready("hello world")

        self.assertIsNone(self._bubble(overlay).open)

    def test_a_link_in_the_text_adds_an_open_item_that_opens_it(self) -> None:
        overlay, left, opened = self._ready("go www.example.org")
        bubble = self._bubble(overlay)
        assert bubble.open is not None
        self.assertEqual(bubble.open_label, "Open link")

        QTest.mouseClick(left, Qt.MouseButton.LeftButton, pos=bubble.open.center())

        self.assertEqual([e.url for e in opened], ["https://www.example.org"])

    def test_an_email_is_labelled_as_one(self) -> None:
        overlay, _, _ = self._ready("jane@example.com")

        self.assertEqual(self._bubble(overlay).open_label, "Email")

    def test_several_entities_ask_which_one_to_open(self) -> None:
        overlay, left, opened = self._ready("jane@example.com www.example.org")
        bubble = self._bubble(overlay)
        assert bubble.open is not None
        self.assertEqual(bubble.open_label, "Open…")

        def second(entities: list[Entity]) -> Entity:
            return entities[1]

        with patch.object(overlay, "_choose_entity", side_effect=second):
            QTest.mouseClick(left, Qt.MouseButton.LeftButton, pos=bubble.open.center())

        self.assertEqual([e.url for e in opened], ["https://www.example.org"])

    def test_dismissing_the_choice_keeps_the_overlay_open(self) -> None:
        overlay, left, opened = self._ready("jane@example.com www.example.org")
        bubble = self._bubble(overlay)
        assert bubble.open is not None

        with patch.object(overlay, "_choose_entity", return_value=None):
            QTest.mouseClick(left, Qt.MouseButton.LeftButton, pos=bubble.open.center())

        self.assertEqual(opened, [])
        self.assertFalse(overlay._finished)  # pyright: ignore[reportPrivateUsage]


class OverlayCodesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _ready(self, *codes: Code) -> tuple[ScreenshotOverlay, OverlayWindow]:
        overlay, _, _ = _overlay()
        left, _ = _windows(overlay)
        _drag(left, QPoint(100, 50), QPoint(300, 150))
        overlay.set_codes(list(codes), QRect(100, 50, 200, 100))
        return overlay, left

    def _choose(self, overlay: ScreenshotOverlay, label: str, index: int = 0) -> None:
        """Ask what to do with the codes, answering the item named `label`."""

        def pick(codes: list[Code]) -> Item:
            return next(i for i in codes[index].items if i.label == label)

        with patch.object(overlay, "_choose_code", side_effect=pick):
            overlay._show_codes()  # pyright: ignore[reportPrivateUsage]

    def test_no_pill_without_a_code(self) -> None:
        overlay, _ = self._ready()
        copied: list[str] = []
        overlay.text_copied.connect(copied.append)

        self._choose(overlay, "Copy")

        self.assertIsNone(overlay._chrome.codes)  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(copied, [])

    def test_a_link_code_shows_a_pill_and_can_be_opened(self) -> None:
        overlay, _ = self._ready(Code("QR Code", "https://a.io/x", ()))
        opened: list[Entity] = []
        overlay.entity_opened.connect(opened.append)
        pill = overlay._chrome.codes  # pyright: ignore[reportPrivateUsage]
        assert pill is not None
        self.assertEqual(pill.text, "QR https://a.io/x")

        self._choose(overlay, "Open link")

        self.assertEqual([e.url for e in opened], ["https://a.io/x"])

    def test_clicking_the_pill_asks_what_to_do(self) -> None:
        overlay, left = self._ready(Code("QR Code", "hi", ()))
        pill = overlay._chrome.codes  # pyright: ignore[reportPrivateUsage]
        assert pill is not None
        copied: list[str] = []
        overlay.text_copied.connect(copied.append)

        copy = Item(ItemKind.COPY, "Copy", "hi")
        with patch.object(overlay, "_choose_code", return_value=copy):
            QTest.mouseClick(left, Qt.MouseButton.LeftButton, pos=pill.rect.center())

        self.assertEqual(copied, ["hi"])

    def test_products_can_be_searched_and_several_codes_share_a_pill(self) -> None:
        overlay, _ = self._ready(
            Code("QR Code", "WIFI:T:WPA;S:home;P:x;;", ()),
            Code("EAN-13", "5901234123457", ()),
        )
        searched: list[str] = []
        overlay.text_searched.connect(searched.append)

        self._choose(overlay, "Search", 1)

        self.assertEqual(searched, ["5901234123457"])
        pill = overlay._chrome.codes  # pyright: ignore[reportPrivateUsage]
        assert pill is not None
        self.assertEqual(pill.text, "Scan 2 codes")

    def test_a_wifi_code_can_be_joined_or_have_its_password_copied(self) -> None:
        text = "WIFI:T:WPA;S:Home;P:pw;;"
        overlay, _ = self._ready(Code("QR Code", text, ()))
        copied: list[str] = []
        overlay.text_copied.connect(copied.append)
        pill = overlay._chrome.codes  # pyright: ignore[reportPrivateUsage]
        assert pill is not None
        self.assertEqual(pill.text, "Wi-Fi Home (WPA)")

        self._choose(overlay, "Copy password")
        self.assertEqual(copied, ["pw"])

        overlay, _ = self._ready(Code("QR Code", text, ()))
        joined: list[Wifi] = []
        overlay.wifi_requested.connect(joined.append)
        self._choose(overlay, "Connect to “Home”")
        self.assertEqual([(w.ssid, w.password) for w in joined], [("Home", "pw")])

    def test_a_place_opens_on_a_map(self) -> None:
        overlay, _ = self._ready(Code("QR Code", "geo:27.7,85.3", ()))
        opened: list[Entity] = []
        overlay.entity_opened.connect(opened.append)

        self._choose(overlay, "Open map")

        self.assertTrue(opened[0].url.startswith("https://www.openstreetmap.org/"))

    def test_dismissing_the_menu_keeps_the_overlay_open(self) -> None:
        overlay, _ = self._ready(Code("QR Code", "hi", ()))

        with patch.object(overlay, "_choose_code", return_value=None):
            overlay._show_codes()  # pyright: ignore[reportPrivateUsage]

        self.assertFalse(overlay._finished)  # pyright: ignore[reportPrivateUsage]

    def test_codes_for_an_old_selection_are_ignored_and_cleared_on_a_new_one(
        self,
    ) -> None:
        overlay, left = self._ready()
        overlay.set_codes([Code("QR Code", "hi", ())], QRect(0, 0, 10, 10))
        self.assertIsNone(overlay._chrome.codes)  # pyright: ignore[reportPrivateUsage]

        overlay.set_codes([Code("QR Code", "hi", ())], QRect(100, 50, 200, 100))
        self.assertIsNotNone(overlay._chrome.codes)  # pyright: ignore[reportPrivateUsage]
        _drag(left, QPoint(10, 10), QPoint(60, 60))

        self.assertIsNone(overlay._chrome.codes)  # pyright: ignore[reportPrivateUsage]


class OverlayColorsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _ready(self) -> tuple[ScreenshotOverlay, list[OverlayWindow], list[str]]:
        # The left monitor is captured at twice the resolution of the right one.
        sharp = QImage(800, 600, QImage.Format.Format_RGB32)
        sharp.fill(QColor("#102030"))
        sharp.setPixelColor(200, 100, QColor("#AA0000"))
        soft = QImage(400, 300, QImage.Format.Format_RGB32)
        soft.fill(QColor("#304050"))
        soft.setPixelColor(100, 60, QColor("#00BB00"))
        overlay = ScreenshotOverlay(Screenshot((LEFT, RIGHT), (sharp, soft)))
        copied: list[str] = []
        overlay.text_copied.connect(copied.append)
        return overlay, _windows(overlay), copied

    def test_a_palette_color_is_copied_as_hex(self) -> None:
        overlay, _, copied = self._ready()
        _drag(_windows(overlay)[0], QPoint(10, 10), QPoint(60, 60))

        with patch.object(overlay, "_choose_color", return_value="#112233") as menu:
            overlay._show_colors()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(copied, ["#112233"])
        swatches: list[Swatch] = menu.call_args.args[0]
        self.assertEqual([s.hex for s in swatches], ["#102030"])

    def test_the_palette_of_a_whole_screen_is_offered_in_screen_mode(self) -> None:
        overlay, _, _ = self._ready()
        overlay._set_mode(CaptureMode.SCREEN)  # pyright: ignore[reportPrivateUsage]

        with patch.object(overlay, "_choose_color", return_value=None) as menu:
            overlay._show_colors()  # pyright: ignore[reportPrivateUsage]

        menu.assert_called_once()

    def test_picking_copies_the_pixel_clicked_whatever_the_scale(self) -> None:
        overlay, (left, right), copied = self._ready()
        with patch.object(overlay, "_choose_color", return_value=PICK):
            _drag(left, QPoint(10, 10), QPoint(60, 60))
            overlay._show_colors()  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(copied, [])

        QTest.mouseClick(right, Qt.MouseButton.LeftButton, pos=QPoint(100, 60))

        self.assertEqual(copied, ["#00BB00"])

    def test_picking_on_the_sharper_monitor_uses_its_own_pixels(self) -> None:
        overlay, (left, _), copied = self._ready()
        with patch.object(overlay, "_choose_color", return_value=PICK):
            _drag(left, QPoint(10, 10), QPoint(60, 60))
            overlay._show_colors()  # pyright: ignore[reportPrivateUsage]

        QTest.mouseClick(left, Qt.MouseButton.LeftButton, pos=QPoint(100, 50))

        self.assertEqual(copied, ["#AA0000"])

    def test_escape_leaves_picking_before_it_cancels(self) -> None:
        overlay, (left, _), copied = self._ready()
        with patch.object(overlay, "_choose_color", return_value=PICK):
            _drag(left, QPoint(10, 10), QPoint(60, 60))
            overlay._show_colors()  # pyright: ignore[reportPrivateUsage]
        cancelled: list[bool] = []
        overlay.cancelled.connect(lambda: cancelled.append(True))

        overlay._cancel()  # pyright: ignore[reportPrivateUsage]
        self.assertFalse(overlay._picking)  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(cancelled, [])

        # A click now selects again instead of copying a color.
        QTest.mouseClick(left, Qt.MouseButton.LeftButton, pos=QPoint(100, 50))
        self.assertEqual(copied, [])
        overlay._cancel()  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(cancelled, [True])


class OverlayTranslateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _ready(self) -> tuple[ScreenshotOverlay, OverlayWindow, list[str], list[str]]:
        overlay, _, _ = _overlay()
        left, _ = _windows(overlay)
        asked: list[str] = []
        copied: list[str] = []

        def ask(text: str, target: str) -> None:
            asked.append(f"{text}>{target}")

        overlay.translate_requested.connect(ask)
        overlay.text_copied.connect(copied.append)
        _drag(left, QPoint(100, 50), QPoint(300, 150))
        overlay.set_words(_words(), QRect(100, 50, 200, 100))
        _drag(left, QPoint(115, 70), QPoint(190, 70))
        return overlay, left, asked, copied

    def _card(self, overlay: ScreenshotOverlay) -> TranslationCard:
        card = overlay._card  # pyright: ignore[reportPrivateUsage]
        assert card is not None
        return card

    def test_nothing_is_sent_until_translate_is_clicked(self) -> None:
        overlay, left, asked, _ = self._ready()
        self.assertEqual(asked, [])

        bubble = overlay._chrome.bubble  # pyright: ignore[reportPrivateUsage]
        assert bubble is not None
        QTest.mouseClick(left, Qt.MouseButton.LeftButton, pos=bubble.translate.center())

        self.assertEqual(asked, ["hello world>en"])
        self.assertFalse(overlay._finished)  # pyright: ignore[reportPrivateUsage]

    def test_the_translation_is_shown_and_can_be_copied(self) -> None:
        overlay, _, _, copied = self._ready()
        overlay._translate_text()  # pyright: ignore[reportPrivateUsage]
        card = self._card(overlay)

        overlay.set_translation("hello world", Translation("hola mundo", "en", "en"))

        self.assertEqual(card.translated, "hola mundo")
        card.copy_requested.emit("hola mundo")
        self.assertEqual(copied, ["hola mundo"])

    def test_a_result_for_an_older_request_is_ignored(self) -> None:
        overlay, _, _, _ = self._ready()
        overlay._translate_text()  # pyright: ignore[reportPrivateUsage]

        overlay.set_translation("something else", Translation("x", "en", "en"))

        self.assertEqual(self._card(overlay).translated, "")

    def test_the_card_goes_away_when_the_selection_changes(self) -> None:
        overlay, left, _, _ = self._ready()
        overlay._translate_text()  # pyright: ignore[reportPrivateUsage]
        card = self._card(overlay)

        _drag(left, QPoint(10, 10), QPoint(60, 40))
        overlay.set_translation("hello world", Translation("hola", "en", "en"))

        self.assertTrue(card.isHidden())
        self.assertEqual(card.translated, "")

    def test_a_failure_is_shown_on_the_card(self) -> None:
        overlay, _, _, _ = self._ready()
        overlay._translate_text()  # pyright: ignore[reportPrivateUsage]

        overlay.set_translation_failed("hello world", "en", "Could not reach it")

        self.assertEqual(self._card(overlay)._status.text(), "Could not reach it")  # pyright: ignore[reportPrivateUsage]

    def test_picking_another_language_translates_again_into_it(self) -> None:
        overlay, _, asked, _ = self._ready()
        overlay.set_target("fr")
        overlay._translate_text()  # pyright: ignore[reportPrivateUsage]
        card = self._card(overlay)

        card.language_changed.emit("de")
        overlay.set_translation("hello world", Translation("Hallo Welt", "en", "fr"))
        self.assertEqual(card.translated, "")  # the French answer is now stale
        overlay.set_translation("hello world", Translation("Hallo Welt", "en", "de"))

        self.assertEqual(asked, ["hello world>fr", "hello world>de"])
        self.assertEqual(card.translated, "Hallo Welt")
