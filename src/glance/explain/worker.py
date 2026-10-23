from typing import Protocol

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class Explainer(Protocol):
    def explain(self, text: str) -> str: ...


class _Signals(QObject):
    done = Signal(str)
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, explainer: Explainer, text: str, signals: _Signals) -> None:
        super().__init__()
        self._explainer = explainer
        self._text = text
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._explainer.explain(self._text)
        except Exception as error:  # a network call can fail in many ways
            self._signals.failed.emit(str(error) or type(error).__name__)
        else:
            self._signals.done.emit(result)


class ExplainTask(QObject):
    """Explains off the UI thread. Emits `done` with the text or `failed`."""

    done = Signal(str)
    failed = Signal(str)

    def __init__(
        self, explainer: Explainer, text: str, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._explainer = explainer
        self._text = text
        # Held so the signals outlive the worker thread's call to run().
        self._signals = _Signals(self)
        self._signals.done.connect(self.done)
        self._signals.failed.connect(self.failed)

    def start(self) -> None:
        QThreadPool.globalInstance().start(
            _Job(self._explainer, self._text, self._signals)
        )
