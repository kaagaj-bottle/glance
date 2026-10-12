"""Takes a real screenshot and saves the result so it can be inspected.

Needs a desktop session with a screenshot portal, so it only runs when
GLANCE_LIVE_TESTS=1 (see `task run-test-live`). Output goes to `test-output/`.
"""

import os
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication, QImage

from glance.capture.manager import CaptureManager
from glance.capture.types import Screenshot

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "test-output"
TIMEOUT_MS = 30_000


def _capture() -> tuple[Screenshot | None, str | None]:
    manager = CaptureManager()
    loop = QEventLoop()
    result: list[Screenshot] = []
    errors: list[str] = []

    def done(screenshot: Screenshot) -> None:
        result.append(screenshot)
        loop.quit()

    def failed(message: str) -> None:
        errors.append(message)
        loop.quit()

    manager.captured.connect(done)
    manager.failed.connect(failed)
    QTimer.singleShot(0, manager.capture_screen)
    QTimer.singleShot(TIMEOUT_MS, loop.quit)
    loop.exec()
    return (result[0] if result else None), (errors[0] if errors else None)


def _distinct_colors(image: QImage) -> int:
    """Count distinct colours on a coarse grid; a blank capture has just one."""
    colors: set[int] = set()
    for x in range(0, image.width(), max(1, image.width() // 40)):
        for y in range(0, image.height(), max(1, image.height() // 40)):
            colors.add(image.pixel(x, y))
    return len(colors)


@unittest.skipUnless(
    os.environ.get("GLANCE_LIVE_TESTS") == "1", "Set GLANCE_LIVE_TESTS=1."
)
class LiveScreenshotTest(unittest.TestCase):
    def test_captures_and_saves_every_monitor(self) -> None:
        existing = QCoreApplication.instance()
        if existing is not None and not isinstance(existing, QGuiApplication):
            self.skipTest("A non-GUI Qt app already exists; run this test on its own.")
        _app = existing or QGuiApplication([])

        screenshot, error = _capture()

        self.assertIsNone(error)
        assert screenshot is not None, "Timed out waiting for the portal."
        self.assertFalse(screenshot.image.isNull())

        OUTPUT_DIR.mkdir(exist_ok=True)
        full_path = OUTPUT_DIR / "desktop.png"
        self.assertTrue(screenshot.image.save(str(full_path)))
        print(f"\n{full_path}  {screenshot.image.width()}x{screenshot.image.height()}")

        for monitor in screenshot.monitors:
            crop = screenshot.monitor_image(monitor)
            expected = screenshot.image_rect(monitor.geometry)
            path = OUTPUT_DIR / f"monitor-{monitor.index}-{monitor.name}.png"
            self.assertTrue(crop.save(str(path)))
            print(f"{path}  {crop.width()}x{crop.height()}")

            self.assertEqual(
                (crop.width(), crop.height()), (expected.width(), expected.height())
            )
            self.assertGreater(
                _distinct_colors(crop), 1, f"{monitor.name} looks blank."
            )
