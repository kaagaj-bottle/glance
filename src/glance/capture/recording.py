"""Building and stopping the GStreamer pipeline that records a monitor to WebM.

The recorder runs `gst-launch-1.0` as a child process, as the screenshot path does.
The pipeline is only finished properly when the process gets an end-of-stream, so a
recording is stopped with SIGINT (`gst-launch-1.0 -e`) and killed only as a last resort.
"""

import signal
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRect, QThread, Signal

from glance.capture.screencast import (
    CURSOR_EMBEDDED,
    Place,
    ScreenCastError,
    open_session,
)

FRAMERATE = 30
# A paused desktop sends no frames, so the last one is repeated to keep the
# video moving at a steady rate.
KEEPALIVE_MS = 100
STOP_TIMEOUT = 10.0
POLL_SECONDS = 0.2


@dataclass(frozen=True, slots=True)
class Crop:
    """How many pixels to cut from each edge of a monitor's frame."""

    left: int
    top: int
    right: int
    bottom: int


def _even(value: int) -> int:
    return value - value % 2


def crop_for(logical: QRect, monitor: QRect, scale: float) -> Crop | None:
    """The pixels to cut so only `logical` is left of a monitor's frame.

    `scale` is the frame's pixels per logical unit, which Qt's own pixel ratio
    cannot give (it rounds fractional scales). The result is clamped to the
    monitor and made even in position and size, which the encoder needs. None
    if nothing of the monitor is left.
    """
    area = logical.intersected(monitor)
    if area.isEmpty():
        return None
    width = round(monitor.width() * scale)
    height = round(monitor.height() * scale)
    left = _even(round((area.left() - monitor.left()) * scale))
    top = _even(round((area.top() - monitor.top()) * scale))
    kept_width = _even(min(round(area.width() * scale), width - left))
    kept_height = _even(min(round(area.height() * scale), height - top))
    if kept_width <= 0 or kept_height <= 0:
        return None
    return Crop(left, top, width - left - kept_width, height - top - kept_height)


def pipeline(fd: int, node: int, output: Path, crop: Crop | None) -> list[str]:
    """The `gst-launch-1.0` arguments that record one PipeWire stream to a WebM file."""
    steps = [f"pipewiresrc fd={fd} path={node} keepalive-time={KEEPALIVE_MS}"]
    steps.append("videoconvert")
    if crop is not None:
        steps.append(
            f"videocrop left={crop.left} top={crop.top} "
            f"right={crop.right} bottom={crop.bottom}"
        )
    steps += [
        "videorate",
        f"video/x-raw,framerate={FRAMERATE}/1",
        "vp8enc deadline=1 cpu-used=4 threads=4 keyframe-max-dist=60",
        "webmmux",
        f"filesink location={output}",
    ]
    return ["-e", "-q", *" ! ".join(steps).split()]


def stop(process: subprocess.Popen[bytes], timeout: float = STOP_TIMEOUT) -> bool:
    """End a recording so the file is finished. False if it had to be killed.

    SIGINT makes `gst-launch-1.0 -e` send an end-of-stream and wait for the
    muxer to write its index. A killed muxer leaves a file that may not play.
    """
    if process.poll() is not None:
        return process.returncode == 0
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        return False
    return process.returncode == 0


class RecordingError(Exception):
    """The recording could not be made."""


class Recorder(QThread):
    """Records one monitor to a file until `request_stop` is called.

    The portal session has to stay open for the whole recording, so everything
    runs on this thread. `running` is sent once the pipeline is running, then
    exactly one of `finished` (with the path) or `failed`.
    """

    running = Signal()
    finished_with = Signal(Path)
    failed = Signal(str)

    def __init__(
        self,
        token_file: Path | None,
        place: Place,
        crop: Crop | None,
        output: Path,
    ) -> None:
        super().__init__()
        self._token_file = token_file
        self._place = place
        self._crop = crop
        self._output = output
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            self._record()
        except (ScreenCastError, RecordingError) as error:
            self.failed.emit(str(error))
        else:
            self.finished_with.emit(self._output)

    def _record(self) -> None:
        session = open_session(self._token_file, CURSOR_EMBEDDED)
        try:
            node = next(
                (
                    node
                    for node, properties in session.streams
                    if (
                        tuple(properties["position"][1]),
                        tuple(properties["size"][1]),
                    )
                    == self._place
                ),
                None,
            )
            if node is None:
                raise RecordingError("The portal did not share that monitor.")
            self._output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile() as errors:
                remote = session.open_remote()
                try:
                    process = subprocess.Popen(
                        [
                            "gst-launch-1.0",
                            *pipeline(remote.fileno(), node, self._output, self._crop),
                        ],
                        pass_fds=[remote.fileno()],
                        stdout=subprocess.DEVNULL,
                        stderr=errors,
                    )
                finally:
                    remote.close()
                self.running.emit()
                # The pipeline also ends by itself when the user stops sharing
                # from the desktop's own indicator.
                while not self._stop.wait(POLL_SECONDS) and process.poll() is None:
                    pass
                finished = stop(process)
                if not finished and not self._output.is_file():
                    errors.seek(0)
                    detail = errors.read().decode(errors="replace").strip()
                    raise RecordingError(
                        f"Recording failed: {detail}" if detail else "Recording failed."
                    )
        finally:
            session.close()
