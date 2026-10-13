import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEventLoop, QRect, QTimer  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance.capture.types import Monitor, Screenshot  # noqa: E402
from glance.ocr.screen import ScreenOcr, selection_result  # noqa: E402
from glance.ocr.types import Box, OcrLine, OcrResult, OcrWord  # noqa: E402


def _box(left: float, top: float, right: float, bottom: float) -> Box:
    return ((left, top), (right, top), (right, bottom), (left, bottom))


def _line(text: str, left: float, top: float = 0, step: float = 60) -> OcrLine:
    """A line of words laid out left to right, each `step` wide, 20 tall."""
    words: list[OcrWord] = []
    position = 0
    for word in text.split():
        start = text.index(word, position)
        position = start + len(word)
        x = left + (len(words)) * step
        words.append(OcrWord(start, position, _box(x, top, x + step - 10, top + 20)))
    return OcrLine(
        text, _box(left, top, left + step * len(words), top + 20), 0.9, tuple(words)
    )


def _screenshot(*sizes: tuple[int, int, int, int], scale: float = 1.0) -> Screenshot:
    monitors = tuple(Monitor(i, f"M{i}", QRect(*rect)) for i, rect in enumerate(sizes))
    images = tuple(
        QImage(
            int(m.geometry.width() * scale),
            int(m.geometry.height() * scale),
            QImage.Format.Format_RGB32,
        )
        for m in monitors
    )
    return Screenshot(monitors, images)


class SelectionResultTest(unittest.TestCase):
    def test_only_words_with_their_center_inside_are_kept(self) -> None:
        shot = _screenshot((0, 0, 400, 100))
        result = OcrResult((_line("one two three four", 0),))
        # Words span x 0-50, 60-110, 120-170, 180-230; centers 25, 85, 145, 205.
        picked = selection_result(shot, [result], QRect(80, 0, 100, 100))
        self.assertEqual([line.text for line in picked.lines], ["two three"])

    def test_boxes_are_moved_to_the_crop(self) -> None:
        shot = _screenshot((0, 0, 400, 100))
        result = OcrResult((_line("one two", 0, top=10),))
        picked = selection_result(shot, [result], QRect(50, 5, 100, 50))
        word = picked.lines[0].words[0]
        self.assertEqual(word.box[0], (10.0, 5.0))
        self.assertEqual((word.start, word.end), (0, 3))

    def test_a_word_just_outside_is_dropped_even_if_it_overlaps(self) -> None:
        shot = _screenshot((0, 0, 400, 100))
        result = OcrResult((_line("one two", 0),))
        # "two" spans 60-110 with center 85; the selection ends at 80.
        picked = selection_result(shot, [result], QRect(0, 0, 80, 100))
        self.assertEqual([line.text for line in picked.lines], ["one"])

    def test_scale_is_applied_for_hidpi_monitors(self) -> None:
        shot = _screenshot((0, 0, 200, 100), scale=2.0)
        # Pixels are doubled: the word's pixel box 100-200 is logical 50-100.
        word = OcrWord(0, 3, _box(100, 20, 200, 60))
        result = OcrResult((OcrLine("one", word.box, 0.9, (word,)),))
        picked = selection_result(shot, [result], QRect(40, 0, 100, 100))
        # In the crop (scale 2) the word starts 10 logical = 20 px in.
        self.assertEqual(picked.lines[0].words[0].box[0], (20.0, 20.0))

    def test_selection_across_monitors_uses_each_monitors_result(self) -> None:
        shot = _screenshot((0, 0, 100, 100), (100, 0, 100, 100))
        left = OcrResult((_line("left", 50, step=40),))
        right = OcrResult((_line("right", 0, step=40),))
        picked = selection_result(shot, [left, right], QRect(0, 0, 200, 100))
        self.assertEqual([line.text for line in picked.lines], ["left", "right"])
        self.assertEqual(picked.lines[1].words[0].box[0], (100.0, 0.0))

    def test_line_without_words_is_kept_whole_when_its_center_is_inside(self) -> None:
        shot = _screenshot((0, 0, 400, 100))
        result = OcrResult((OcrLine("whole", _box(10, 0, 50, 20), 0.9),))
        inside = selection_result(shot, [result], QRect(0, 0, 100, 100))
        outside = selection_result(shot, [result], QRect(200, 0, 100, 100))
        self.assertEqual([line.text for line in inside.lines], ["whole"])
        self.assertEqual(outside.lines, ())

    def test_selection_off_every_monitor_is_empty(self) -> None:
        shot = _screenshot((0, 0, 100, 100))
        picked = selection_result(shot, [OcrResult(())], QRect(500, 500, 10, 10))
        self.assertEqual(picked.lines, ())


class _Engine:
    def __init__(self) -> None:
        self.widths: list[int] = []

    def recognize(self, image: QImage) -> OcrResult:
        self.widths.append(image.width())
        return OcrResult(())


class ScreenOcrTest(unittest.TestCase):
    def _run(self, ocr: ScreenOcr) -> None:
        if QCoreApplication.instance() is None:
            QApplication([])
        loop = QEventLoop()
        ocr.done.connect(loop.quit)
        ocr.failed.connect(loop.quit)
        QTimer.singleShot(5000, loop.quit)
        ocr.start()
        loop.exec()

    def test_reads_every_image_in_order(self) -> None:
        engine = _Engine()
        images = [QImage(w, 10, QImage.Format.Format_RGB32) for w in (30, 20)]
        ocr = ScreenOcr(engine, images)
        self.assertIsNone(ocr.results)
        self._run(ocr)
        self.assertEqual(engine.widths, [30, 20])
        self.assertIsNotNone(ocr.results)
        self.assertEqual(len(ocr.results or ()), 2)

    def test_a_failure_leaves_no_results(self) -> None:
        class Broken:
            def recognize(self, image: QImage) -> OcrResult:
                raise RuntimeError("boom")

        ocr = ScreenOcr(Broken(), [QImage(5, 5, QImage.Format.Format_RGB32)])
        self._run(ocr)
        self.assertIsNone(ocr.results)


if __name__ == "__main__":
    unittest.main()
