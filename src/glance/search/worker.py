from PySide6.QtCore import QBuffer, QIODevice, QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from glance.search.engines import Engine


def png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    # The stubs ask for bytes, but PySide only accepts the format as a str.
    image.save(buffer, "PNG")  # pyright: ignore[reportCallIssue, reportArgumentType]
    return bytes(buffer.data().data())


class _Signals(QObject):
    done = Signal(str)
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, engine: Engine, png: bytes, signals: _Signals) -> None:
        super().__init__()
        self._engine = engine
        self._png = png
        self._signals = signals

    def run(self) -> None:
        try:
            url = self._engine.results(self._png)
        except Exception as error:  # a network call can fail in many ways
            self._signals.failed.emit(str(error) or type(error).__name__)
        else:
            self._signals.done.emit(url)


class SearchTask(QObject):
    """Uploads an image off the UI thread. Emits `done` with the results address."""

    done = Signal(str)
    failed = Signal(str)

    def __init__(
        self, engine: Engine, image: QImage, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._png = png_bytes(image)
        # Held so the signals outlive the worker thread's call to run().
        self._signals = _Signals(self)
        self._signals.done.connect(self.done)
        self._signals.failed.connect(self.failed)

    def start(self) -> None:
        QThreadPool.globalInstance().start(_Job(self._engine, self._png, self._signals))
