import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication, QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance.ui.text_result import TextResultWindow  # noqa: E402


class TextResultWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_shows_the_recognized_text(self) -> None:
        self.assertEqual(TextResultWindow("one\ntwo").text(), "one\ntwo")

    def test_copy_uses_the_edited_text(self) -> None:
        window = TextResultWindow("draft")
        window._edit.setPlainText("fixed")  # pyright: ignore[reportPrivateUsage]
        window.copy()
        self.assertEqual(QGuiApplication.clipboard().text(), "fixed")

    def test_copy_uses_only_the_highlighted_part(self) -> None:
        window = TextResultWindow("one\ntwo\nthree")
        edit = window._edit  # pyright: ignore[reportPrivateUsage]
        cursor = edit.textCursor()
        cursor.setPosition(0)
        cursor.movePosition(
            QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor
        )
        edit.setTextCursor(cursor)
        window.copy()
        self.assertEqual(QGuiApplication.clipboard().text(), "one\ntwo")

    def test_closing_emits_closed(self) -> None:
        window = TextResultWindow("x")
        closed: list[bool] = []
        window.closed.connect(lambda: closed.append(True))
        window.show()
        window.close()
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
