from typing import Protocol

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from glance.translate.types import Translation


class Translator(Protocol):
    def translate(self, text: str, target: str) -> Translation: ...


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(
        self, translator: Translator, text: str, target: str, signals: _Signals
    ) -> None:
        super().__init__()
        self._translator = translator
        self._text = text
        self._target = target
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._translator.translate(self._text, self._target)
        except Exception as error:  # a network call can fail in many ways
            self._signals.failed.emit(str(error) or type(error).__name__)
        else:
            self._signals.done.emit(result)


class TranslateTask(QObject):
    """Translates off the UI thread. Emits `done` with a `Translation` or `failed`."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        translator: Translator,
        text: str,
        target: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._translator = translator
        self._text = text
        self._target = target
        # Held so the signals outlive the worker thread's call to run().
        self._signals = _Signals(self)
        self._signals.done.connect(self.done)
        self._signals.failed.connect(self.failed)

    def start(self) -> None:
        QThreadPool.globalInstance().start(
            _Job(self._translator, self._text, self._target, self._signals)
        )
