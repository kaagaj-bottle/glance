import contextlib
import io
import os
import unittest
from typing import cast
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QClipboard, QColor, QGuiApplication, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance.app import App  # noqa: E402
from glance.smart import Entity, Kind  # noqa: E402


def _image() -> QImage:
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    return image


class CopyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(QApplication, QApplication.instance() or QApplication([]))

    def setUp(self) -> None:
        self.glance = App(self.app)
        self.quit = MagicMock()
        self.glance._app = MagicMock(quit=self.quit)  # pyright: ignore[reportPrivateUsage]
        self.clipboard = QGuiApplication.clipboard()

    def _quiet(self) -> contextlib.AbstractContextManager[object]:
        return contextlib.redirect_stdout(io.StringIO())

    def _taken_by_another_app(self) -> None:
        with patch.object(QClipboard, "ownsClipboard", return_value=False):
            self.clipboard.dataChanged.emit()

    def test_a_copied_image_is_on_the_clipboard_and_the_app_stays_alive(self) -> None:
        self.glance._copy_image(_image())  # pyright: ignore[reportPrivateUsage]

        image = self.clipboard.image()
        self.assertEqual((image.width(), image.height()), (4, 3))
        self.quit.assert_not_called()

    def test_the_app_quits_once_another_app_takes_the_clipboard(self) -> None:
        self.glance._copy_image(_image())  # pyright: ignore[reportPrivateUsage]

        self._taken_by_another_app()

        self.quit.assert_called_once()

    def test_a_clipboard_change_by_glance_itself_does_not_quit(self) -> None:
        self.glance._copy_image(_image())  # pyright: ignore[reportPrivateUsage]

        with patch.object(QClipboard, "ownsClipboard", return_value=True):
            self.clipboard.dataChanged.emit()

        self.quit.assert_not_called()

    def test_copy_text_stays_alive_the_same_way(self) -> None:
        self.glance._copy_text("hello")  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(self.clipboard.text(), "hello")
        self.quit.assert_not_called()
        self._taken_by_another_app()
        self.quit.assert_called_once()

    def test_opening_a_link_opens_it_and_then_quits(self) -> None:
        entity = Entity(Kind.LINK, "example.org", "https://example.org")

        with (
            patch("glance.app.open_entity") as opened,
            patch("glance.app.QTimer.singleShot") as later,
        ):
            self.glance._open_entity(entity)  # pyright: ignore[reportPrivateUsage]

        opened.assert_called_once_with(entity)
        later.assert_called_once()

    def test_copy_and_save_keeps_the_image_on_the_clipboard(self) -> None:
        with patch("glance.app.save", return_value="shot.png"), self._quiet():
            self.glance._finish(_image())  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(self.clipboard.image().width(), 4)
        self.quit.assert_not_called()

    def test_save_only_quits_right_away(self) -> None:
        with patch("glance.app.save", return_value="shot.png"), self._quiet():
            self.glance._save_image(_image())  # pyright: ignore[reportPrivateUsage]

        self.quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
