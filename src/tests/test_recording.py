import signal
import subprocess
import sys
import unittest
from pathlib import Path

from PySide6.QtCore import QRect

from glance.capture.recording import Crop, crop_for, pipeline, stop


class CropTest(unittest.TestCase):
    def test_cuts_the_margins_around_the_area(self) -> None:
        monitor = QRect(0, 0, 1000, 800)
        crop = crop_for(QRect(100, 50, 400, 300), monitor, 1.0)
        self.assertEqual(crop, Crop(left=100, top=50, right=500, bottom=450))

    def test_uses_the_frame_scale_and_the_monitor_origin(self) -> None:
        monitor = QRect(1920, 0, 1000, 800)
        crop = crop_for(QRect(2020, 50, 400, 300), monitor, 2.0)
        self.assertEqual(crop, Crop(left=200, top=100, right=1000, bottom=900))

    def test_odd_sizes_and_positions_are_made_even(self) -> None:
        crop = crop_for(QRect(11, 13, 101, 99), QRect(0, 0, 400, 300), 1.0)
        assert crop is not None
        self.assertEqual((crop.left, crop.top), (10, 12))
        self.assertEqual((400 - crop.left - crop.right) % 2, 0)
        self.assertEqual((300 - crop.top - crop.bottom) % 2, 0)

    def test_fractional_scale_keeps_the_area_inside_the_frame(self) -> None:
        monitor = QRect(0, 0, 1536, 864)
        crop = crop_for(QRect(0, 0, 1536, 864), monitor, 1.25)
        assert crop is not None
        self.assertEqual(crop, Crop(0, 0, 0, 0))

    def test_an_area_past_the_monitor_is_clamped(self) -> None:
        crop = crop_for(QRect(-50, 700, 400, 400), QRect(0, 0, 1000, 800), 1.0)
        assert crop is not None
        self.assertEqual(crop, Crop(left=0, top=700, right=650, bottom=0))

    def test_an_area_off_the_monitor_gives_nothing(self) -> None:
        self.assertIsNone(crop_for(QRect(2000, 0, 10, 10), QRect(0, 0, 1000, 800), 1.0))


class PipelineTest(unittest.TestCase):
    def test_records_the_stream_to_webm(self) -> None:
        args = pipeline(7, 42, Path("/tmp/a.webm"), None)
        self.assertEqual(args[:2], ["-e", "-q"])
        self.assertIn("fd=7", args)
        self.assertIn("path=42", args)
        self.assertIn("vp8enc", args)
        self.assertIn("webmmux", args)
        self.assertIn("location=/tmp/a.webm", args)
        self.assertNotIn("videocrop", args)

    def test_crops_when_given_a_crop(self) -> None:
        args = pipeline(7, 42, Path("a.webm"), Crop(2, 4, 6, 8))
        crop = args.index("videocrop")
        self.assertEqual(
            args[crop + 1 : crop + 5], ["left=2", "top=4", "right=6", "bottom=8"]
        )

    def test_steps_are_joined_by_bangs(self) -> None:
        args = pipeline(7, 42, Path("a.webm"), None)
        self.assertEqual(args.count("!"), 6)


def _child(code: str) -> subprocess.Popen[bytes]:
    process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE)
    assert process.stdout is not None
    process.stdout.readline()  # wait until the handler is installed
    return process


HANDLES_SIGINT = (
    "import signal,sys\n"
    "signal.signal(signal.SIGINT, lambda *a: sys.exit(0))\n"
    "print('ready', flush=True)\n"
    "signal.pause()\n"
)
IGNORES_SIGINT = (
    "import signal,time\n"
    "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
    "print('ready', flush=True)\n"
    "time.sleep(60)\n"
)


class StopTest(unittest.TestCase):
    def test_interrupts_so_the_file_can_be_finished(self) -> None:
        process = _child(HANDLES_SIGINT)
        self.assertTrue(stop(process, timeout=5))
        self.assertEqual(process.returncode, 0)

    def test_kills_a_process_that_does_not_end(self) -> None:
        process = _child(IGNORES_SIGINT)
        self.assertFalse(stop(process, timeout=0.3))
        self.assertEqual(process.returncode, -signal.SIGKILL)

    def test_a_process_that_already_ended_is_reported_by_its_status(self) -> None:
        process = subprocess.Popen([sys.executable, "-c", "pass"])
        process.wait()
        self.assertTrue(stop(process))


if __name__ == "__main__":
    unittest.main()
