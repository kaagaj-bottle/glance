import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance.ui.chrome import Action, action_at, blocks, code_pill, layout  # noqa: E402

DESKTOP = QRect(0, 0, 800, 600)
SELECTION = QRect(100, 100, 300, 200)


class ChromeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_nothing_is_shown_without_a_selection(self) -> None:
        chrome = layout(None, "1 × 1", 0, None, 0, DESKTOP)

        self.assertIsNone(chrome.size)
        self.assertIsNone(chrome.words)
        self.assertIsNone(chrome.bubble)

    def test_the_word_count_sits_beside_the_size_and_needs_words(self) -> None:
        none = layout(SELECTION, "300 × 200", 0, None, 0, DESKTOP)
        some = layout(SELECTION, "300 × 200", 3, None, 0, DESKTOP)

        self.assertIsNone(none.words)
        assert some.size is not None and some.words is not None
        self.assertEqual(some.words.text, "Aa 3 words")
        self.assertGreater(some.words.rect.left(), some.size.rect.right())
        self.assertEqual(some.words.rect.top(), some.size.rect.top())

    def test_the_labels_move_inside_when_there_is_no_room_above(self) -> None:
        chrome = layout(QRect(100, 0, 300, 200), "300 × 200", 1, None, 0, DESKTOP)

        assert chrome.size is not None
        self.assertGreaterEqual(chrome.size.rect.top(), 0)
        self.assertEqual(chrome.words and chrome.words.text, "Aa 1 word")

    def test_the_bubble_appears_above_picked_words_and_offers_both_actions(
        self,
    ) -> None:
        picked = QRect(200, 200, 80, 20)
        chrome = layout(SELECTION, "300 × 200", 5, picked, 2, DESKTOP)

        assert chrome.bubble is not None
        self.assertEqual(chrome.bubble.count, "2 words")
        self.assertLess(chrome.bubble.rect.bottom(), picked.top())
        self.assertEqual(action_at(chrome, chrome.bubble.copy.center()), Action.COPY)
        self.assertEqual(
            action_at(chrome, chrome.bubble.search.center()), Action.SEARCH
        )
        self.assertEqual(
            action_at(chrome, chrome.bubble.translate.center()), Action.TRANSLATE
        )
        self.assertEqual(
            action_at(chrome, chrome.bubble.explain.center()), Action.EXPLAIN
        )

    def test_the_bubble_only_offers_open_when_given_a_label(self) -> None:
        picked = QRect(200, 200, 80, 20)
        plain = layout(SELECTION, "300 × 200", 5, picked, 2, DESKTOP)
        linked = layout(SELECTION, "300 × 200", 5, picked, 2, DESKTOP, "Open link")

        assert plain.bubble is not None and linked.bubble is not None
        assert linked.bubble.open is not None
        self.assertIsNone(plain.bubble.open)
        self.assertGreater(linked.bubble.rect.width(), plain.bubble.rect.width())
        self.assertEqual(action_at(linked, linked.bubble.open.center()), Action.OPEN)
        self.assertEqual(
            action_at(linked, linked.bubble.search.center()), Action.SEARCH
        )

    def test_the_bubble_drops_below_when_above_is_taken(self) -> None:
        # Words on the first line: above them are the size and word-count labels.
        picked = QRect(110, 105, 80, 20)
        chrome = layout(SELECTION, "300 × 200", 5, picked, 1, DESKTOP)

        assert chrome.bubble is not None
        self.assertGreater(chrome.bubble.rect.top(), picked.bottom())

    def test_a_code_pill_follows_the_word_count_and_asks_for_the_codes(self) -> None:
        none = layout(SELECTION, "300 × 200", 3, None, 0, DESKTOP)
        some = layout(SELECTION, "300 × 200", 3, None, 0, DESKTOP, code_text="QR a.io")
        alone = layout(SELECTION, "300 × 200", 0, None, 0, DESKTOP, code_text="QR a.io")

        self.assertIsNone(none.codes)
        assert some.words is not None and some.codes is not None
        self.assertGreater(some.codes.rect.left(), some.words.rect.right())
        assert alone.size is not None and alone.codes is not None
        self.assertGreater(alone.codes.rect.left(), alone.size.rect.right())
        self.assertIs(action_at(some, some.codes.rect.center()), Action.CODES)
        self.assertTrue(blocks(some, some.codes.rect.center()))

    def test_the_code_pill_for_a_screen_sits_in_its_corner(self) -> None:
        area = QRect(400, 0, 400, 300)

        chrome = code_pill("QR a.io", area)

        assert chrome.codes is not None
        self.assertTrue(area.contains(chrome.codes.rect))
        self.assertLess(chrome.codes.rect.left(), area.left() + 40)
        self.assertIsNone(chrome.size)
        self.assertIs(action_at(chrome, chrome.codes.rect.center()), Action.CODES)

    def test_a_click_on_the_word_count_picks_all_words(self) -> None:
        chrome = layout(SELECTION, "300 × 200", 5, None, 0, DESKTOP)

        assert chrome.words is not None
        self.assertEqual(
            action_at(chrome, chrome.words.rect.center()), Action.ALL_WORDS
        )
        self.assertTrue(blocks(chrome, chrome.words.rect.center()))
        self.assertFalse(blocks(chrome, SELECTION.center()))
