"""Searching the library by the words in screenshots and by what they show."""

from dataclasses import dataclass
from pathlib import Path

from glance.library.clip import Embedder
from glance.library.store import Library

# Matches by meaning always exist, however poor, so only this many are shown.
LIMIT = 20


@dataclass(frozen=True)
class Found:
    path: Path
    taken_at: float
    # The words that matched in `[brackets]`; empty for a match by meaning.
    snippet: str


def find(
    library: Library, query: str, embedder: Embedder | None, limit: int = LIMIT
) -> list[Found]:
    """Captures that say the words of the query, then captures that look like it.

    A capture holding every word comes first, since that is the surest match. The
    rest are the closest pictures by meaning, when there is an `embedder`.
    """
    found = [Found(h.path, h.taken_at, h.snippet) for h in library.search(query, limit)]
    if embedder is None or not query.strip() or len(found) >= limit:
        return found
    seen = {f.path for f in found}
    nearest = library.nearest(embedder.embed_text(query.strip()), limit)
    found.extend(Found(m.path, m.taken_at, "") for m in nearest if m.path not in seen)
    return found[:limit]
