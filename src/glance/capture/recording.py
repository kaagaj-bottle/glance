"""Building and stopping the GStreamer pipeline that records a monitor to a video.

The recorder runs `gst-launch-1.0` as a child process, as the screenshot path does.
The pipeline is only finished properly when the process gets an end-of-stream, so a
recording is stopped with SIGINT (`gst-launch-1.0 -e`) and killed only as a last resort.
"""

import os
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from PySide6.QtCore import QRect, QThread, Signal

from glance.capture.screencast import (
    CURSOR_EMBEDDED,
    Place,
    ScreenCastError,
    open_session,
)

FRAMERATE = 30
# VP8 and OpenH264 aim for a fixed rate (VP8's own default of 256 kbps smears text
# on a screen), so theirs is set from the size of the video: bits per pixel per frame.
VP8_BITS_PER_PIXEL = 0.15
H264_BITS_PER_PIXEL = 0.1
MIN_BITRATE = 2_000_000
MAX_BITRATE = 40_000_000
# x264 keeps a constant quality instead, so a still screen costs almost nothing and
# motion gets what it needs. Lower is sharper and larger.
X264_QUANTIZER = 25
KEYFRAME_FRAMES = 60
# The MP4 index is written first and the file is finished at the end, so a recording
# that is cut short (the app killed, or the share ended with an error) still plays.
MP4_MUX = "mp4mux fragment-duration=1000 fragment-mode=first-moov-then-finalise"
THREADS = 4
# A paused desktop sends no frames, so the last one is repeated to keep the
# video moving at a steady rate.
KEEPALIVE_MS = 100
STOP_TIMEOUT = 10.0
# After an error the pipeline is unlikely to finish on its own.
BROKEN_STOP_TIMEOUT = 3.0
POLL_SECONDS = 0.2
# How long to wait for the portal to say it closed the session, when the
# pipeline stopped on its own.
CLOSE_GRACE = 1.0
# A pipeline that fails sooner than this never got going.
MIN_RUN_SECONDS = 2.0


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


def bitrate(size: tuple[int, int], bits_per_pixel: float) -> int:
    """Bits per second for a screen of this pixel size, kept within limits."""
    wanted = round(size[0] * size[1] * FRAMERATE * bits_per_pixel)
    return max(MIN_BITRATE, min(MAX_BITRATE, wanted))


@dataclass(frozen=True, slots=True)
class Codec:
    """How a recording is encoded and wrapped: the plugin it needs and the file type."""

    element: str
    suffix: str
    chain: Callable[[tuple[int, int]], str]


def _x264(size: tuple[int, int]) -> str:
    return (
        "x264enc speed-preset=ultrafast tune=zerolatency pass=quant "
        f"quantizer={X264_QUANTIZER} threads={THREADS} key-int-max={KEYFRAME_FRAMES}"
        f" ! h264parse ! {MP4_MUX}"
    )


def _openh264(size: tuple[int, int]) -> str:
    return (
        "openh264enc rate-control=bitrate complexity=low "
        f"bitrate={bitrate(size, H264_BITS_PER_PIXEL)} gop-size={KEYFRAME_FRAMES}"
        f" ! h264parse ! {MP4_MUX}"
    )


def _vp8(size: tuple[int, int]) -> str:
    return (
        f"vp8enc deadline=1 cpu-used=4 threads={THREADS} "
        f"keyframe-max-dist={KEYFRAME_FRAMES} "
        f"target-bitrate={bitrate(size, VP8_BITS_PER_PIXEL)} ! webmmux"
    )


# In order of preference. x264 is fastest and gives the smallest files, but its plugin
# is GPL and not always installed; OpenH264 comes next; VP8 is in the base plugins.
CODECS = (
    Codec("x264enc", ".mp4", _x264),
    Codec("openh264enc", ".mp4", _openh264),
    Codec("vp8enc", ".webm", _vp8),
)


