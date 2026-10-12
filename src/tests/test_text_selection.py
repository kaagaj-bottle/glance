import unittest

from PySide6.QtCore import QPointF

from glance.ocr.types import OcrLine, OcrResult, OcrWord
from glance.ui.text_selection import TextLayout


def _box(left: float, top: float, right: float, bottom: float):
    return ((left, top), (right, top), (right, bottom), (left, bottom))


def _line(text: str, top: float, spans: list[tuple[int, int]]) -> OcrLine:
    # Each character is 10 wide, so a word's box follows its place in the text.
    words = tuple(OcrWord(a, b, _box(a * 10, top, b * 10, top + 20)) for a, b in spans)
    return OcrLine(text, _box(0, top, len(text) * 10, top + 20), 1.0, words)


RESULT = OcrResult(
    (
        _line("Hello, big world", 0, [(0, 6), (7, 10), (11, 16)]),
        _line("second line", 40, [(0, 6), (7, 11)]),
    )
)


class TextLayoutTest(unittest.TestCase):
    def setUp(self) -> None:
        self.layout = TextLayout(RESULT)

    def test_words_are_numbered_in_reading_order(self) -> None:
        self.assertEqual(len(self.layout.words), 5)
        self.assertEqual([w.line for w in self.layout.words], [0, 0, 0, 1, 1])

    def test_word_at_finds_the_word_under_the_point(self) -> None:
        self.assertEqual(self.layout.word_at(QPointF(80, 10)), 1)

    def test_word_at_is_none_off_the_words(self) -> None:
        self.assertIsNone(self.layout.word_at(QPointF(5, 30)))

    def test_nearest_word_snaps_to_the_closest_line_then_word(self) -> None:
        self.assertEqual(self.layout.nearest_word(QPointF(500, 35)), 4)
        self.assertEqual(self.layout.nearest_word(QPointF(-50, 25)), 0)

    def test_text_keeps_punctuation_and_spacing_within_a_line(self) -> None:
        self.assertEqual(self.layout.text(0, 2), "Hello, big world")
        self.assertEqual(self.layout.text(0, 0), "Hello,")

    def test_text_across_lines_is_split_by_newline(self) -> None:
        self.assertEqual(self.layout.text(2, 3), "world\nsecond")

    def test_text_does_not_care_which_end_came_first(self) -> None:
        self.assertEqual(self.layout.text(4, 1), "big world\nsecond line")

    def test_a_line_without_words_is_one_word(self) -> None:
        layout = TextLayout(OcrResult((OcrLine("whole", _box(0, 0, 50, 20), 1.0),)))
        self.assertEqual(layout.text(0, 0), "whole")

    def test_empty_result_has_nothing_to_hit(self) -> None:
        layout = TextLayout(OcrResult(()))
        self.assertIsNone(layout.nearest_word(QPointF(1, 1)))


if __name__ == "__main__":
    unittest.main()
