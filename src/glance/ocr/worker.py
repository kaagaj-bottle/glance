from typing import Protocol

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from glance.ocr.types import OcrResult


class OcrEngine(Protocol):
    def recognize(self, image: QImage) -> OcrResult: ...


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, engine: OcrEngine, image: QImage, signals: _Signals) -> None:
        super().__init__()
        self._engine = engine
        self._image = image
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._engine.recognize(self._image)
        except Exception as error:  # the model can fail in many ways
            self._signals.failed.emit(str(error) or type(error).__name__)
        else:
            self._signals.done.emit(result)


class OcrTask(QObject):
    """Runs OCR off the UI thread. Emits `done` with an `OcrResult` or `failed`."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(
        self, engine: OcrEngine, image: QImage, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._image = image
        # Held so the signals outlive the worker thread's call to run().
        self._signals = _Signals(self)
        self._signals.done.connect(self.done)
        self._signals.failed.connect(self.failed)

    def start(self) -> None:
        QThreadPool.globalInstance().start(
            _Job(self._engine, self._image, self._signals)
        )
