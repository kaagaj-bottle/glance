import os
import unittest
from typing import cast
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402

from glance.app import App  # noqa: E402
from glance.capture.recording import Crop  # noqa: E402
from glance.capture.types import Monitor, Screenshot  # noqa: E402
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

    def test_the_overlays_memory_is_released(self) -> None:
        glance = self._app()
        self._record(glance, RIGHT.geometry, RIGHT)
        self.assertIsNone(glance._screenshot)  # pyright: ignore[reportPrivateUsage]


if __name__ == "__main__":
    unittest.main()
