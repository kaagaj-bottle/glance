import os
import tempfile
import unittest
from pathlib import Path
from typing import cast

import numpy as np
import numpy.typing as npt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402

from glance.library.indexer import embed_pending, index_pending  # noqa: E402
from glance.library.store import DONE, FAILED, Library, Pending  # noqa: E402
from glance.ocr.types import OcrLine, OcrResult  # noqa: E402


class FakeEngine:
    """Reads a fixed text, or raises, and remembers what it was asked to read."""

    def __init__(self, text: str = "hello world", error: Exception | None = None):
        self.text = text
        self.error = error
        self.sizes: list[tuple[int, int]] = []

    def recognize(self, image: QImage) -> OcrResult:
        self.sizes.append((image.width(), image.height()))
        if self.error is not None:
            raise self.error
        return OcrResult((OcrLine(self.text, (), 1.0),))


class IndexPendingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(
            QGuiApplication, QGuiApplication.instance() or QGuiApplication([])
        )

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.library = Library(self.root / "library.db")
        self.addCleanup(self.library.close)

    def _png(self, name: str) -> Path:
        image = QImage(6, 4, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        path = self.root / name
        self.assertTrue(image.save(str(path)))
        self.library.add(path, 1.0, 6, 4)
        return path

    def test_the_text_of_a_capture_becomes_searchable(self) -> None:
        path = self._png("a.png")
        engine = FakeEngine("Invoice 4021")

        result = index_pending(self.library, engine)

        self.assertEqual((result.read, result.failed), (1, 0))
        self.assertEqual(engine.sizes, [(6, 4)])
        self.assertEqual(
            [hit.path for hit in self.library.search("invoice")], [path.resolve()]
        )

    def test_a_missing_file_is_marked_failed_and_the_rest_are_read(self) -> None:
        gone = self._png("gone.png")
        self._png("kept.png")
        gone.unlink()

        result = index_pending(self.library, FakeEngine())

        self.assertEqual((result.read, result.failed), (1, 1))
        self.assertEqual(self.library.counts()[FAILED], 1)
        self.assertEqual(self.library.counts()[DONE], 1)

    def test_a_file_that_is_not_an_image_is_marked_failed(self) -> None:
        path = self.root / "text.png"
        path.write_text("not a picture")
        self.library.add(path, 1.0, 1, 1)
        engine = FakeEngine()

        result = index_pending(self.library, engine)

        self.assertEqual(result.failed, 1)
        self.assertEqual(engine.sizes, [])

    def test_an_engine_error_is_marked_failed_with_its_message(self) -> None:
        self._png("a.png")

        result = index_pending(self.library, FakeEngine(error=RuntimeError("boom")))

        self.assertEqual(result.failed, 1)
        self.assertEqual(self.library.counts()[FAILED], 1)

    def test_a_failed_capture_is_not_read_again(self) -> None:
        self._png("a.png")
        index_pending(self.library, FakeEngine(error=RuntimeError("boom")))
        engine = FakeEngine()

        index_pending(self.library, engine)

        self.assertEqual(engine.sizes, [])

    def test_progress_reports_each_capture_and_why_it_failed(self) -> None:
        self._png("ok.png")
        gone = self._png("gone.png")
        gone.unlink()
        seen: list[tuple[str, str | None]] = []

        def progress(item: Pending, error: str | None) -> None:
            seen.append((item.path.name, error))

        index_pending(self.library, FakeEngine(), progress)

        self.assertEqual(
            sorted(seen), [("gone.png", "the file is missing"), ("ok.png", None)]
        )

    def test_a_picture_with_no_text_is_done(self) -> None:
        self._png("blank.png")

        result = index_pending(self.library, FakeEngine(""))

        self.assertEqual((result.read, result.failed), (1, 0))
        self.assertEqual(self.library.pending(), [])


if __name__ == "__main__":
    unittest.main()


class FakeEmbedder:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.embedded = 0

    def embed_image(self, image: QImage) -> npt.NDArray[np.float32]:
        if self.error is not None:
            raise self.error
        self.embedded += 1
        return np.array([1, 0], dtype=np.float32)

    def embed_text(self, text: str) -> npt.NDArray[np.float32]:
        return np.array([1, 0], dtype=np.float32)


class EmbedPendingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(
            QGuiApplication, QGuiApplication.instance() or QGuiApplication([])
        )

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.library = Library(self.root / "library.db")
        self.addCleanup(self.library.close)

    def _png(self, name: str) -> Path:
        image = QImage(6, 4, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        path = self.root / name
        self.assertTrue(image.save(str(path)))
        self.library.add(path, 1.0, 6, 4)
        return path

    def test_every_capture_becomes_searchable_by_meaning(self) -> None:
        self._png("a.png")
        self._png("b.png")
        embedder = FakeEmbedder()

        result = embed_pending(self.library, embedder)

        self.assertEqual((result.read, result.failed), (2, 0))
        self.assertEqual(self.library.embedded(), 2)

    def test_a_second_run_does_no_work(self) -> None:
        self._png("a.png")
        embedder = FakeEmbedder()
        embed_pending(self.library, embedder)

        embed_pending(self.library, embedder)

        self.assertEqual(embedder.embedded, 1)

    def test_a_missing_file_is_reported_and_the_rest_continue(self) -> None:
        self.library.add(self.root / "gone.png", 0.5, 6, 4)
        self._png("b.png")
        reasons: list[str | None] = []

        result = embed_pending(
            self.library, FakeEmbedder(), lambda item, error: reasons.append(error)
        )

        self.assertEqual((result.read, result.failed), (1, 1))
        self.assertIsNotNone(reasons[0])
        self.assertIsNone(reasons[1])

    def test_a_model_error_is_reported_with_its_reason(self) -> None:
        self._png("a.png")
        reasons: list[str | None] = []

        result = embed_pending(
            self.library,
            FakeEmbedder(RuntimeError("bad model")),
            lambda item, error: reasons.append(error),
        )

        self.assertEqual(result.failed, 1)
        self.assertEqual(reasons, ["bad model"])
