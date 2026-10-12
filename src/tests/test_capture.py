import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QImage

from glance.capture.manager import CaptureManager, with_native_frames
from glance.capture.screencast import Frame
from glance.capture.types import Monitor, Screenshot


def _record(manager: CaptureManager) -> tuple[list[Screenshot], list[str]]:
    shots: list[Screenshot] = []
    errors: list[str] = []
    manager.captured.connect(shots.append)
    manager.failed.connect(errors.append)
    return shots, errors


def _image(width: int = 2, height: int = 2) -> QImage:
    return QImage(width, height, QImage.Format.Format_RGB32)


def _screen(name: str = "DP-1") -> MagicMock:
    screen = MagicMock()
    screen.name.return_value = name
    screen.geometry.return_value = QRect(0, 0, 2, 2)
    screen.grabWindow.return_value.toImage.return_value = _image()
    return screen


class WithNativeFramesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.laptop = Monitor(0, "eDP-1", QRect(0, 360, 1536, 864))
        self.external = Monitor(1, "HDMI-1", QRect(1536, 0, 2560, 1440))
        self.baseline = Screenshot.from_stitched(
            _image(5120, 1800), (self.laptop, self.external)
        )

    def test_matching_frame_replaces_the_blurry_image(self) -> None:
        frame = Frame((1536, 0), (2560, 1440), _image(2560, 1440))

        result = with_native_frames(self.baseline, [frame])

        self.assertEqual(result.monitor_image(self.external).size(), QSize(2560, 1440))
        self.assertEqual(
            result.monitor_image(self.laptop), self.baseline.monitor_image(self.laptop)
        )

    def test_monitor_without_a_frame_keeps_the_portal_image(self) -> None:
        result = with_native_frames(self.baseline, [])

        self.assertEqual(result.monitor_image(self.external).size(), QSize(3200, 1800))

    def test_frame_in_the_wrong_place_is_ignored(self) -> None:
        frame = Frame((0, 0), (2560, 1440), _image(2560, 1440))

        result = with_native_frames(self.baseline, [frame])

        self.assertEqual(result.monitor_image(self.external).size(), QSize(3200, 1800))


class CaptureManagerTest(unittest.TestCase):
    def test_x11_grabs_every_screen_without_the_portal(self) -> None:
        manager = CaptureManager()
        shots, errors = _record(manager)
        first, second = _screen("DP-1"), _screen("DP-2")

        with (
            patch("glance.capture.manager.PortalScreenshot") as portal_class,
            patch("glance.capture.manager.QGuiApplication") as gui,
        ):
            gui.platformName.return_value = "xcb"
            gui.screens.return_value = [first, second]
            manager.capture_screen()

        self.assertEqual(errors, [])
        self.assertEqual([m.name for m in shots[0].monitors], ["DP-1", "DP-2"])
        portal_class.assert_not_called()

    def test_x11_falls_back_to_the_portal_when_a_grab_is_blank(self) -> None:
        manager = CaptureManager()
        shots, errors = _record(manager)
        screen = _screen()
        screen.grabWindow.return_value.toImage.return_value = QImage()

        with (
            patch("glance.capture.manager.PortalScreenshot") as portal_class,
            patch("glance.capture.manager.QGuiApplication") as gui,
            patch("glance.capture.manager.current_monitors") as monitors,
        ):
            gui.platformName.return_value = "xcb"
            gui.screens.return_value = [screen]
            monitors.return_value = (Monitor(0, "DP-1", QRect(0, 0, 2, 2)),)
            portal = portal_class.return_value
            portal.start.return_value = True
            manager.capture_screen()
            portal.captured.connect.call_args.args[0](_image())

        self.assertEqual(errors, [])
        self.assertEqual(len(shots), 1)

    def test_wayland_portal_failure_is_reported_without_screencast(self) -> None:
        manager = CaptureManager()
        shots, errors = _record(manager)

        with (
            patch("glance.capture.manager.PortalScreenshot") as portal_class,
            patch("glance.capture.manager.ScreenCastWorker") as worker_class,
            patch("glance.capture.manager.QGuiApplication") as gui,
            patch("glance.capture.manager.soft_monitors", return_value=()),
        ):
            gui.platformName.return_value = "wayland"
            portal = portal_class.return_value
            portal.start.return_value = True
            manager.capture_screen()
            portal.failed.connect.call_args.args[0]("Screenshot was cancelled.")

        self.assertEqual(errors, ["Screenshot was cancelled."])
        self.assertEqual(shots, [])
        worker_class.assert_not_called()

    def _wayland(
        self, soft: tuple[Monitor, ...]
    ) -> tuple[CaptureManager, list[Screenshot], list[str], MagicMock, MagicMock]:
        manager = CaptureManager()
        shots, errors = _record(manager)
        monitor = Monitor(0, "DP-1", QRect(0, 0, 2, 2))
        patches = (
            patch("glance.capture.manager.PortalScreenshot"),
            patch("glance.capture.manager.ScreenCastWorker"),
            patch("glance.capture.manager.QGuiApplication"),
            patch("glance.capture.manager.current_monitors", return_value=(monitor,)),
            patch("glance.capture.manager.soft_monitors", return_value=soft),
        )
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        mocks[2].platformName.return_value = "wayland"
        mocks[0].return_value.start.return_value = True
        manager.capture_screen()
        return manager, shots, errors, mocks[0], mocks[1]

    def test_wayland_takes_native_frames_before_the_portal_screenshot(self) -> None:
        monitor = Monitor(0, "DP-1", QRect(0, 0, 2, 2))
        native = _image(4, 4)
        _, shots, errors, portal_class, worker_class = self._wayland((monitor,))

        # GNOME flashes the screen during the portal screenshot, which would
        # wash out any frame taken then.
        portal_class.assert_not_called()
        worker = worker_class.return_value
        worker.grabbed.connect.call_args.args[0]([Frame((0, 0), (2, 2), native)])
        portal = portal_class.return_value
        portal.captured.connect.call_args.args[0](_image())

        self.assertEqual(errors, [])
        self.assertEqual(shots[0].monitor_image(monitor), native)

    def test_wayland_skips_screencast_when_no_monitor_is_soft(self) -> None:
        _, shots, _, portal_class, worker_class = self._wayland(())

        portal_class.return_value.captured.connect.call_args.args[0](_image())

        worker_class.assert_not_called()
        self.assertEqual(len(shots), 1)

    def test_wayland_keeps_the_portal_image_when_screencast_fails(self) -> None:
        monitor = Monitor(0, "DP-1", QRect(0, 0, 2, 2))
        _, shots, errors, portal_class, worker_class = self._wayland((monitor,))

        with self.assertLogs("glance.capture.manager", "WARNING"):
            worker_class.return_value.failed.connect.call_args.args[0]("no portal")
        portal_class.return_value.captured.connect.call_args.args[0](_image())

        self.assertEqual(errors, [])
        self.assertEqual(len(shots), 1)

    def test_fails_when_no_portal_can_be_reached(self) -> None:
        manager = CaptureManager()
        shots, errors = _record(manager)

        with (
            patch("glance.capture.manager.PortalScreenshot") as portal_class,
            patch("glance.capture.manager.QGuiApplication") as gui,
            patch("glance.capture.manager.soft_monitors", return_value=()),
        ):
            gui.platformName.return_value = "wayland"
            portal_class.return_value.start.return_value = False
            manager.capture_screen()

        self.assertEqual(shots, [])
        self.assertEqual(len(errors), 1)
