"""`glance library`: turn the library on, read its captures and search them."""

import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from glance.library import settings
from glance.library.clip import DOWNLOAD_MEGABYTES, Model
from glance.library.indexer import embed_pending, index_pending
from glance.library.search import find
from glance.library.store import FAILED, PENDING, Library, Pending
from glance.ocr.worker import OcrEngine

DOWNLOAD_NOTE = f"about {DOWNLOAD_MEGABYTES} MB from huggingface.co"

USAGE = """usage: glance library <command>

  on             add each screenshot Glance saves to the library
  off            stop adding them (what is already there stays)
  status         say whether it is on and how many captures are in it
  index          read the text and the pictures of the captures not read yet
                 (downloads the image-search model the first time)
  retry          queue the captures that could not be read, and read them
  search WORDS   list the captures that have all of the words, then the ones
                 that look like what you typed
  open           open the library window
"""


def run(
    args: list[str],
    database: Path,
    engine: Callable[[], OcrEngine],
    model: Model,
    show: Callable[[], int],
) -> int:
    """Run one command. Returns the exit code.

    `engine` is called only to read the text, and `model` only to read the pictures
    or search by meaning. `show` opens the library window and returns its exit code.
    """
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
    if command == "open" and not words:
        return show()
    if command in ("status", "index", "retry", "search"):
        return _with_library(command, words, database, engine, model)
    print(USAGE, file=sys.stderr, end="")
    return 2


def _with_library(
    command: str,
    words: list[str],
    database: Path,
    engine: Callable[[], OcrEngine],
    model: Model,
) -> int:
    if command == "search" and not words:
        print(USAGE, file=sys.stderr, end="")
        return 2
    if command != "search" and words:
        print(USAGE, file=sys.stderr, end="")
        return 2
    with Library(database) as library:
        if command == "status":
            return _status(library, model)
        if command == "search":
            return _search(library, " ".join(words), model)
        if command == "retry":
            print(f"{library.retry_failed()} queued to be read again.")
        return _index(library, engine, model)


def _status(library: Library, model: Model) -> int:
    counts = library.counts()
    state = "on" if settings.is_enabled() else "off"
    print(f"The library is {state}.")
    total = sum(counts.values())
    print(f"{total} capture{'s' if total != 1 else ''}: ", end="")
    print(f"{counts[PENDING]} waiting to be read, {counts[FAILED]} that failed.")
    print(f"{library.embedded()} can be found by what they show.", end=" ")
    print(
        "The image-search model is " + ("ready." if model.ready else "not downloaded.")
    )
    return 0


def _index(library: Library, engine: Callable[[], OcrEngine], model: Model) -> int:
    waiting = library.pending()
    unembedded = library.unembedded()
    if not waiting and not unembedded:
        print("Nothing to read.")
        return 0

    def progress(item: Pending, error: str | None) -> None:
        if error is None:
            print(f"read    {item.path}")
        else:
            print(f"failed  {item.path}: {error}", file=sys.stderr)

    code = 0
    if waiting:
        result = index_pending(library, engine(), progress)
        print(f"Read the text of {result.read}, failed {result.failed}.")
        code = 1 if result.failed else 0
    # Captures whose text failed are not offered, so read the text first.
    unembedded = library.unembedded()
    if unembedded:
        if not model.ready:
            print(f"Downloading the image-search model ({DOWNLOAD_NOTE})…")
            try:
                model.download()
            except OSError as error:
                print(f"Could not download it: {error}", file=sys.stderr)
                return 1
        result = embed_pending(library, model.embedder(), progress)
        print(f"Read the picture of {result.read}, failed {result.failed}.")
        code = 1 if result.failed else code
    return code


def _search(library: Library, query: str, model: Model) -> int:
    embedder = model.embedder() if model.ready else None
    if embedder is None:
        print("Searching the words only: run `glance library index` first to", end=" ")
        print("download the image-search model.", file=sys.stderr)
    hits = find(library, query, embedder)
    for hit in hits:
        when = datetime.fromtimestamp(hit.taken_at)
        print(f"{hit.path}  ({when:%Y-%m-%d %H:%M})")
        print(f"    {hit.snippet or 'looks like what you typed'}")
    if not hits:
        print("No captures match.", file=sys.stderr)
    return 0 if hits else 1
