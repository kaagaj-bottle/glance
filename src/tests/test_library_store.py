import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np

from glance.library.store import DONE, FAILED, PENDING, Library, match_query


class MatchQueryTest(unittest.TestCase):
    def test_each_word_is_quoted(self) -> None:
        self.assertEqual(match_query("database timeout"), '"database" "timeout"')

    def test_nothing_to_search_for(self) -> None:
        self.assertIsNone(match_query("   "))

    def test_a_quote_is_doubled(self) -> None:
        self.assertEqual(match_query('say "hi'), '"say" """hi"')


class LibraryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.library = Library(self.root / "data" / "library.db")
        self.addCleanup(self.library.close)

    def _add(self, name: str, taken_at: float = 1.0) -> Path:
        path = self.root / name
        self.library.add(path, taken_at, 10, 5)
        return path

    def test_a_capture_is_pending_until_its_text_is_read(self) -> None:
        path = self._add("a.png")

        pending = self.library.pending()

        self.assertEqual([p.path for p in pending], [path.resolve()])
        self.assertEqual(self.library.counts()[PENDING], 1)

    def test_adding_the_same_path_twice_keeps_one_row(self) -> None:
        self._add("a.png")

        self.assertFalse(self.library.add(self.root / "a.png", 2.0, 10, 5))
        self.assertEqual(len(self.library.pending()), 1)

    def test_the_same_file_by_another_spelling_is_still_one_row(self) -> None:
        self._add("a.png")

        self.assertFalse(self.library.add(self.root / "x" / ".." / "a.png", 2.0, 1, 1))

    def test_pending_is_oldest_first(self) -> None:
        newer = self._add("new.png", 2.0)
        older = self._add("old.png", 1.0)

        self.assertEqual(
            [p.path for p in self.library.pending()], [older.resolve(), newer.resolve()]
        )

    def test_a_read_capture_is_found_by_its_words(self) -> None:
        path = self._add("a.png")
        self.library.set_text(
            self.library.pending()[0].id, "Connection to db timed out"
        )

        hits = self.library.search("timed out")

        self.assertEqual([h.path for h in hits], [path.resolve()])
        self.assertIn("[timed]", hits[0].snippet)
        self.assertEqual(self.library.counts()[DONE], 1)
        self.assertEqual(self.library.pending(), [])

    def test_every_word_must_match(self) -> None:
        self._add("a.png")
        self.library.set_text(self.library.pending()[0].id, "database error")

        self.assertEqual(self.library.search("database timeout"), [])

    def test_punctuation_in_a_query_is_not_query_syntax(self) -> None:
        self._add("a.png")
        self.library.set_text(self.library.pending()[0].id, "error: foo-bar failed")

        for query in ["error:", "foo-bar", 'say "hi', "a AND", "(", "*", "NEAR(", "-x"]:
            with self.subTest(query=query):
                self.library.search(query)
        self.assertEqual(len(self.library.search("error: foo-bar")), 1)

    def test_a_blank_query_finds_nothing(self) -> None:
        self.assertEqual(self.library.search("  "), [])

    def test_the_better_match_comes_first(self) -> None:
        self._add("weak.png", 1.0)
        self._add("strong.png", 2.0)
        weak, strong = self.library.pending()
        self.library.set_text(weak.id, "one error among many many other words here")
        self.library.set_text(strong.id, "error error error")

        hits = self.library.search("error")

        self.assertEqual([h.path for h in hits], [strong.path, weak.path])

    def test_a_snippet_is_one_line(self) -> None:
        self._add("a.png")
        self.library.set_text(self.library.pending()[0].id, "first line\nsecond line")

        self.assertNotIn("\n", self.library.search("first")[0].snippet)

    def test_setting_the_text_again_replaces_it(self) -> None:
        self._add("a.png")
        id = self.library.pending()[0].id
        self.library.set_text(id, "old words")
        self.library.set_text(id, "new words")

        self.assertEqual(self.library.search("old"), [])
        self.assertEqual(len(self.library.search("new")), 1)

    def test_a_failed_capture_is_not_tried_again_until_asked(self) -> None:
        self._add("a.png")
        self.library.set_failed(self.library.pending()[0].id, "file is missing")

        self.assertEqual(self.library.pending(), [])
        self.assertEqual(self.library.counts()[FAILED], 1)
        self.assertEqual(self.library.retry_failed(), 1)
        self.assertEqual(len(self.library.pending()), 1)

    def test_the_index_survives_reopening(self) -> None:
        self._add("a.png")
        self.library.set_text(self.library.pending()[0].id, "kept words")
        self.library.close()

        with Library(self.root / "data" / "library.db") as again:
            self.assertEqual(len(again.search("kept")), 1)


if __name__ == "__main__":
    unittest.main()


class EmbeddingTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.library = Library(self.root / "library.db")
        self.addCleanup(self.library.close)

    def _add(self, name: str) -> int:
        self.library.add(self.root / name, 1.0, 10, 5)
        return self.library.pending()[-1].id

    def test_a_capture_is_unembedded_until_its_vector_is_stored(self) -> None:
        id = self._add("a.png")
        self.assertEqual([p.id for p in self.library.unembedded()], [id])

        self.library.set_embedding(id, np.array([1, 0], dtype=np.float32))

        self.assertEqual(self.library.unembedded(), [])
        self.assertEqual(self.library.embedded(), 1)

    def test_a_capture_that_failed_to_be_read_is_not_offered(self) -> None:
        self.library.set_failed(self._add("a.png"), "the file is missing")

        self.assertEqual(self.library.unembedded(), [])

    def test_the_closest_vector_comes_first(self) -> None:
        near = self._add("near.png")
        far = self._add("far.png")
        self.library.set_embedding(near, np.array([1, 0], dtype=np.float32))
        self.library.set_embedding(far, np.array([0, 1], dtype=np.float32))

        matches = self.library.nearest(np.array([0.9, 0.1], dtype=np.float32))

        self.assertEqual(
            [m.path for m in matches],
            [(self.root / "near.png").resolve(), (self.root / "far.png").resolve()],
        )
        self.assertAlmostEqual(matches[0].score, 0.9, places=5)

    def test_the_number_of_matches_is_limited(self) -> None:
        for name in ("a.png", "b.png", "c.png"):
            self.library.set_embedding(
                self._add(name), np.array([1, 0], dtype=np.float32)
            )

        matches = self.library.nearest(np.array([1, 0], dtype=np.float32), limit=2)

        self.assertEqual(len(matches), 2)

    def test_nothing_is_found_in_an_empty_library(self) -> None:
        self.assertEqual(self.library.nearest(np.array([1, 0], dtype=np.float32)), [])

    def test_a_vector_of_another_size_is_ignored(self) -> None:
        self.library.set_embedding(
            self._add("old.png"), np.array([1, 0, 0], dtype=np.float32)
        )

        self.assertEqual(self.library.nearest(np.array([1, 0], dtype=np.float32)), [])

    def test_a_library_made_before_embeddings_gains_them(self) -> None:
        path = self.root / "old.db"
        old = sqlite3.connect(path)
        old.execute(
            "CREATE TABLE captures (id INTEGER PRIMARY KEY, path TEXT NOT NULL"
            " UNIQUE, taken_at REAL NOT NULL, width INTEGER NOT NULL,"
            " height INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'pending',"
            " error TEXT)"
        )
        old.execute("PRAGMA user_version = 1")
        old.commit()
        old.close()

        with Library(path) as library:
            self.assertEqual(library.embedded(), 0)
