"""Reading a whole screenshot ahead of time, and cutting a selection out of it.

Recognizing the text once, when Glance starts, makes asking for the text of a
selection instant: the words that lie inside it are picked from the result.
"""

from collections.abc import Sequence

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, Signal
from PySide6.QtGui import QImage

from glance.capture.types import Monitor, Screenshot
from glance.ocr.types import Box, OcrLine, OcrResult, OcrWord
from glance.ocr.worker import OcrEngine, OcrTask


class ScreenOcr(QObject):
    """Recognizes each monitor's image in turn, off the UI thread.

    The images are read one after another because the engine is shared. Emits
    `done` once every monitor has a result, or `failed` at the first error.
    """

    done = Signal()
    failed = Signal(str)

    def __init__(
        self,
        engine: OcrEngine,
        images: Sequence[QImage],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._images = tuple(images)
        self._results: list[OcrResult] = []
        self._task: OcrTask | None = None
        self._failed = False

    @property
    def results(self) -> tuple[OcrResult, ...] | None:
        """One result per image, or None until all of them are read."""
        if self._failed or len(self._results) < len(self._images):
            return None
        return tuple(self._results)

    def start(self) -> None:
        self._next()

    def _next(self) -> None:
        if len(self._results) == len(self._images):
            self.done.emit()
            return
        task = OcrTask(self._engine, self._images[len(self._results)], self)
        task.done.connect(self._on_result)
        task.failed.connect(self._on_failed)
        self._task = task
        task.start()

    def _on_result(self, result: OcrResult) -> None:
        self._results.append(result)
        self._next()

    def _on_failed(self, message: str) -> None:
        self._failed = True
        self.failed.emit(message)


def _bounds(points: Sequence[tuple[float, float]]) -> QRectF:
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))


def _quad(rect: QRectF) -> Box:
    """The corners of a rectangle, clockwise from the top-left."""
    return (
        (rect.left(), rect.top()),
        (rect.right(), rect.top()),
        (rect.right(), rect.bottom()),
        (rect.left(), rect.bottom()),
    )


class _Mapping:
    """Moves boxes from one monitor's pixels into the pixels of a crop."""

    def __init__(self, monitor: Monitor, source: float, selection: QRect, scale: float):
        self._monitor = monitor.geometry.topLeft()
        self._source = source
        self._selection = selection
        self._scale = scale

    def logical(self, box: Box) -> Box:
        return tuple(
            (self._monitor.x() + x / self._source, self._monitor.y() + y / self._source)
            for x, y in box
        )

    def inside(self, box: Box) -> bool:
        center = _bounds(self.logical(box)).center()
        return self._selection.toRectF().contains(center)

    def to_crop(self, box: Box) -> Box:
        return tuple(
            (
                (x - self._selection.left()) * self._scale,
                (y - self._selection.top()) * self._scale,
            )
            for x, y in self.logical(box)
        )


def selection_result(
    screenshot: Screenshot, results: Sequence[OcrResult], selection: QRect
) -> OcrResult:
    """The text inside a logical rectangle, positioned as in `Screenshot.crop`.

    A word belongs to the selection when the center of its box is inside it. A
    line that is only partly inside is cut down to its words that are, so the
    result looks like OCR of the cropped image.
    """
    monitors = [
        (index, monitor)
        for index, monitor in enumerate(screenshot.monitors)
        if not selection.intersected(monitor.geometry).isEmpty()
    ]
    if not monitors:
        return OcrResult(())
    scale = max(screenshot.scale(monitor) for _, monitor in monitors)
    lines: list[OcrLine] = []
    for index, monitor in monitors:
        mapping = _Mapping(monitor, screenshot.scale(monitor), selection, scale)
        for line in results[index].lines:
            if not line.words:
                if mapping.inside(line.box):
                    lines.append(
                        OcrLine(line.text, mapping.to_crop(line.box), line.confidence)
                    )
                continue
            run: list[OcrWord] = []
            for word in (*line.words, None):
                if word is not None and mapping.inside(word.box):
                    run.append(word)
                elif run:
                    lines.append(_run_line(line, run, mapping))
                    run = []
    return OcrResult(tuple(lines))


def _run_line(line: OcrLine, run: list[OcrWord], mapping: _Mapping) -> OcrLine:
    """The part of a line covered by consecutive words, moved into the crop."""
    first, last = run[0].start, run[-1].end
    words = tuple(
        OcrWord(w.start - first, w.end - first, mapping.to_crop(w.box)) for w in run
    )
    box = _quad(_bounds([point for word in words for point in word.box]))
    return OcrLine(line.text[first:last], box, line.confidence, words)