def has_element(name: str) -> bool:
    try:
        return (
            subprocess.run(
                ["gst-inspect-1.0", "--exists", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


def choose_codec(available: Callable[[str], bool] = has_element) -> Codec:
    """The best codec whose plugin is installed. VP8 is the last resort."""
    return next((codec for codec in CODECS if available(codec.element)), CODECS[-1])


def output_size(frame: tuple[int, int], crop: Crop | None) -> tuple[int, int]:
    """The video's size in pixels: the monitor's frame less what the crop cuts."""
    if crop is None:
        return frame
    return frame[0] - crop.left - crop.right, frame[1] - crop.top - crop.bottom


def pipeline(
    fd: int,
    node: int,
    output: Path,
    crop: Crop | None,
    size: tuple[int, int],
    codec: Codec,
) -> list[str]:
    """The `gst-launch-1.0` arguments that record one PipeWire stream to a file.

    `size` is the video's size in pixels, after the crop. Each stage has a queue
    in front of it so the stages run on threads of their own, and the screen is
    cropped before it is converted so only the part kept costs anything. The queues
    that sit before the slow stages drop the oldest frame rather than hold up the
    capture.
    """
    leaky = "queue max-size-buffers=4 leaky=downstream"
    steps = [f"pipewiresrc fd={fd} path={node} keepalive-time={KEEPALIVE_MS}", leaky]
    if crop is not None:
        steps.append(
            f"videocrop left={crop.left} top={crop.top} "
            f"right={crop.right} bottom={crop.bottom}"
        )
    steps += [
        f"videoconvert n-threads={THREADS}",
        leaky,
        "videorate",
        f"video/x-raw,framerate={FRAMERATE}/1",
        "queue max-size-buffers=8",
        codec.chain(size),
    ]
    args = " ! ".join(steps).split()
    # gst-launch joins its arguments and parses them again, so a path with
    # spaces (such as "Screencast From ...") has to be quoted for it.
    return ["-e", "-q", *args, "!", "filesink", f"location={_quoted(output)}"]


def _quoted(path: Path) -> str:
    escaped = str(path).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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


def has_error(errors: IO[bytes]) -> bool:
    """Whether the pipeline has reported an error.

    This reads without moving the offset the child writes at.
    """
    try:
        return b"ERROR" in os.pread(errors.fileno(), 65536, 0)
    except OSError:
        return False


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
        size: tuple[int, int],
        codec: Codec,
    ) -> None:
        super().__init__()
        self._size = size
        self._codec = codec
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
                            *pipeline(
                                remote.fileno(),
                                node,
                                self._output,
                                self._crop,
                                self._size,
                                self._codec,
                            ),
                        ],
                        pass_fds=[remote.fileno()],
                        stdout=subprocess.DEVNULL,
                        stderr=errors,
                    )
                finally:
                    remote.close()
                self.running.emit()
                begun = time.monotonic()
                # The user can also stop sharing from the desktop's own indicator.
                # The pipeline then fails with an error of its own, and `-e` makes it
                # wait for an end-of-stream that may never come, so an error is
                # treated like a stop. The index is written as it goes, so the file
                # plays even if it has to be killed.
                ended = broken = False
                with session.watching() as closed:
                    while not self._stop.is_set() and process.poll() is None:
                        if closed(POLL_SECONDS):
                            ended = True
                            break
                        if has_error(errors):
                            broken = True
                            break
                    if not (ended or broken) and not self._stop.is_set():
                        ended = closed(CLOSE_GRACE)
                ran = time.monotonic() - begun
                gave_up = not self._stop.is_set() and (
                    broken or process.poll() is not None
                )
                patience = BROKEN_STOP_TIMEOUT if ended or broken else STOP_TIMEOUT
                clean = (
                    stop(process, patience)
                    or ended
                    or (gave_up and ran >= MIN_RUN_SECONDS)
                )
                size = self._output.stat().st_size if self._output.is_file() else 0
                if not clean or size == 0:
                    errors.seek(0)
                    detail = errors.read().decode(errors="replace").strip()
                    if size == 0:
                        self._output.unlink(missing_ok=True)
                    raise RecordingError(
                        f"Recording failed: {detail}" if detail else "Recording failed."
                    )
        finally:
            session.close()
