import unittest

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from glance.capture.types import Monitor, Screenshot


def _image(width: int, height: int) -> QImage:
    return QImage(width, height, QImage.Format.Format_RGB32)


class ScreenshotTest(unittest.TestCase):
    def setUp(self) -> None:
        # A real layout: a 1.25x laptop panel beside a 1x external monitor.
        # GNOME's portal returned a 5120x1800 image for this 4096x1440 desktop.
        self.laptop = Monitor(0, "eDP-1", QRect(0, 360, 1536, 864))
        self.external = Monitor(1, "HDMI-1", QRect(1536, 0, 2560, 1440))
        self.screenshot = Screenshot(_image(5120, 1800), (self.laptop, self.external))

    def test_desktop_covers_all_monitors(self) -> None:
        self.assertEqual(self.screenshot.desktop, QRect(0, 0, 4096, 1440))

    def test_scale_is_derived_from_the_image_size(self) -> None:
        self.assertEqual(self.screenshot.scale, 1.25)

    def test_monitor_images_have_the_monitor_size_in_pixels(self) -> None:
        laptop = self.screenshot.monitor_image(self.laptop)
        external = self.screenshot.monitor_image(self.external)

        self.assertEqual((laptop.width(), laptop.height()), (1920, 1080))
        self.assertEqual((external.width(), external.height()), (3200, 1800))

    def test_monitors_tile_the_image_without_gaps(self) -> None:
        laptop = self.screenshot.image_rect(self.laptop.geometry)
        external = self.screenshot.image_rect(self.external.geometry)

        self.assertEqual(laptop, QRect(0, 450, 1920, 1080))
        self.assertEqual(external, QRect(1920, 0, 3200, 1800))

    def test_monitor_left_of_the_origin(self) -> None:
        left = Monitor(0, "left", QRect(-1920, 0, 1920, 1080))
        main = Monitor(1, "main", QRect(0, 0, 2560, 1440))
        screenshot = Screenshot(_image(4480, 1440), (left, main))

        self.assertEqual(screenshot.image_rect(left.geometry), QRect(0, 0, 1920, 1080))
        self.assertEqual(
            screenshot.image_rect(main.geometry), QRect(1920, 0, 2560, 1440)
        )

    def test_requires_at_least_one_monitor(self) -> None:
        with self.assertRaises(ValueError):
            Screenshot(_image(10, 10), ())
