import logging
from collections.abc import Sequence
from typing import Any

import numpy as np
from PySide6.QtGui import QImage

from glance.ocr.types import Box, OcrLine, OcrResult, OcrWord

# Detection shrinks images whose long side is larger, which loses small text on
# a full monitor capture.
MAX_SIDE = 4096


def locate_words(text: str, found: Sequence[tuple[str, Box]]) -> tuple[OcrWord, ...]:
    """Place each recognized word in the line's text, in order.

    If the words cannot all be found in the text, the line is treated as a single
    word so that it can still be selected whole.
    """
    words: list[OcrWord] = []
    position = 0
    for word, box in found:
        start = text.find(word, position)
        if start < 0:
            return ()
        position = start + len(word)
        words.append(OcrWord(start, position, box))
    return tuple(words)


def image_to_array(image: QImage) -> "np.ndarray[Any, np.dtype[np.uint8]]":
    """An RGB copy of the image as a height x width x 3 array."""
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    width, height, stride = rgb.width(), rgb.height(), rgb.bytesPerLine()
    rows = np.frombuffer(rgb.constBits(), dtype=np.uint8, count=stride * height)
    return rows.reshape(height, stride)[:, : width * 3].reshape(height, width, 3).copy()


class RapidOcrEngine:
    """Recognizes text with RapidOCR (PaddleOCR models on ONNX Runtime).

    The model is loaded on the first call, since loading takes a moment and
    most runs never use it.
    """

    def __init__(self) -> None:
        self._engine: Any = None

    def recognize(self, image: QImage) -> OcrResult:
        if image.isNull():
            return OcrResult(())
        if self._engine is None:
            # Imported here so the app starts without paying for onnxruntime.
            from rapidocr import RapidOCR

            self._engine = RapidOCR(params={"Global.max_side_len": MAX_SIDE})
            # RapidOCR logs every model it loads, and sets its levels on init.
            for name in logging.root.manager.loggerDict:
                if "rapidocr" in name.lower():
                    logging.getLogger(name).setLevel(logging.ERROR)
        output: Any = self._engine(image_to_array(image), return_word_box=True)
        if output.txts is None:
            return OcrResult(())
        word_results: Sequence[Any] = output.word_results or [None] * len(output.txts)
        lines: list[OcrLine] = []
        for text, box, score, found in zip(
            output.txts, output.boxes, output.scores, word_results, strict=True
        ):
            line_box = _box(box)
            words = locate_words(
                str(text), [(str(w[0]), _box(w[2])) for w in found or ()]
            )
            lines.append(OcrLine(str(text), line_box, float(score), words))
        return OcrResult(tuple(lines))


def _box(points: Any) -> Box:
    return tuple((float(x), float(y)) for x, y in points)
