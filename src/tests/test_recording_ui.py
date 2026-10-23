import contextlib
import io
import os
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402

from glance.app import App  # noqa: E402
from glance.capture.recording import Crop  # noqa: E402
from glance.capture.types import Monitor, Screenshot  # noqa: E402
from glance.ui.guide import dashes, frame_bounds  # noqa: E402
from glance.ui.overlay import ScreenshotOverlay  # noqa: E402
from glance.ui.panel import CaptureMode  # noqa: E402
from glance.ui.recording import RecordingControls, format_elapsed  # noqa: E402

LEFT = Monitor(0, "A", QRect(0, 0, 400, 300))
RIGHT = Monitor(1, "B", QRect(400, 0, 400, 300))


class FormatTest(unittest.TestCase):
    def test_minutes_and_seconds(self) -> None:
        self.assertEqual(format_elapsed(0), "00:00")
        self.assertEqual(format_elapsed(12_900), "00:12")
        self.assertEqual(format_elapsed(125_000), "02:05")

    def test_hours_appear_when_needed(self) -> None:
        self.assertEqual(format_elapsed(3_725_000), "1:02:05")

    def test_a_negative_time_is_zero(self) -> None:
        self.assertEqual(format_elapsed(-5), "00:00")


def _overlay() -> tuple[ScreenshotOverlay, list[tuple[QRect, Monitor]]]:
    images = tuple(
        QImage(monitor.geometry.size(), QImage.Format.Format_RGB32)
        for monitor in (LEFT, RIGHT)
    )
    overlay = ScreenshotOverlay(Screenshot((LEFT, RIGHT), images))
    requests: list[tuple[QRect, Monitor]] = []

    def requested(area: QRect, monitor: Monitor) -> None:
        requests.append((area, monitor))

    overlay.record_requested.connect(requested)
    return overlay, requests


class GuideTest(unittest.TestCase):
    def test_the_dashes_stay_outside_the_area(self) -> None:
        area = QRect(200, 100, 300, 150)
        pieces = dashes(area)
        self.assertTrue(pieces)
        self.assertFalse(any(piece.intersects(area) for piece in pieces))

    def test_the_dashes_fit_the_window_and_leave_gaps(self) -> None:
        area = QRect(200, 100, 300, 150)
        bounds = frame_bounds(area)
        pieces = dashes(area)
        self.assertTrue(all(bounds.contains(piece) for piece in pieces))
        top = sorted(
            (p for p in pieces if p.top() == bounds.top() and p.height() == 3),
            key=QRect.left,
        )
        self.assertGreater(top[1].left(), top[0].right() + 1)

    def test_every_corner_is_marked(self) -> None:
        area = QRect(200, 100, 300, 150)
        bounds = frame_bounds(area)
        pieces = dashes(area)
        for corner in (
            bounds.topLeft(),
            bounds.topRight(),
            bounds.bottomLeft(),
            bounds.bottomRight(),
        ):
            self.assertTrue(any(piece.contains(corner) for piece in pieces))


class ControlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(QApplication, QApplication.instance() or QApplication([]))

    def test_start_shows_the_bar_and_finish_hides_it(self) -> None:
        controls = RecordingControls()
        controls.start()
        self.assertTrue(controls.isVisible())
        controls.finish()
        self.assertFalse(controls.isVisible())

    def test_the_stop_button_asks_the_recorder_to_stop(self) -> None:
        controls = RecordingControls()
        stops: list[bool] = []
        controls.stop_requested.connect(lambda: stops.append(True))
        button = controls.findChild(QToolButton, "stop")
        assert button is not None
        button.click()
        self.assertEqual(stops, [True])

    def test_closing_the_bar_asks_the_recorder_to_stop(self) -> None:
        controls = RecordingControls()
        stops: list[bool] = []
        controls.stop_requested.connect(lambda: stops.append(True))
        controls.start()
        controls.close()
        self.assertEqual(stops, [True])

    def test_finishing_the_bar_does_not_ask_for_another_stop(self) -> None:
        controls = RecordingControls()
        stops: list[bool] = []
        controls.stop_requested.connect(lambda: stops.append(True))
        controls.start()
        controls.finish()
        self.assertEqual(stops, [])

    def test_escape_stops_the_recording_and_does_not_cancel_the_overlay(self) -> None:
        overlay, requests = _overlay()
        cancelled: list[bool] = []
        overlay.cancelled.connect(lambda: cancelled.append(True))
        overlay._selection = QRect(50, 50, 100, 80)  # pyright: ignore[reportPrivateUsage]
        overlay._record()  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(len(requests), 1)

        controls = RecordingControls()
        stops: list[bool] = []
        controls.stop_requested.connect(lambda: stops.append(True))
        controls.start()
        self.addCleanup(controls.finish)
        controls.activateWindow()
        QTest.qWaitForWindowActive(controls)
        QTest.keyClick(controls, Qt.Key.Key_Escape)
        self.assertEqual(stops, [True])
        self.assertEqual(cancelled, [])


class OverlayRecordTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(QApplication, QApplication.instance() or QApplication([]))

    def test_nothing_is_recorded_without_a_selection(self) -> None:
        overlay, requests = _overlay()
        overlay._record()  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(requests, [])

    def test_a_selection_is_recorded_on_its_monitor(self) -> None:
        overlay, requests = _overlay()
        overlay._selection = QRect(50, 50, 100, 80)  # pyright: ignore[reportPrivateUsage]
        overlay._record()  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(requests, [(QRect(50, 50, 100, 80), LEFT)])

    def test_a_selection_across_monitors_is_cut_to_the_larger_part(self) -> None:
        overlay, requests = _overlay()
        overlay._selection = QRect(350, 50, 200, 100)  # pyright: ignore[reportPrivateUsage]
        overlay._record()  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(requests, [(QRect(400, 50, 150, 100), RIGHT)])

    def test_screen_mode_records_the_whole_monitor(self) -> None:
        overlay, requests = _overlay()
        overlay._set_mode(CaptureMode.SCREEN)  # pyright: ignore[reportPrivateUsage]
        overlay._hovered = RIGHT  # pyright: ignore[reportPrivateUsage]
        overlay._record()  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(requests, [(RIGHT.geometry, RIGHT)])


class AppRecordTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(QApplication, QApplication.instance() or QApplication([]))

    def _app(self) -> App:
        glance = App(self.app)
        glance._app = MagicMock()  # pyright: ignore[reportPrivateUsage]
        images = tuple(
            QImage(monitor.geometry.size(), QImage.Format.Format_RGB32)
            for monitor in (LEFT, RIGHT)
        )
        glance._screenshot = Screenshot((LEFT, RIGHT), images)  # pyright: ignore[reportPrivateUsage]
        return glance

    def _record(self, glance: App, area: QRect, monitor: Monitor) -> MagicMock:
        with (
            patch("glance.app.Recorder") as recorder,
            patch("glance.app.RecordingControls"),
            patch("glance.app.QTimer"),
        ):
            glance._record(area, monitor)  # pyright: ignore[reportPrivateUsage]
        return recorder

    def test_a_whole_monitor_is_recorded_without_a_crop(self) -> None:
        recorder = self._record(self._app(), RIGHT.geometry, RIGHT)
        _, place, crop, _ = recorder.call_args.args
        self.assertEqual(place, ((400, 0), (400, 300)))
        self.assertIsNone(crop)

    def test_a_selection_is_cropped_to_its_monitor_pixels(self) -> None:
        recorder = self._record(self._app(), QRect(450, 20, 100, 60), RIGHT)
        crop = recorder.call_args.args[2]
        self.assertEqual(crop, Crop(left=50, top=20, right=250, bottom=220))

    def test_a_selection_gets_a_frame_and_a_whole_monitor_does_not(self) -> None:
        for area, framed in ((QRect(450, 20, 100, 60), True), (RIGHT.geometry, False)):
            glance = self._app()
            with patch("glance.app.RecordingGuide") as guide:
                self._record(glance, area, RIGHT)
            self.assertEqual(guide.called, framed)

    def test_the_frame_is_removed_when_the_recording_ends(self) -> None:
        glance = self._app()
        guide = MagicMock()
        glance._guide = guide  # pyright: ignore[reportPrivateUsage]
        glance._recorder = MagicMock()  # pyright: ignore[reportPrivateUsage]
        with patch("glance.app.notify"), contextlib.redirect_stdout(io.StringIO()):
            glance._recorded(Path("a.webm"))  # pyright: ignore[reportPrivateUsage]
        guide.stop.assert_called_once()

    def test_the_app_waits_for_the_recorder_before_quitting(self) -> None:
        glance = self._app()
        order: list[str] = []
        recorder = MagicMock()
        recorder.wait.side_effect = lambda: order.append("wait")
        glance._recorder = recorder  # pyright: ignore[reportPrivateUsage]
        quit_app = MagicMock(side_effect=lambda: order.append("quit"))
        glance._app = MagicMock(quit=quit_app)  # pyright: ignore[reportPrivateUsage]
        with patch("glance.app.notify"), contextlib.redirect_stdout(io.StringIO()):
            glance._recorded(Path("a.webm"))  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(order, ["wait", "quit"])

    def test_the_overlays_memory_is_released(self) -> None:
        glance = self._app()
        self._record(glance, RIGHT.geometry, RIGHT)
        self.assertIsNone(glance._screenshot)  # pyright: ignore[reportPrivateUsage]


if __name__ == "__main__":
    unittest.main()
