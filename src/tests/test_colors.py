import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402

from glance.colors import palette, pixel_hex  # noqa: E402


def _image(*bands: tuple[str, int]) -> QImage:
    """Vertical bands of color, each the given number of pixels wide."""
    image = QImage(sum(width for _, width in bands), 20, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    left = 0
    for color, width in bands:
        painter.fillRect(left, 0, width, 20, QColor(color))
        left += width
    painter.end()
    return image


class PixelTest(unittest.TestCase):
    def test_a_pixel_is_given_as_upper_case_hex(self) -> None:
        image = _image(("#10abef", 5))

        self.assertEqual(pixel_hex(image, 2, 3), "#10ABEF")

    def test_outside_the_image_there_is_no_color(self) -> None:
        image = _image(("red", 5))

        self.assertIsNone(pixel_hex(image, -1, 0))
        self.assertIsNone(pixel_hex(image, 5, 0))
        self.assertIsNone(pixel_hex(image, 0, 20))


class PaletteTest(unittest.TestCase):
    def test_the_main_colors_come_back_most_common_first(self) -> None:
        image = _image(("#ff0000", 60), ("#00ff00", 30), ("#0000ff", 10))

        swatches = palette(image)

        self.assertEqual([s.hex for s in swatches], ["#FF0000", "#00FF00", "#0000FF"])
        self.assertAlmostEqual(swatches[0].share, 0.6, delta=0.05)

    def test_one_flat_color_is_one_swatch(self) -> None:
        [swatch] = palette(_image(("#336699", 40)))

        self.assertEqual((swatch.hex, round(swatch.share, 2)), ("#336699", 1.0))

    def test_near_identical_colors_are_merged(self) -> None:
        swatches = palette(_image(("#ff0000", 50), ("#fe0101", 50)))

        self.assertEqual(len(swatches), 1)

    def test_the_palette_is_no_larger_than_asked(self) -> None:
        bands = tuple(
            (QColor.fromHsv(h, 255, 255).name(), 10) for h in range(0, 360, 30)
        )

        self.assertLessEqual(len(palette(_image(*bands), 4)), 4)

    def test_a_null_image_has_no_palette(self) -> None:
        self.assertEqual(palette(QImage()), [])


if __name__ == "__main__":
    unittest.main()
