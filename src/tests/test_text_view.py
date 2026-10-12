import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from glance.actions import TextAction, search_url  # noqa: E402
from glance.ocr.types import OcrLine, OcrResult, OcrWord  # noqa: E402
from glance.ui.text_view import TextView  # noqa: E402


def _box(left: float, top: float, right: float, bottom: float):
    return ((left, top), (right, top), (right, bottom), (left, bottom))


def _line(text: str, top: float, spans: list[tuple[int, int]]) -> OcrLine:
    words = tuple(OcrWord(a, b, _box(a * 10, top, b * 10, top + 20)) for a, b in spans)
    return OcrLine(text, _box(0, top, len(text) * 10, top + 20), 1.0, words)


# A 400x100 image at 1:1: "hello world" on top, "second line" below.
RESULT = OcrResult(
    (
        _line("hello world", 10, [(0, 5), (6, 11)]),
        _line("second line", 60, [(0, 6), (7, 11)]),
    )
)


class TextViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        image = QImage(400, 100, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        self.ran: list[str] = []
        self.view = TextView(image, [TextAction("Do", self.ran.append)])
        self.view.resize(440, 200)
        self.view.show()
        self.canvas = self.view._canvas  # pyright: ignore[reportPrivateUsage]
        self.view.set_result(RESULT)
        self.app.processEvents()

    def _widget_point(self, x: float, y: float) -> QPoint:
        mapped = self.canvas._transform.map(  # pyright: ignore[reportPrivateUsage]
            QPoint(round(x), round(y))
        )
        return QPoint(round(mapped.x()), round(mapped.y()))

    def _drag(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        first, last = self._widget_point(*start), self._widget_point(*end)
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=first)
        QTest.mouseMove(self.canvas, last)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=last)

    def test_nothing_is_selected_at_first(self) -> None:
        self.assertEqual(self.view.selected_text(), "")

    def test_dragging_across_words_selects_them(self) -> None:
        self._drag((5, 20), (100, 20))
        self.assertEqual(self.view.selected_text(), "hello world")

    def test_dragging_down_a_line_extends_the_selection(self) -> None:
        self._drag((70, 20), (30, 70))
        self.assertEqual(self.view.selected_text(), "world\nsecond")

    def test_clicking_a_word_selects_it(self) -> None:
        QTest.mouseClick(
            self.canvas, Qt.MouseButton.LeftButton, pos=self._widget_point(20, 20)
        )
        self.assertEqual(self.view.selected_text(), "hello")

    def test_clicking_empty_space_clears_the_selection(self) -> None:
        self._drag((5, 20), (100, 20))
        QTest.mouseClick(
            self.canvas, Qt.MouseButton.LeftButton, pos=self._widget_point(300, 45)
        )
        self.assertEqual(self.view.selected_text(), "")

    def test_buttons_are_enabled_only_with_a_selection(self) -> None:
        button = self.view.findChild(QPushButton)
        assert button is not None
        self.assertFalse(button.isEnabled())
        self._drag((5, 20), (30, 20))
        self.assertTrue(button.isEnabled())

    def test_an_action_receives_the_selected_text(self) -> None:
        self._drag((5, 20), (30, 20))
        button = self.view.findChild(QPushButton)
        assert button is not None
        button.click()
        self.assertEqual(self.ran, ["hello"])

    def test_select_all_takes_every_line(self) -> None:
        self.canvas.select_all()
        self.assertEqual(self.view.selected_text(), "hello world\nsecond line")

    def test_closing_emits_closed(self) -> None:
        closed: list[bool] = []
        self.view.closed.connect(lambda: closed.append(True))
        self.view.close()
        self.assertEqual(closed, [True])


class SearchUrlTest(unittest.TestCase):
    def test_text_is_encoded_into_the_query(self) -> None:
        url = bytes(search_url("a&b c/ü").toEncoded().data()).decode()
        self.assertEqual(url, "https://www.google.com/search?q=a%26b+c%2F%C3%BC")


if __name__ == "__main__":
    unittest.main()
