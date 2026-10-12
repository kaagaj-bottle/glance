import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from glance.capture.manager import CaptureManager
from glance.capture.types import Monitor, Screenshot


def _record(manager: CaptureManager) -> tuple[list[Screenshot], list[str]]:
    shots: list[Screenshot] = []
    errors: list[str] = []
    manager.captured.connect(shots.append)
    manager.failed.connect(errors.append)
    return shots, errors


def _image() -> QImage:
    return QImage(2, 2, QImage.Format.Format_RGB32)


def _screen() -> MagicMock:
    screen = MagicMock()
    screen.name.return_value = "DP-1"
    screen.geometry.return_value = QRect(0, 0, 2, 2)
    screen.grabWindow.return_value.toImage.return_value = _image()
    return screen


class CaptureManagerTest(unittest.TestCase):
    def test_portal_image_is_paired_with_the_current_monitors(self) -> None:
        manager = CaptureManager()
        shots, errors = _record(manager)
        monitor = Monitor(0, "DP-1", QRect(0, 0, 2, 2))

        with (
            patch("glance.capture.manager.PortalScreenshot") as portal_class,
            patch("glance.capture.manager.current_monitors", return_value=(monitor,)),
        ):
            portal = portal_class.return_value
            portal.start.return_value = True
            manager.capture_screen()
            portal.captured.connect.call_args.args[0](_image())

        self.assertEqual(errors, [])
        self.assertEqual(len(shots), 1)
        self.assertEqual(shots[0].monitors, (monitor,))

    def test_portal_failure_is_reported_without_fallback(self) -> None:
        manager = CaptureManager()
        shots, errors = _record(manager)

        with (
            patch("glance.capture.manager.PortalScreenshot") as portal_class,
            patch("glance.capture.manager.QGuiApplication") as gui,
        ):
            portal = portal_class.return_value
            portal.start.return_value = True
            manager.capture_screen()
            portal.failed.connect.call_args.args[0]("Screenshot was cancelled.")

        self.assertEqual(errors, ["Screenshot was cancelled."])
        self.assertEqual(shots, [])
        gui.primaryScreen.assert_not_called()

    def test_falls_back_to_qt_on_x11_when_portal_is_unavailable(self) -> None:
        manager = CaptureManager()
        shots, errors = _record(manager)
        other, screen = _screen(), _screen()

        with (
            patch("glance.capture.manager.PortalScreenshot") as portal_class,
            patch("glance.capture.manager.QGuiApplication") as gui,
        ):
            portal_class.return_value.start.return_value = False
            gui.platformName.return_value = "xcb"
            gui.primaryScreen.return_value = screen
            gui.screens.return_value = [other, screen]
            manager.capture_screen()

        self.assertEqual(errors, [])
        self.assertEqual(len(shots), 1)
        self.assertEqual([m.index for m in shots[0].monitors], [1])

    def test_no_qt_fallback_on_wayland(self) -> None:
        manager = CaptureManager()
        shots, errors = _record(manager)

        with (
            patch("glance.capture.manager.PortalScreenshot") as portal_class,
            patch("glance.capture.manager.QGuiApplication") as gui,
        ):
            portal_class.return_value.start.return_value = False
            gui.platformName.return_value = "wayland"
            gui.primaryScreen.return_value = _screen()
            manager.capture_screen()

        self.assertEqual(shots, [])
        self.assertEqual(len(errors), 1)
