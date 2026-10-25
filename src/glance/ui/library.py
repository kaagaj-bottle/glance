"""The library window: search saved screenshots by their words or by what they show."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from glance.background import BackgroundTask
from glance.library.clip import DOWNLOAD_MEGABYTES, Model
from glance.library.indexer import embed_pending, index_pending
from glance.library.search import Found, find
from glance.library.store import Library
from glance.ocr.worker import OcrEngine
from glance.ui.panel import ACCENT, MUTED, TEXT

THUMBNAIL = QSize(240, 150)
GRID = QSize(264, 240)
RANKS = ("#1  Best match", "#2  Second best", "#3  Third best")

_STYLE = f"""
QWidget {{ background: rgb(24, 24, 32); }}
QLabel {{ color: {TEXT}; font: 400 13px sans-serif; }}
QLabel#note {{ color: {MUTED}; font: 400 12px sans-serif; }}
QLineEdit {{
    background: rgba(255, 255, 255, 20);
    border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 9px;
    color: {TEXT};
    font: 400 14px sans-serif;
    padding: 8px 12px;
}}
QPushButton {{
    background: rgba(255, 255, 255, 20);
    border: none;
    border-radius: 9px;
    color: {TEXT};
    font: 600 12px sans-serif;
    padding: 8px 16px;
}}
QPushButton:hover {{ background: rgba(255, 255, 255, 36); }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton#primary {{ background: {ACCENT}; color: #12121A; }}
QPushButton#primary:disabled {{ background: rgba(255, 255, 255, 25); color: {MUTED}; }}
QListWidget {{ border: none; color: {TEXT}; font: 400 11px sans-serif; }}
QListWidget::item {{ border-radius: 9px; padding: 6px; }}
QListWidget::item:selected {{ background: rgba(139, 124, 255, 70); }}
"""

DOWNLOAD_NOTE = (
    "To find screenshots by what they show, Glance downloads an image-understanding "
    f"model once ({DOWNLOAD_MEGABYTES} MB from huggingface.co). It then runs offline. "
    "Searching by their words works without it."
)


class LibraryWindow(QWidget):
    """A search box over the library, with the matching screenshots as thumbnails.

    It opens the library file itself for each job: a connection cannot be shared
    between threads, and the searches and the reading of new screenshots run off the
    UI thread.
    """

    closed = Signal()

    def __init__(
        self,
        database: Path,
        model: Model,
        engine: Callable[[], OcrEngine],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._database = database
        self._model = model
        self._engine = engine
        self._tasks: list[BackgroundTask] = []
        self._found: list[Found] = []
        self._search_number = 0
        self._preparing = False
        self.setWindowTitle("Glance: library")
        self.setStyleSheet(_STYLE)
        self.resize(900, 640)

        self._query = QLineEdit()
        self._query.setPlaceholderText("Search by words or by what a screenshot shows…")
        self._query.returnPressed.connect(self.search)
        self._query.setClearButtonEnabled(True)
        self._search_button = QPushButton("Search")
        self._search_button.setObjectName("primary")
        self._search_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._search_button.clicked.connect(self.search)

        self._download_note = QLabel(DOWNLOAD_NOTE)
        self._download_note.setObjectName("note")
        self._download_note.setWordWrap(True)
        self._download_button = QPushButton("Download the model")
        self._download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._download_button.clicked.connect(self._download)
        self._download_row = QWidget()
        row = QHBoxLayout(self._download_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._download_note, 1)
        row.addWidget(self._download_button)

        self._results = QListWidget()
        self._results.setViewMode(QListView.ViewMode.IconMode)
        self._results.setResizeMode(QListView.ResizeMode.Adjust)
        self._results.setMovement(QListView.Movement.Static)
        self._results.setIconSize(THUMBNAIL)
        self._results.setGridSize(GRID)
        self._results.setWordWrap(True)
        self._results.setUniformItemSizes(True)
        self._results.itemActivated.connect(self._open)
        self._status = QLabel()
        self._status.setObjectName("note")
        self._status.setWordWrap(True)

        bar = QHBoxLayout()
        bar.addWidget(self._query, 1)
        bar.addWidget(self._search_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(12)
        layout.addLayout(bar)
        layout.addWidget(self._download_row)
        layout.addWidget(self._results, 1)
        layout.addWidget(self._status)

        self._show_model_state()
        self._prepare()

    def closeEvent(self, event: QCloseEvent) -> None:
        super().closeEvent(event)
        self.closed.emit()

    def search(self) -> None:
        """Search for what is typed. Of several searches under way, the latest wins."""
        query = self._query.text().strip()
        if not query:
            self._show([], "Type some words, or describe what the screenshot shows.")
            return
        self._search_number += 1
        number = self._search_number
        self._status.setText("Searching…")
        holder: list[Found] = []

        def work() -> None:
            embedder = self._model.embedder() if self._model.ready else None
            with Library(self._database) as library:
                holder.extend(find(library, query, embedder))

        task = self._run(work)
        task.done.connect(lambda: self._searched(number, query, holder))
        task.failed.connect(self._status.setText)

    def _searched(self, number: int, query: str, found: list[Found]) -> None:
        if number != self._search_number:
            return  # an older search, answered after a newer one was started
        self._show(found, "" if found else "No screenshots match.", query)

    def _show(self, found: list[Found], status: str, query: str = "") -> None:
        self._found = found
        self._results.clear()
        for rank, item in enumerate(found):
            self._results.addItem(self._item(item, rank, query))
        self._status.setText(status or self._summary(len(found), query))

    def _summary(self, count: int, query: str) -> str:
        return (
            f"Top {count} match{'es' if count != 1 else ''} for \u201c{query}\u201d, "
            "best first. Double-click one to open it."
        )

    def _item(self, found: Found, rank: int, query: str) -> QListWidgetItem:
        when = datetime.fromtimestamp(found.taken_at)
        title = RANKS[rank] if rank < len(RANKS) else f"#{rank + 1}"
        why = (
            f"Has your words: {found.snippet}"
            if found.snippet
            else f"Looks like \u201c{query}\u201d"
        )
        label = f"{title}\n{why}\n{when:%Y-%m-%d %H:%M}"
        item = QListWidgetItem(QIcon(thumbnail(found.path)), label)
        item.setData(Qt.ItemDataRole.UserRole, str(found.path))
        item.setToolTip(str(found.path))
        item.setSizeHint(GRID)
        return item

    def _open(self, item: QListWidgetItem) -> None:
        path = str(item.data(Qt.ItemDataRole.UserRole))
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _show_model_state(self) -> None:
        self._download_row.setVisible(not self._model.ready)

    def _download(self) -> None:
        self._download_button.setEnabled(False)
        self._download_button.setText("Downloading…")
        task = self._run(self._model.download)
        task.done.connect(self._downloaded)
        task.failed.connect(self._download_failed)

    def _downloaded(self) -> None:
        self._show_model_state()
        self._prepare()

    def _download_failed(self, message: str) -> None:
        self._download_button.setEnabled(True)
        self._download_button.setText("Try again")
        self._status.setText(f"Could not download the model: {message}")

    def _prepare(self) -> None:
        """Read, in the background, the screenshots added since the last time."""
        if self._preparing:
            return
        self._preparing = True
        self._status.setText("Reading new screenshots…")

        def work() -> None:
            with Library(self._database) as library:
                if library.pending():
                    index_pending(library, self._engine())
                if self._model.ready and library.unembedded():
                    embed_pending(library, self._model.embedder())

        task = self._run(work)
        task.done.connect(self._prepared)
        task.failed.connect(self._prepared_failed)

    def _prepared(self) -> None:
        self._preparing = False
        with Library(self._database) as library:
            total = sum(library.counts().values())
            seen = library.embedded()
        self._status.setText(
            f"{total} screenshot{'s' if total != 1 else ''} in the library, "
            f"{seen} that can be found by what they show."
        )
        if self._query.text().strip():
            self.search()

    def _prepared_failed(self, message: str) -> None:
        self._preparing = False
        self._status.setText(f"Could not read the new screenshots: {message}")

    def _run(self, work: Callable[[], None]) -> BackgroundTask:
        task = BackgroundTask(work, self)
        self._tasks.append(task)

        def forget() -> None:
            if task in self._tasks:
                self._tasks.remove(task)

        task.done.connect(forget)
        task.failed.connect(forget)
        task.start()
        return task


def thumbnail(path: Path) -> QPixmap:
    """The picture scaled down while it is read, so a huge screenshot stays cheap."""
    reader = QImageReader(str(path))
    size = reader.size()
    if size.isValid():
        reader.setScaledSize(size.scaled(THUMBNAIL, Qt.AspectRatioMode.KeepAspectRatio))
    return QPixmap.fromImage(reader.read())
