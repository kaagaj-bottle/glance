import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (  # noqa: E402
    QCoreApplication,
    QEventLoop,
    QObject,
    QThreadPool,
    QTimer,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance import background  # noqa: E402
from glance.background import BackgroundTask  # noqa: E402


class BackgroundTaskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QApplication([])

    def _wait(self, task: BackgroundTask) -> None:
        loop = QEventLoop()
        task.done.connect(loop.quit)
        task.failed.connect(loop.quit)
        QTimer.singleShot(3000, loop.quit)
        task.start()
        loop.exec()

    def test_done_is_emitted_when_the_work_returns(self) -> None:
        done = MagicMock()
        task = BackgroundTask(lambda: None)
        task.done.connect(done)

        self._wait(task)

        done.assert_called_once()

    def test_failed_carries_the_reason(self) -> None:
        reasons: list[str] = []

        def work() -> None:
            raise ValueError("nope")

        task = BackgroundTask(work)
        task.failed.connect(reasons.append)

        self._wait(task)

        self.assertEqual(reasons, ["nope"])

    def test_an_answer_for_a_deleted_task_is_dropped_quietly(self) -> None:
        owner = QObject()
        signals = background._Signals(owner)  # pyright: ignore[reportPrivateUsage]
        job = background._Job(  # pyright: ignore[reportPrivateUsage]
            lambda: None, signals
        )
        del owner  # the signals go with it, as when a window closes

        job.run()  # must not raise

        QThreadPool.globalInstance().waitForDone()
