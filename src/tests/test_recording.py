import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QRect

from glance.capture.recording import Crop, Recorder, crop_for, pipeline, stop
from glance.capture.screencast import ScreenCastError


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
        self.assertEqual(args[-2:], ["filesink", 'location="/tmp/a.webm"'])
        self.assertNotIn("videocrop", args)

    def test_a_path_with_spaces_is_quoted_for_gstreamer(self) -> None:
        path = Path("/home/me/Videos/Screencast From 2026-10-23 14-45-10.webm")
        args = pipeline(7, 42, path, None)
        self.assertEqual(args[-1], f'location="{path}"')

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
    process.stdout.close()
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


PLACE = ((0, 0), (1000, 800))


def _session(place: object = PLACE) -> MagicMock:
    session = MagicMock()
    session.watching.return_value.__enter__.return_value = MagicMock(return_value=False)
    session.streams = [
        (42, {"position": ("(ii)", place[0]), "size": ("(ii)", place[1])})  # type: ignore[index]
    ]
    return session


class RecorderTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.output = Path(folder.name) / "out.webm"
        self.events: list[str] = []

    def _recorder(self) -> Recorder:
        recorder = Recorder(None, PLACE, None, self.output)
        recorder.running.connect(lambda: self.events.append("running"))

        def done(path: Path) -> None:
            self.events.append(f"done {path}")

        def failed(message: str) -> None:
            self.events.append(f"failed {message}")

        recorder.finished_with.connect(done)
        recorder.failed.connect(failed)
        return recorder

    def test_records_until_stopped_and_closes_the_session(self) -> None:
        session = _session()
        process = MagicMock()
        process.poll.return_value = None
        recorder = self._recorder()
        recorder.request_stop()

        def finish(_: object) -> bool:
            self.output.write_bytes(b"webm")
            return True

        with (
            patch("glance.capture.recording.open_session", return_value=session),
            patch("glance.capture.recording.subprocess.Popen", return_value=process),
            patch("glance.capture.recording.stop", side_effect=finish) as stopped,
        ):
            recorder.run()
        stopped.assert_called_once_with(process)
        session.close.assert_called_once()
        self.assertEqual(self.events, ["running", f"done {self.output}"])

    def test_the_portal_closing_the_session_stops_the_recording(self) -> None:
        session = _session()
        session.watching.return_value.__enter__.return_value = MagicMock(
            return_value=True
        )
        process = MagicMock()
        process.poll.return_value = None

        def finish(_: object) -> bool:
            self.output.write_bytes(b"webm")
            return True

        with (
            patch("glance.capture.recording.open_session", return_value=session),
            patch("glance.capture.recording.subprocess.Popen", return_value=process),
            patch("glance.capture.recording.stop", side_effect=finish) as stopped,
        ):
            self._recorder().run()
        stopped.assert_called_once_with(process)
        self.assertEqual(self.events, ["running", f"done {self.output}"])

    def test_an_error_after_the_portal_closed_the_session_is_still_a_recording(
        self,
    ) -> None:
        session = _session()
        session.watching.return_value.__enter__.return_value = MagicMock(
            return_value=True
        )
        process = MagicMock()
        process.poll.return_value = 1
        self.output.write_bytes(b"webm")
        with (
            patch("glance.capture.recording.open_session", return_value=session),
            patch("glance.capture.recording.subprocess.Popen", return_value=process),
            patch("glance.capture.recording.stop", return_value=False),
        ):
            self._recorder().run()
        self.assertEqual(self.events, ["running", f"done {self.output}"])

    def test_an_error_long_after_the_start_keeps_the_finished_file(self) -> None:
        session = _session()
        process = MagicMock()
        process.poll.return_value = 1
        self.output.write_bytes(b"webm")
        with (
            patch("glance.capture.recording.open_session", return_value=session),
            patch("glance.capture.recording.subprocess.Popen", return_value=process),
            patch("glance.capture.recording.stop", return_value=False),
            patch("glance.capture.recording.time.monotonic", side_effect=[0.0, 30.0]),
        ):
            self._recorder().run()
        self.assertEqual(self.events, ["running", f"done {self.output}"])

    def test_the_pipeline_ending_by_itself_finishes_the_recording(self) -> None:
        session = _session()
        process = MagicMock()
        process.poll.return_value = 0
        self.output.write_bytes(b"webm")
        with (
            patch("glance.capture.recording.open_session", return_value=session),
            patch("glance.capture.recording.subprocess.Popen", return_value=process),
            patch("glance.capture.recording.stop", return_value=True),
        ):
            self._recorder().run()
        self.assertEqual(self.events, ["running", f"done {self.output}"])

    def test_a_pipeline_that_fails_without_a_file_is_an_error(self) -> None:
        session = _session()
        process = MagicMock()
        process.poll.return_value = 1
        with (
            patch("glance.capture.recording.open_session", return_value=session),
            patch("glance.capture.recording.subprocess.Popen", return_value=process),
            patch("glance.capture.recording.stop", return_value=False),
        ):
            self._recorder().run()
        self.assertEqual(self.events, ["running", "failed Recording failed."])
        session.close.assert_called_once()

    def test_a_nonzero_exit_with_a_file_is_still_an_error(self) -> None:
        session = _session()
        process = MagicMock()
        process.poll.return_value = 1
        self.output.write_bytes(b"partial")
        with (
            patch("glance.capture.recording.open_session", return_value=session),
            patch("glance.capture.recording.subprocess.Popen", return_value=process),
            patch("glance.capture.recording.stop", return_value=False),
        ):
            self._recorder().run()
        self.assertEqual(self.events, ["running", "failed Recording failed."])

    def test_an_empty_file_is_an_error_and_is_removed(self) -> None:
        session = _session()
        process = MagicMock()
        process.poll.return_value = 0
        self.output.write_bytes(b"")
        with (
            patch("glance.capture.recording.open_session", return_value=session),
            patch("glance.capture.recording.subprocess.Popen", return_value=process),
            patch("glance.capture.recording.stop", return_value=True),
        ):
            self._recorder().run()
        self.assertEqual(self.events, ["running", "failed Recording failed."])
        self.assertFalse(self.output.exists())

    def test_a_monitor_the_portal_did_not_share_is_an_error(self) -> None:
        session = _session(((5000, 0), (10, 10)))
        with patch("glance.capture.recording.open_session", return_value=session):
            self._recorder().run()
        self.assertEqual(self.events, ["failed The portal did not share that monitor."])
        session.close.assert_called_once()

    def test_a_refused_share_is_reported(self) -> None:
        with patch(
            "glance.capture.recording.open_session",
            side_effect=ScreenCastError("The screen share was cancelled."),
        ):
            self._recorder().run()
        self.assertEqual(self.events, ["failed The screen share was cancelled."])


if __name__ == "__main__":
    unittest.main()
