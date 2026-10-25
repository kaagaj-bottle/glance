import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402

from glance.library import clip  # noqa: E402


class NormalizeTest(unittest.TestCase):
    def test_a_vector_is_scaled_to_length_one(self) -> None:
        result = clip.normalize(np.array([3.0, 4.0], dtype=np.float32))

        self.assertAlmostEqual(float(np.linalg.norm(result)), 1.0, places=6)

    def test_a_zero_vector_stays_zero(self) -> None:
        result = clip.normalize(np.zeros(3, dtype=np.float32))

        self.assertEqual(result.tolist(), [0.0, 0.0, 0.0])


class PreprocessTest(unittest.TestCase):
    def test_any_size_becomes_a_normalized_square_batch(self) -> None:
        image = QImage(400, 90, QImage.Format.Format_RGB32)
        image.fill(QColor(255, 255, 255))

        result = clip.preprocess(image)

        self.assertEqual(result.shape, (1, 3, 224, 224))
        expected = (1.0 - clip.MEAN) / clip.STD
        self.assertTrue(np.allclose(result[0, :, 100, 100], expected, atol=1e-4))

    def test_the_channels_are_in_red_green_blue_order(self) -> None:
        image = QImage(8, 8, QImage.Format.Format_RGB32)
        image.fill(QColor(255, 0, 0))

        result = clip.preprocess(image)

        self.assertGreater(result[0, 0, 5, 5], result[0, 1, 5, 5])


def write_placeholder(url: str, to: Path) -> None:
    to.write_bytes(b"x")


class DownloadTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name) / "clip"

    def test_nothing_is_downloaded_until_every_file_is_there(self) -> None:
        self.assertFalse(clip.is_downloaded(self.folder))

        clip.download(self.folder, write_placeholder)

        self.assertTrue(clip.is_downloaded(self.folder))
        self.assertEqual(list(self.folder.rglob("*.part")), [])

    def test_a_failed_download_leaves_no_file_that_looks_whole(self) -> None:
        def fetch(url: str, to: Path) -> None:
            to.write_bytes(b"half")
            raise OSError("connection lost")

        with self.assertRaises(OSError):
            clip.download(self.folder, fetch)

        self.assertFalse(clip.is_downloaded(self.folder))
        self.assertFalse((self.folder / clip.FILES[0]).exists())

    def test_files_already_there_are_not_fetched_again(self) -> None:
        clip.download(self.folder, write_placeholder)
        urls: list[str] = []

        def fetch(url: str, to: Path) -> None:
            urls.append(url)

        clip.download(self.folder, fetch)

        self.assertEqual(urls, [])


@unittest.skipUnless(
    clip.is_downloaded(clip.model_dir()), "the CLIP model is not downloaded"
)
class RealModelTest(unittest.TestCase):
    def test_a_description_is_closer_to_its_picture_than_to_another(self) -> None:
        embedder = clip.ClipEmbedder(clip.model_dir())
        red = QImage(64, 64, QImage.Format.Format_RGB32)
        red.fill(QColor(255, 0, 0))
        blue = QImage(64, 64, QImage.Format.Format_RGB32)
        blue.fill(QColor(0, 0, 255))

        text = embedder.embed_text("a plain red square")

        self.assertEqual(text.shape, (512,))
        self.assertGreater(
            float(text @ embedder.embed_image(red)),
            float(text @ embedder.embed_image(blue)),
        )
