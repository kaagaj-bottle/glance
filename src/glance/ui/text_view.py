from typing import override

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QImage,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygonF,
    QShortcut,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from glance.actions import TextAction
from glance.ocr.types import OcrResult
from glance.ui.text_selection import TextLayout

ACCENT = QColor("#3584e4")
WORD_OUTLINE = QColor(53, 132, 228, 80)
WORD_FILL = QColor(53, 132, 228, 110)
FEEDBACK_MS = 1200
MIN_SIZE = QSize(420, 260)
SCREEN_SHARE = 0.8


class _Canvas(QWidget):
    """Draws the capture and lets the user drag over its words."""

    selection_changed = Signal()

    def __init__(self, image: QImage) -> None:
        super().__init__()
        self._image = image
        self._layout: TextLayout | None = None
        self._range: tuple[int, int] | None = None
        self._anchor: int | None = None
        self._transform = QTransform()
        self._message = "Reading text…"
        self.setMouseTracking(True)
        self.setMinimumSize(MIN_SIZE.width(), 120)

    def set_result(self, result: OcrResult) -> None:
        self._layout = TextLayout(result)
        self._range = None
        self._message = "" if self._layout.words else "No text found"
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.update()

    def set_error(self, message: str) -> None:
        self._message = f"Could not read the text: {message}"
        self.update()

    def selected_text(self) -> str:
        if self._layout is None or self._range is None:
            return ""
        return self._layout.text(*self._range)

    def select_all(self) -> None:
        if self._layout is not None and self._layout.words:
            self._select(0, len(self._layout.words) - 1)

    def _select(self, first: int, last: int) -> None:
        self._range = (min(first, last), max(first, last))
        self.selection_changed.emit()
        self.update()

    def _clear(self) -> None:
        if self._range is not None:
            self._range = None
            self.selection_changed.emit()
            self.update()

    def _fit(self) -> QTransform:
        """Image pixels to widget coordinates, shrunk to fit but never enlarged."""
        scale = min(
            self.width() / self._image.width(),
            self.height() / self._image.height(),
            1.0,
        )
        transform = QTransform()
        transform.translate(
            (self.width() - self._image.width() * scale) / 2,
            (self.height() - self._image.height() * scale) / 2,
        )
        transform.scale(scale, scale)
        return transform

    def _to_image(self, point: QPointF) -> QPointF:
        inverse, invertible = self._transform.inverted()
        return inverse.map(point) if invertible else point

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._layout is None:
            return
        self._anchor = self._layout.word_at(self._to_image(event.position()))
        if self._anchor is None:
            self._clear()
        else:
            self._select(self._anchor, self._anchor)

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._layout is None or self._anchor is None:
            return
        if event.buttons() & Qt.MouseButton.LeftButton:
            focus = self._layout.nearest_word(self._to_image(event.position()))
            if focus is not None:
                self._select(self._anchor, focus)

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._anchor = None

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._transform = self._fit()
        painter.setTransform(self._transform)
        painter.drawImage(0, 0, self._image)
        if self._layout is not None:
            self._paint_words(painter, self._layout)
        painter.resetTransform()
        if self._message:
            self._paint_message(painter)

    def _paint_words(self, painter: QPainter, layout: TextLayout) -> None:
        selected = range(self._range[0], self._range[1] + 1) if self._range else ()
        for number, word in enumerate(layout.words):
            shape = QPolygonF([QPointF(x, y) for x, y in word.box])
            if number in selected:
                painter.setPen(QPen(ACCENT, 1))
                painter.setBrush(WORD_FILL)
            else:
                painter.setPen(QPen(WORD_OUTLINE, 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(shape)

    def _paint_message(self, painter: QPainter) -> None:
        box = QRectF(self.rect()).adjusted(16, 16, -16, -16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 190))
        metrics = painter.fontMetrics()
        text = metrics.elidedText(
            self._message, Qt.TextElideMode.ElideRight, int(box.width()) - 24
        )
        pill = QRectF(0, 0, metrics.horizontalAdvance(text) + 24, metrics.height() + 12)
        pill.moveCenter(box.center())
        painter.drawRoundedRect(pill, 8, 8)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)


class TextView(QWidget):
    """A capture with its recognized words, to select and act on like page text.

    Shown at once with the image so the user is not left waiting while OCR runs;
    `set_result` or `set_error` then fills it in. Emits `closed` when it goes.
    """

    closed = Signal()

    def __init__(
        self,
        image: QImage,
        actions: list[TextAction],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Glance - Text")
        self._actions = actions
        self._canvas = _Canvas(image)
        self._canvas.selection_changed.connect(self._update_buttons)
        self._hint = QLabel("Drag over text to select it")
        self._buttons: dict[QPushButton, TextAction] = {}

        bar = QHBoxLayout()
        bar.addWidget(self._hint)
        bar.addStretch()
        for action in actions:
            button = QPushButton(action.label)
            button.setEnabled(False)
            button.clicked.connect(lambda _=False, b=button: self._run(b))
            bar.addWidget(button)
            self._buttons[button] = action
        layout = QVBoxLayout(self)
        layout.addWidget(self._canvas, 1)
        layout.addLayout(bar)

        QShortcut(QKeySequence("Escape"), self, self.close)
        QShortcut(QKeySequence.StandardKey.SelectAll, self, self._canvas.select_all)
        QShortcut(QKeySequence.StandardKey.Copy, self, self._run_first)
        self.resize(self._initial_size(image))

    def _initial_size(self, image: QImage) -> QSize:
        screen = QApplication.primaryScreen()
        limit = screen.availableSize() * SCREEN_SHARE if screen else QSize(1000, 700)
        size = image.size().boundedTo(limit) + QSize(32, 64)
        return size.expandedTo(MIN_SIZE)

    def set_result(self, result: OcrResult) -> None:
        self._canvas.set_result(result)

    def set_error(self, message: str) -> None:
        self._canvas.set_error(message)

    def selected_text(self) -> str:
        return self._canvas.selected_text()

    def _update_buttons(self) -> None:
        has_text = bool(self.selected_text())
        for button in self._buttons:
            button.setEnabled(has_text)
        self._hint.setText("" if has_text else "Drag over text to select it")

    def _run(self, button: QPushButton) -> None:
        text = self.selected_text()
        if not text:
            return
        self._buttons[button].run(text)
        label = self._buttons[button].label
        button.setText("Done")
        QTimer.singleShot(FEEDBACK_MS, lambda: button.setText(label))

    def _run_first(self) -> None:
        """Ctrl+C runs the first action, which is Copy."""
        for button in self._buttons:
            self._run(button)
            return

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        super().closeEvent(event)
        self.closed.emit()
