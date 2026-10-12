"""Picking recognized words with the pointer, like selecting text on a page.

Everything here works on image coordinates and needs no widgets, so it can be
tested without a display. Words are numbered in reading order across all lines,
and a selection is a first and last number, both included.
"""

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF

from glance.ocr.types import Box, OcrResult


def _bounds(box: Box) -> QRectF:
    xs = [x for x, _ in box]
    ys = [y for _, y in box]
    return QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))


@dataclass(frozen=True, slots=True)
class LaidOutWord:
    line: int
    start: int
    end: int
    box: Box
    bounds: QRectF


class TextLayout:
    """The words of an `OcrResult`, ready to be hit-tested and cut into text."""

    def __init__(self, result: OcrResult) -> None:
        self._lines = [line.text for line in result.lines]
        self.words: list[LaidOutWord] = []
        for index, line in enumerate(result.lines):
            if line.words:
                parts = [(w.start, w.end, w.box) for w in line.words]
            else:
                parts = [(0, len(line.text), line.box)]
            for start, end, box in parts:
                self.words.append(LaidOutWord(index, start, end, box, _bounds(box)))

    def word_at(self, point: QPointF) -> int | None:
        """The word under the point, or None if it is not on a word."""
        for number, word in enumerate(self.words):
            if word.bounds.contains(point):
                return number
        return None

    def nearest_word(self, point: QPointF) -> int | None:
        """The word under the point, else the closest one.

        The closest line by height is chosen first and then the closest word in
        it by width, so a drag that strays between lines still extends the
        selection in the direction of the pointer.
        """
        if not self.words:
            return None
        line = min(
            {word.line for word in self.words},
            key=lambda index: self._line_distance(index, point.y()),
        )
        return min(
            (n for n, word in enumerate(self.words) if word.line == line),
            key=lambda n: _gap(
                self.words[n].bounds.left(), self.words[n].bounds.right(), point.x()
            ),
        )

    def _line_distance(self, line: int, y: float) -> float:
        tops = [w.bounds.top() for w in self.words if w.line == line]
        bottoms = [w.bounds.bottom() for w in self.words if w.line == line]
        return _gap(min(tops), max(bottoms), y)

    def text(self, first: int, last: int) -> str:
        """The text from word `first` to word `last`, in either order.

        Each line is cut from the line's own text, so spacing and punctuation
        between selected words are kept.
        """
        first, last = sorted((first, last))
        spans: dict[int, tuple[int, int]] = {}
        for word in self.words[first : last + 1]:
            start, end = spans.get(word.line, (word.start, word.end))
            spans[word.line] = (min(start, word.start), max(end, word.end))
        return "\n".join(
            self._lines[line][start:end].strip()
            for line, (start, end) in sorted(spans.items())
        )


def _gap(low: float, high: float, value: float) -> float:
    """How far `value` is from the range, or 0 inside it."""
    if value < low:
        return low - value
    return max(0.0, value - high)
