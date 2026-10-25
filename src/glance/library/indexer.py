"""Reading the text of captures that the library has not read yet."""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtGui import QImage

from glance.library.clip import Embedder
from glance.library.store import Library, Pending
from glance.ocr.worker import OcrEngine


@dataclass(frozen=True)
class Indexed:
    read: int
    failed: int


def index_pending(
    library: Library,
    engine: OcrEngine,
    progress: Callable[[Pending, str | None], None] | None = None,
) -> Indexed:
    """Read the text of every pending capture, one after another.

    A capture that cannot be read is marked failed, with the reason, so it does not
    block the ones after it or get tried again on every run. `progress` is called
    after each capture with the reason it failed, or None if it was read.
    """
    read = failed = 0
    for item in library.pending():
        error = _read(library, engine, item)
        if error is None:
            read += 1
        else:
            failed += 1
        if progress is not None:
            progress(item, error)
    return Indexed(read, failed)


def _read(library: Library, engine: OcrEngine, item: Pending) -> str | None:
    """Store the capture's text. Returns why it could not, or None."""
    if not item.path.is_file():
        error = "the file is missing"
    else:
        image = QImage(str(item.path))
        if image.isNull():
            error = "the file is not an image Glance can open"
        else:
            try:
                text = engine.recognize(image).text
            except Exception as problem:  # the model can fail in many ways
                error = str(problem) or type(problem).__name__
            else:
                library.set_text(item.id, text)
                return None
    library.set_failed(item.id, error)
    return error


def embed_pending(
    library: Library,
    embedder: Embedder,
    progress: Callable[[Pending, str | None], None] | None = None,
) -> Indexed:
    """Make every capture that is not yet searchable by meaning so, one by one.

    Unlike reading the text, a capture that cannot be embedded is not marked: a
    missing file is just skipped, and it is tried again on the next run.
    """
    done = failed = 0
    for item in library.unembedded():
        error = _embed(library, embedder, item)
        if error is None:
            done += 1
        else:
            failed += 1
        if progress is not None:
            progress(item, error)
    return Indexed(done, failed)


def _embed(library: Library, embedder: Embedder, item: Pending) -> str | None:
    """Store the capture's vector. Returns why it could not, or None."""
    image = QImage(str(item.path))
    if image.isNull():
        return "the file is missing or is not an image Glance can open"
    try:
        library.set_embedding(item.id, embedder.embed_image(image))
    except Exception as problem:  # the model can fail in many ways
        return str(problem) or type(problem).__name__
    return None
