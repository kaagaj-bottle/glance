from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(str)
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, work: Callable[[], str], signals: _Signals) -> None:
        super().__init__()
        self._work = work
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._work()
        except Exception as error:  # a network call can fail in many ways
            self._signals.failed.emit(str(error) or type(error).__name__)
        else:
            self._signals.done.emit(result)


class ExplainTask(QObject):
    """Runs `work` off the UI thread. Emits `done` with its text or `failed`."""

    done = Signal(str)
    failed = Signal(str)

    def __init__(self, work: Callable[[], str], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._work = work
        # Held so the signals outlive the worker thread's call to run().
        self._signals = _Signals(self)
        self._signals.done.connect(self.done)
        self._signals.failed.connect(self.failed)

    def start(self) -> None:
        QThreadPool.globalInstance().start(_Job(self._work, self._signals))
