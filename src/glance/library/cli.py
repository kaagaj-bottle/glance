"""`glance library`: turn the library on, read its captures and search them."""

import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from glance.library import settings
from glance.library.indexer import index_pending
from glance.library.store import FAILED, PENDING, Library, Pending
from glance.ocr.worker import OcrEngine

USAGE = """usage: glance library <command>

  on             add each screenshot Glance saves to the library
  off            stop adding them (what is already there stays)
  status         say whether it is on and how many captures are in it
  index          read the text of the captures that have not been read yet
  retry          queue the captures that could not be read, and read them
  search WORDS   list the captures that have all of the words, best first
"""


def run(args: list[str], database: Path, engine: Callable[[], OcrEngine]) -> int:
    """Run one command. Returns the exit code. `engine` is called only to read."""
    command, words = (args[0], args[1:]) if args else ("", [])
    if command == "on" and not words:
        settings.set_enabled(True)
        print("Screenshots Glance saves from now on are added to the library.")
        print("Run `glance library index` to read their text.")
        return 0
    if command == "off" and not words:
        settings.set_enabled(False)
        print("New screenshots are no longer added to the library.")
        return 0
    if command in ("status", "index", "retry", "search"):
        return _with_library(command, words, database, engine)
    print(USAGE, file=sys.stderr, end="")
    return 2


def _with_library(
    command: str, words: list[str], database: Path, engine: Callable[[], OcrEngine]
) -> int:
    if command == "search" and not words:
        print(USAGE, file=sys.stderr, end="")
        return 2
    if command != "search" and words:
        print(USAGE, file=sys.stderr, end="")
        return 2
    with Library(database) as library:
        if command == "status":
            return _status(library)
        if command == "search":
            return _search(library, " ".join(words))
        if command == "retry":
            print(f"{library.retry_failed()} queued to be read again.")
        return _index(library, engine)


def _status(library: Library) -> int:
    counts = library.counts()
    state = "on" if settings.is_enabled() else "off"
    print(f"The library is {state}.")
    total = sum(counts.values())
    print(f"{total} capture{'s' if total != 1 else ''}: ", end="")
    print(f"{counts[PENDING]} waiting to be read, {counts[FAILED]} that failed.")
    return 0


def _index(library: Library, engine: Callable[[], OcrEngine]) -> int:
    if not library.pending():
        print("Nothing to read.")
        return 0

    def progress(item: Pending, error: str | None) -> None:
        if error is None:
            print(f"read    {item.path}")
        else:
            print(f"failed  {item.path}: {error}", file=sys.stderr)

    result = index_pending(library, engine(), progress)
    print(f"Read {result.read}, failed {result.failed}.")
    return 1 if result.failed else 0


def _search(library: Library, query: str) -> int:
    hits = library.search(query)
    for hit in hits:
        when = datetime.fromtimestamp(hit.taken_at)
        print(f"{hit.path}  ({when:%Y-%m-%d %H:%M})")
        print(f"    {hit.snippet}")
    if not hits:
        print("No captures match.", file=sys.stderr)
    return 0 if hits else 1
