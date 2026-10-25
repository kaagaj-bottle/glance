"""The library: an index of kept screenshots and the text found in them.

The images stay where they were saved. This file only records where they are and
what they say, so deleting it loses nothing but the index.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
import numpy.typing as npt

SCHEMA_VERSION = 2
# Two one-shot processes (a capture and `glance library index`) may open the file
# at once; wait for each other rather than failing.
BUSY_TIMEOUT_MS = 5000
SNIPPET_WORDS = 12

PENDING = "pending"
DONE = "done"
FAILED = "failed"


@dataclass(frozen=True)
class Pending:
    id: int
    path: Path


@dataclass(frozen=True)
class Hit:
    path: Path
    taken_at: float
    snippet: str


@dataclass(frozen=True)
class Match:
    """A capture found by meaning. `score` is the cosine similarity, -1 to 1."""

    path: Path
    taken_at: float
    score: float


def match_query(text: str) -> str | None:
    """Turn what a person typed into an FTS5 query that matches each word.

    Every word is quoted, so punctuation such as `error:` or `foo-bar` is searched
    for rather than read as query syntax. None if there is nothing to search for.
    """
    words = text.split()
    if not words:
        return None
    return " ".join('"' + word.replace('"', '""') + '"' for word in words)


class Library:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000)
        self._db.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._create()

    def _create(self) -> None:
        with self._db:
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS captures (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE,
                    taken_at REAL NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    error TEXT
                )
                """
            )
            # The row id of a text is the id of its capture.
            self._db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS texts USING fts5(text)"
            )
            # One unit-length float32 vector per capture, for search by meaning.
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS embeddings ("
                " capture_id INTEGER PRIMARY KEY, vector BLOB NOT NULL)"
            )
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "Library":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def add(self, path: Path, taken_at: float, width: int, height: int) -> bool:
        """Record a capture to be read later. False if it is already known."""
        with self._db:
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO captures (path, taken_at, width, height)"
                " VALUES (?, ?, ?, ?)",
                (str(path.resolve()), taken_at, width, height),
            )
        return cursor.rowcount == 1

    def pending(self) -> list[Pending]:
        """Captures whose text has not been read yet, oldest first."""
        rows = cast(
            list[tuple[int, str]],
            self._db.execute(
                "SELECT id, path FROM captures WHERE state = ? ORDER BY taken_at, id",
                (PENDING,),
            ).fetchall(),
        )
        return [Pending(id, Path(path)) for id, path in rows]

    def set_text(self, id: int, text: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM texts WHERE rowid = ?", (id,))
            self._db.execute(
                "INSERT INTO texts (rowid, text) VALUES (?, ?)", (id, text)
            )
            self._db.execute(
                "UPDATE captures SET state = ?, error = NULL WHERE id = ?", (DONE, id)
            )

    def set_failed(self, id: int, error: str) -> None:
        """Remember that a capture could not be read, so it is not tried every run."""
        with self._db:
            self._db.execute(
                "UPDATE captures SET state = ?, error = ? WHERE id = ?",
                (FAILED, error, id),
            )

    def retry_failed(self) -> int:
        """Queue the captures that failed to be read again. Returns how many."""
        with self._db:
            cursor = self._db.execute(
                "UPDATE captures SET state = ?, error = NULL WHERE state = ?",
                (PENDING, FAILED),
            )
        return cursor.rowcount

    def search(self, query: str, limit: int = 20) -> list[Hit]:
        """Captures whose text has every word of the query, best match first."""
        match = match_query(query)
        if match is None:
            return []
        rows = cast(
            list[tuple[str, float, str]],
            self._db.execute(
                "SELECT c.path, c.taken_at,"
                f" snippet(texts, 0, '[', ']', '…', {SNIPPET_WORDS})"
                " FROM texts JOIN captures c ON c.id = texts.rowid"
                " WHERE texts MATCH ? ORDER BY bm25(texts) LIMIT ?",
                (match, limit),
            ).fetchall(),
        )
        return [
            Hit(Path(path), taken, " ".join(snip.split())) for path, taken, snip in rows
        ]

    def counts(self) -> dict[str, int]:
        """How many captures are in each state."""
        rows = cast(
            list[tuple[str, int]],
            self._db.execute(
                "SELECT state, COUNT(*) FROM captures GROUP BY state"
            ).fetchall(),
        )
        counts = {PENDING: 0, DONE: 0, FAILED: 0}
        counts.update(dict(rows))
        return counts

    def unembedded(self) -> list[Pending]:
        """Captures not yet searchable by meaning, oldest first.

        Ones whose text could not be read are left out: the file is missing or is
        not an image, and `retry_failed` brings them back.
        """
        rows = cast(
            list[tuple[int, str]],
            self._db.execute(
                "SELECT c.id, c.path FROM captures c"
                " LEFT JOIN embeddings e ON e.capture_id = c.id"
                " WHERE e.capture_id IS NULL AND c.state != ?"
                " ORDER BY c.taken_at, c.id",
                (FAILED,),
            ).fetchall(),
        )
        return [Pending(id, Path(path)) for id, path in rows]

    def set_embedding(self, id: int, vector: npt.NDArray[np.float32]) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO embeddings (capture_id, vector) VALUES (?, ?)",
                (id, vector.astype(np.float32).tobytes()),
            )

    def embedded(self) -> int:
        """How many captures can be found by meaning."""
        row = cast(
            tuple[int],
            self._db.execute("SELECT COUNT(*) FROM embeddings").fetchone(),
        )
        return row[0]

    def nearest(self, vector: npt.NDArray[np.float32], limit: int = 20) -> list[Match]:
        """Captures whose picture is closest to `vector`, best first.

        Every stored vector is compared; for a personal library that is fast and
        needs no index.
        """
        rows = cast(
            list[tuple[str, float, bytes]],
            self._db.execute(
                "SELECT c.path, c.taken_at, e.vector FROM embeddings e"
                " JOIN captures c ON c.id = e.capture_id"
            ).fetchall(),
        )
        rows = [row for row in rows if len(row[2]) == vector.nbytes]
        if not rows:
            return []
        matrix = np.stack([np.frombuffer(row[2], dtype=np.float32) for row in rows])
        scores = matrix @ vector.astype(np.float32)
        best = [int(i) for i in np.argsort(-scores)[:limit]]
        return [Match(Path(rows[i][0]), rows[i][1], float(scores[i])) for i in best]
