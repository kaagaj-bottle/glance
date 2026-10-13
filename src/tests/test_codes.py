import os
import unittest
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import zxingcpp  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from glance.codes import Code, read_codes  # noqa: E402
from glance.smart import Kind  # noqa: E402


def _render(kind: zxingcpp.BarcodeFormat, text: str, scale: int = 6) -> QImage:
    create: Any = zxingcpp.create_barcode  # pyright: ignore
    pixels = np.ascontiguousarray(
        zxingcpp.write_barcode_to_image(create(text, kind), scale)
    )
    height, width = pixels.shape[:2]
    image = QImage(pixels.data, width, height, width, QImage.Format.Format_Grayscale8)
    return image.copy()


def _code(text: str, format: str = "QR Code") -> Code:
    return Code(format, text, ())


class ReadCodesTest(unittest.TestCase):
    def test_a_qr_code_is_read_with_its_corners(self) -> None:
        [code] = read_codes(_render(zxingcpp.BarcodeFormat.QRCode, "hello"))

        self.assertEqual((code.format, code.text), ("QR Code", "hello"))
        xs = [x for x, _ in code.box]
        self.assertEqual(len(code.box), 4)
        self.assertTrue(0 <= min(xs) < max(xs) <= 300)

    def test_a_barcode_is_read(self) -> None:
        image = _render(zxingcpp.BarcodeFormat.EAN13, "5901234123457", 4)

        [code] = read_codes(image)

        self.assertEqual((code.format, code.text), ("EAN-13", "5901234123457"))
        self.assertTrue(code.searchable)

    def test_an_image_without_a_code_gives_nothing(self) -> None:
        blank = QImage(100, 100, QImage.Format.Format_RGB32)
        blank.fill(0xFFFFFF)

        self.assertEqual(read_codes(blank), [])
        self.assertEqual(read_codes(QImage()), [])


class OpenTest(unittest.TestCase):
    def test_a_web_link_opens_as_it_is(self) -> None:
        entity = _code("https://example.com/a?b=1.").entity

        assert entity is not None
        self.assertEqual(entity.kind, Kind.LINK)
        self.assertEqual(entity.url, "https://example.com/a?b=1.")

    def test_a_mailto_link_opens_as_an_email(self) -> None:
        entity = _code("mailto:jane@example.com?subject=Hi").entity

        assert entity is not None
        self.assertEqual(entity.kind, Kind.EMAIL)
        self.assertEqual(entity.text, "jane@example.com")
        self.assertEqual(entity.url, "mailto:jane@example.com?subject=Hi")

    def test_anything_else_can_only_be_copied(self) -> None:
        for text in (
            "javascript:alert(1)",
            "file:///etc/passwd",
            "tel:+15551234",
            "WIFI:T:WPA;S:home;P:secret;;",
            "ftp://example.com",
            "https://",
            "see https://example.com",
            "https://example.com\nhttps://evil.example",
            "just text",
            "mailto:nobody",
        ):
            with self.subTest(text=text):
                self.assertIsNone(_code(text).entity)

    def test_only_retail_codes_are_searchable(self) -> None:
        self.assertFalse(_code("123").searchable)
        self.assertTrue(_code("9780306406157", "ISBN").searchable)

    def test_labels_are_one_short_line(self) -> None:
        label = _code("a\n" + "b" * 80).label

        self.assertNotIn("\n", label)
        self.assertEqual(len(label), 40)


if __name__ == "__main__":
    unittest.main()
