import logging
from typing import Any

import numpy as np
from PySide6.QtGui import QImage

from glance.ocr.types import OcrLine, OcrResult


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

            self._engine = RapidOCR()
            # RapidOCR logs every model it loads, and sets its levels on init.
            for name in logging.root.manager.loggerDict:
                if "rapidocr" in name.lower():
                    logging.getLogger(name).setLevel(logging.ERROR)
        output: Any = self._engine(image_to_array(image))
        if output.txts is None:
            return OcrResult(())
        lines = tuple(
            OcrLine(
                text=str(text),
                box=tuple((float(x), float(y)) for x, y in box),
                confidence=float(score),
            )
            for text, box, score in zip(
                output.txts, output.boxes, output.scores, strict=True
            )
        )
        return OcrResult(lines)
