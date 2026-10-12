import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance.capture.types import Monitor, Screenshot  # noqa: E402
from glance.ui.overlay import OverlayWindow, ScreenshotOverlay  # noqa: E402
from glance.ui.panel import CaptureMode  # noqa: E402

LEFT = Monitor(0, "A", QRect(0, 0, 400, 300))
RIGHT = Monitor(1, "B", QRect(400, 0, 400, 300))


def _overlay() -> tuple[ScreenshotOverlay, list[QImage], list[bool]]:
    images = tuple(
        QImage(monitor.geometry.size(), QImage.Format.Format_RGB32)
        for monitor in (LEFT, RIGHT)
    )
    overlay = ScreenshotOverlay(Screenshot((LEFT, RIGHT), images))
    captured: list[QImage] = []
    cancelled: list[bool] = []
    overlay.captured.connect(captured.append)
    overlay.cancelled.connect(lambda: cancelled.append(True))
    return overlay, captured, cancelled


def _windows(overlay: ScreenshotOverlay) -> list[OverlayWindow]:
    return overlay._windows  # pyright: ignore[reportPrivateUsage]


def _drag(window: OverlayWindow, start: QPoint, end: QPoint) -> None:
    left = Qt.MouseButton.LeftButton
    QTest.mousePress(window, left, pos=start)
    QTest.mouseMove(window, end)
    QTest.mouseRelease(window, left, pos=end)


class OverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_dragging_selects_and_capture_crops_that_area(self) -> None:
        overlay, captured, _ = _overlay()
        left, _ = _windows(overlay)

        _drag(left, QPoint(10, 20), QPoint(110, 90))
        overlay._capture()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(len(captured), 1)
        self.assertEqual((captured[0].width(), captured[0].height()), (100, 70))

    def test_a_drag_can_cross_onto_the_next_monitor(self) -> None:
        overlay, captured, _ = _overlay()
        left, _ = _windows(overlay)

        # The pointer stays with the window where the drag began, so it reports
        # coordinates beyond that window's edge.
        _drag(left, QPoint(300, 50), QPoint(500, 150))
        overlay._capture()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual((captured[0].width(), captured[0].height()), (200, 100))

    def test_a_click_without_a_drag_selects_nothing(self) -> None:
        overlay, captured, _ = _overlay()
        left, _ = _windows(overlay)

        _drag(left, QPoint(10, 10), QPoint(11, 11))
        overlay._capture()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(captured, [])

    def test_the_selection_stays_inside_the_desktop(self) -> None:
        overlay, captured, _ = _overlay()
        _, right = _windows(overlay)

        _drag(right, QPoint(300, 200), QPoint(900, 900))
        overlay._capture()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual((captured[0].width(), captured[0].height()), (100, 100))

    def test_screen_mode_captures_the_clicked_monitor(self) -> None:
        overlay, captured, _ = _overlay()
        _, right = _windows(overlay)

        overlay._set_mode(CaptureMode.SCREEN)  # pyright: ignore[reportPrivateUsage]
        QTest.mouseClick(right, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))

        self.assertEqual((captured[0].width(), captured[0].height()), (400, 300))

    def test_cancel_reports_once_and_never_captures(self) -> None:
        overlay, captured, cancelled = _overlay()

        overlay._cancel()  # pyright: ignore[reportPrivateUsage]
        overlay._cancel()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(cancelled, [True])
        self.assertEqual(captured, [])
