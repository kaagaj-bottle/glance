import tempfile
import unittest
from pathlib import Path

import numpy as np
import numpy.typing as npt

from glance.library.search import find
from glance.library.store import Library


class FakeEmbedder:
    """Puts a text on the x axis when it says "red" and on the y axis otherwise."""

    def embed_image(self, image: object) -> npt.NDArray[np.float32]:
        raise NotImplementedError

    def embed_text(self, text: str) -> npt.NDArray[np.float32]:
        return np.array([1, 0] if "red" in text else [0, 1], dtype=np.float32)


class FindTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.library = Library(self.root / "library.db")
        self.addCleanup(self.library.close)

    def _add(self, name: str, text: str, vector: list[float]) -> Path:
        path = self.root / name
        self.library.add(path, 1.0, 10, 5)
        id = self.library.pending()[-1].id
        self.library.set_text(id, text)
        self.library.set_embedding(id, np.array(vector, dtype=np.float32))
        return path.resolve()

    def test_a_capture_with_the_words_comes_before_one_that_only_looks_alike(
        self,
    ) -> None:
        alike = self._add("alike.png", "nothing here", [1, 0])
        worded = self._add("worded.png", "a red button", [0, 1])

        found = find(self.library, "red", FakeEmbedder())

        self.assertEqual([f.path for f in found], [worded, alike])
        self.assertIn("[red]", found[0].snippet)
        self.assertEqual(found[1].snippet, "")

    def test_a_capture_is_listed_once(self) -> None:
        both = self._add("both.png", "a red button", [1, 0])

        found = find(self.library, "red", FakeEmbedder())

        self.assertEqual([f.path for f in found], [both])

    def test_without_an_embedder_only_the_words_are_searched(self) -> None:
        self._add("alike.png", "nothing here", [1, 0])
        worded = self._add("worded.png", "a red button", [0, 1])

        found = find(self.library, "red", None)

        self.assertEqual([f.path for f in found], [worded])

    def test_a_blank_query_finds_nothing(self) -> None:
        self._add("a.png", "a red button", [1, 0])

        self.assertEqual(find(self.library, "   ", FakeEmbedder()), [])

    def test_the_result_is_limited(self) -> None:
        for name in ("a.png", "b.png", "c.png"):
            self._add(name, "no words", [1, 0])

        self.assertEqual(len(find(self.library, "red", FakeEmbedder(), limit=2)), 2)
