"""Building and stopping the GStreamer pipeline that records a monitor to WebM.

The recorder runs `gst-launch-1.0` as a child process, as the screenshot path does.
The pipeline is only finished properly when the process gets an end-of-stream, so a
recording is stopped with SIGINT (`gst-launch-1.0 -e`) and killed only as a last resort.
"""

import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRect

FRAMERATE = 30
# A paused desktop sends no frames, so the last one is repeated to keep the
# video moving at a steady rate.
KEEPALIVE_MS = 100
STOP_TIMEOUT = 10.0


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
