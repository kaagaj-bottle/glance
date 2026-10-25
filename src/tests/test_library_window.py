import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import numpy.typing as npt  # noqa: E402
from PySide6.QtCore import (  # noqa: E402
    QCoreApplication,
    QEventLoop,
    QThreadPool,
    QTimer,
)
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance.library.clip import Model  # noqa: E402
from glance.library.store import Library  # noqa: E402
from glance.ocr.types import OcrLine, OcrResult  # noqa: E402
from glance.ui.library import LibraryWindow  # noqa: E402


class FakeEngine:
    def recognize(self, image: QImage) -> OcrResult:
        return OcrResult((OcrLine("invoice total", (), 1.0),))


class FakeEmbedder:
    def embed_image(self, image: QImage) -> npt.NDArray[np.float32]:
        return np.array([1, 0], dtype=np.float32)

    def embed_text(self, text: str) -> npt.NDArray[np.float32]:
        return np.array([1, 0], dtype=np.float32)


def settle(window: LibraryWindow, until: str) -> None:
    """Run the event loop until the status says `until`, or time runs out."""
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(20)
    status = window._status  # pyright: ignore[reportPrivateUsage]

    def check() -> None:
        if until in status.text():
            loop.quit()

    timer.timeout.connect(check)
    timer.start()
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    timer.stop()


class LibraryWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QApplication([])

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.database = self.root / "library.db"
        image = QImage(40, 20, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        self.shot = self.root / "shot.png"
        self.assertTrue(image.save(str(self.shot)))
        with Library(self.database) as library:
            library.add(self.shot, 1.0, 40, 20)
        self.fetched: list[str] = []

    def _fetch(self, url: str, to: Path) -> None:
        self.fetched.append(url)
        to.write_bytes(b"x")

    def _window(self, ready: bool) -> LibraryWindow:
        model = Model(self.root / "clip", self._fetch, lambda folder: FakeEmbedder())
        if ready:
            model.download()
            self.fetched.clear()
        window = LibraryWindow(self.database, model, FakeEngine)
        # Cleanups run last to first: jobs end before the folder is removed.
        self.addCleanup(window.deleteLater)
        self.addCleanup(QThreadPool.globalInstance().waitForDone)
        return window

    def _results(self, window: LibraryWindow) -> list[str]:
        view = window._results  # pyright: ignore[reportPrivateUsage]
        return [view.item(i).toolTip() for i in range(view.count())]

    def test_new_screenshots_are_read_when_it_opens_and_found_by_their_words(
        self,
    ) -> None:
        window = self._window(ready=True)
        settle(window, "that can be found by what they show")

        window._query.setText("invoice")  # pyright: ignore[reportPrivateUsage]
        window.search()
        settle(window, "1 screenshot")

        self.assertEqual(self._results(window), [str(self.shot.resolve())])
        with Library(self.database) as library:
            self.assertEqual(library.embedded(), 1)

    def test_a_description_finds_a_picture_that_never_says_it(self) -> None:
        window = self._window(ready=True)
        settle(window, "that can be found by what they show")

        window._query.setText("a white page")  # pyright: ignore[reportPrivateUsage]
        window.search()
        settle(window, "look like them")

        self.assertEqual(self._results(window), [str(self.shot.resolve())])

    def test_nothing_is_downloaded_until_the_button_is_clicked(self) -> None:
        window = self._window(ready=False)
        settle(window, "in the library")

        self.assertEqual(self.fetched, [])
        row = window._download_row  # pyright: ignore[reportPrivateUsage]
        self.assertFalse(row.isHidden())

        window._download_button.click()  # pyright: ignore[reportPrivateUsage]
        settle(window, "1 that can be found")

        self.assertEqual(len(self.fetched), 3)
        self.assertTrue(row.isHidden())

    def test_a_failed_download_can_be_tried_again(self) -> None:
        window = self._window(ready=False)
        settle(window, "in the library")
        button = window._download_button  # pyright: ignore[reportPrivateUsage]
        with patch.object(Model, "download", MagicMock(side_effect=OSError("offline"))):
            button.click()
            settle(window, "Could not download")

        self.assertIn("offline", window._status.text())  # pyright: ignore[reportPrivateUsage]
        self.assertTrue(button.isEnabled())

    def test_a_blank_search_asks_for_words(self) -> None:
        window = self._window(ready=True)

        window.search()

        self.assertIn("Type some words", window._status.text())  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(self._results(window), [])
