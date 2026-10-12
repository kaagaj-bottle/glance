import unittest

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QImage

from glance.capture.types import Monitor, Screenshot


def _image(width: int, height: int, color: str = "black") -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    return image


class ScreenshotTest(unittest.TestCase):
    def setUp(self) -> None:
        # A real layout: a 1.25x laptop panel beside a 1x external monitor.
        self.laptop = Monitor(0, "eDP-1", QRect(0, 360, 1536, 864))
        self.external = Monitor(1, "HDMI-1", QRect(1536, 0, 2560, 1440))
        self.screenshot = Screenshot(
            (self.laptop, self.external),
            (_image(1920, 1080, "red"), _image(2560, 1440, "blue")),
        )

    def test_desktop_covers_all_monitors(self) -> None:
        self.assertEqual(self.screenshot.desktop, QRect(0, 0, 4096, 1440))

    def test_each_monitor_has_its_own_scale(self) -> None:
        self.assertEqual(self.screenshot.scale(self.laptop), 1.25)
        self.assertEqual(self.screenshot.scale(self.external), 1.0)

    def test_requires_at_least_one_monitor(self) -> None:
        with self.assertRaises(ValueError):
            Screenshot((), ())

    def test_requires_one_image_per_monitor(self) -> None:
        with self.assertRaises(ValueError):
            Screenshot((self.laptop,), ())

    def test_crop_inside_a_monitor_uses_its_native_pixels(self) -> None:
        crop = self.screenshot.crop(QRect(1636, 100, 400, 300))

        self.assertEqual(crop.size(), QSize(400, 300))
        self.assertEqual(crop.pixelColor(0, 0), QColor("blue"))

    def test_crop_on_the_scaled_monitor_is_in_its_pixels(self) -> None:
        crop = self.screenshot.crop(QRect(100, 400, 400, 200))

        self.assertEqual(crop.size(), QSize(500, 250))
        self.assertEqual(crop.pixelColor(0, 0), QColor("red"))

    def test_crop_across_monitors_uses_the_highest_scale(self) -> None:
        crop = self.screenshot.crop(QRect(1436, 400, 200, 100))

        self.assertEqual(crop.size(), QSize(250, 125))
        self.assertEqual(crop.pixelColor(10, 10), QColor("red"))
        self.assertEqual(crop.pixelColor(240, 10), QColor("blue"))
        self.assertEqual(
            self.screenshot.pixel_size(QRect(1436, 400, 200, 100)), crop.size()
        )

    def test_monitor_left_of_the_origin(self) -> None:
        left = Monitor(0, "left", QRect(-1920, 0, 1920, 1080))
        main = Monitor(1, "main", QRect(0, 0, 2560, 1440))
        screenshot = Screenshot((left, main), (_image(1920, 1080), _image(2560, 1440)))

        self.assertEqual(screenshot.desktop, QRect(-1920, 0, 4480, 1440))
        self.assertEqual(
            screenshot.crop(QRect(-100, 0, 100, 50)).size(), QSize(100, 50)
        )


class FromStitchedTest(unittest.TestCase):
    def test_splits_the_portal_image_by_monitor(self) -> None:
        # GNOME's portal returned a 5120x1800 image for this 4096x1440 desktop,
        # upscaling the 1x monitor to 1.25x.
        laptop = Monitor(0, "eDP-1", QRect(0, 360, 1536, 864))
        external = Monitor(1, "HDMI-1", QRect(1536, 0, 2560, 1440))

        screenshot = Screenshot.from_stitched(_image(5120, 1800), (laptop, external))

        self.assertEqual(screenshot.monitor_image(laptop).size(), QSize(1920, 1080))
        self.assertEqual(screenshot.monitor_image(external).size(), QSize(3200, 1800))
