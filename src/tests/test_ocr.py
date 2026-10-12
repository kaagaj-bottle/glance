import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEventLoop, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance.ocr.rapid import RapidOcrEngine, image_to_array  # noqa: E402
from glance.ocr.types import OcrLine, OcrResult  # noqa: E402
from glance.ocr.worker import OcrTask  # noqa: E402


def _app() -> QCoreApplication:
    return QCoreApplication.instance() or QApplication([])


def _text_image(text: str) -> QImage:
    image = QImage(600, 120, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(QColor("black"))
    painter.setFont(QFont("DejaVu Sans", 32))
    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return image


class OcrResultTest(unittest.TestCase):
    def test_text_joins_lines_and_trims_them(self) -> None:
        box = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        result = OcrResult((OcrLine("Hello ", box, 0.9), OcrLine("world", box, 0.9)))
        self.assertEqual(result.text, "Hello\nworld")

    def test_empty_result_has_no_text(self) -> None:
        self.assertEqual(OcrResult(()).text, "")


class ImageToArrayTest(unittest.TestCase):
    def test_pixels_are_rgb_and_unpadded(self) -> None:
        image = QImage(3, 2, QImage.Format.Format_RGB32)
        image.fill(QColor(10, 20, 30))
        array = image_to_array(image)
        self.assertEqual(array.shape, (2, 3, 3))
        self.assertEqual(array[1, 2].tolist(), [10, 20, 30])


class RapidOcrEngineTest(unittest.TestCase):
    def test_reads_rendered_text(self) -> None:
        _app()
        result = RapidOcrEngine().recognize(_text_image("Hello Glance"))
        self.assertEqual(result.text.replace("\n", " ").lower(), "hello glance")

    def test_blank_image_has_no_lines(self) -> None:
        _app()
        blank = QImage(200, 100, QImage.Format.Format_RGB32)
        blank.fill(QColor("white"))
        self.assertEqual(RapidOcrEngine().recognize(blank).lines, ())

    def test_null_image_has_no_lines(self) -> None:
        self.assertEqual(RapidOcrEngine().recognize(QImage()).lines, ())


class _FakeEngine:
    def __init__(self, result: OcrResult | Exception) -> None:
        self._result = result

    def recognize(self, image: QImage) -> OcrResult:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _run(task: OcrTask) -> tuple[list[object], list[str]]:
    _app()
    done: list[object] = []
    failed: list[str] = []
    loop = QEventLoop()

    def on_done(result: object) -> None:
        done.append(result)
        loop.quit()

    def on_failed(message: str) -> None:
        failed.append(message)
        loop.quit()

    task.done.connect(on_done)
    task.failed.connect(on_failed)
    QTimer.singleShot(10000, loop.quit)
    task.start()
    loop.exec()
    return done, failed


class OcrTaskTest(unittest.TestCase):
    def test_emits_done_with_the_result(self) -> None:
        result = OcrResult(())
        done, failed = _run(OcrTask(_FakeEngine(result), QImage()))
        self.assertEqual(done, [result])
        self.assertEqual(failed, [])

    def test_emits_failed_when_the_engine_raises(self) -> None:
        done, failed = _run(OcrTask(_FakeEngine(RuntimeError("boom")), QImage()))
        self.assertEqual(done, [])
        self.assertEqual(failed, ["boom"])


if __name__ == "__main__":
    unittest.main()
