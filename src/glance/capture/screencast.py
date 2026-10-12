# pyright: basic
# jeepney ships no type information, which strict mode cannot work with.
"""Native-resolution screenshots through the ScreenCast portal.

The Screenshot portal returns one stitched image that the compositor has scaled
to its highest-scale monitor, so lower-scale monitors come out soft. The
ScreenCast portal hands out one PipeWire stream per monitor at that monitor's
real resolution; we take a single frame from each.

The portal is spoken to with jeepney because QtDBus cannot send the unsigned
integers the options need. All of it blocks, so it runs on a worker thread.
"""

import shutil
import subprocess
import tempfile
import time
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from jeepney import DBusAddress, MatchRule, message_bus, new_method_call
from jeepney.io.blocking import DBusConnection, open_dbus_connection
from jeepney.wrappers import unwrap_msg
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

SERVICE = "org.freedesktop.portal.Desktop"
OBJECT_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST_INTERFACE = "org.freedesktop.portal.ScreenCast"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"
SESSION_INTERFACE = "org.freedesktop.portal.Session"

SOURCE_MONITOR = 1
CURSOR_HIDDEN = 1
# Remember the user's choice of monitors until it is revoked, so the share
# prompt appears only once.
PERSIST_UNTIL_REVOKED = 2

RESPONSE_SUCCESS = 0
RESPONSE_CANCELLED = 1

# The prompt waits for the user, so this has to be generous.
RESPONSE_TIMEOUT = 120
# GNOME only sends a frame when the screen repaints, so on an idle desktop a
# stream may never deliver one. Wait briefly for all of them together and let
# the caller fall back for any monitor that is still missing.
FRAME_BUDGET = 1.0


class ScreenCastError(Exception):
    """The ScreenCast portal could not provide the screens."""


# Where a monitor sits on the desktop: its logical position and size.
Place = tuple[tuple[int, int], tuple[int, int]]


@dataclass(frozen=True, slots=True)
class Frame:
    """One monitor's image, with where the portal says it sits on the desktop."""

    position: tuple[int, int]
    size: tuple[int, int]
    image: QImage


def _call(
    connection: DBusConnection, path: str, interface: str, method: str, *args: Any
) -> Any:
    signature = {
        "CreateSession": "a{sv}",
        "SelectSources": "oa{sv}",
        "Start": "osa{sv}",
        "OpenPipeWireRemote": "oa{sv}",
        "Close": "",
    }[method]
    address = DBusAddress(path, bus_name=SERVICE, interface=interface)
    message = new_method_call(address, method, signature, args)
    return unwrap_msg(connection.send_and_get_reply(message))


def _request(
    connection: DBusConnection,
    method: str,
    *args: Any,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Call a portal method that answers later with a Response signal."""
    token = f"glance_{uuid4().hex}"
    sender = (connection.unique_name or "").removeprefix(":").replace(".", "_")
    rule = MatchRule(
        type="signal",
        interface=REQUEST_INTERFACE,
        member="Response",
        path=f"{OBJECT_PATH}/request/{sender}/{token}",
    )
    # Subscribe before calling so a fast answer cannot be missed.
    with connection.filter(rule) as queue:
        connection.send_and_get_reply(message_bus.AddMatch(rule))
        options = {**options, "handle_token": ("s", token)}
        _call(connection, OBJECT_PATH, SCREENCAST_INTERFACE, method, *args, options)
        response = connection.recv_until_filtered(queue, timeout=RESPONSE_TIMEOUT)
    code, results = response.body
    if code == RESPONSE_CANCELLED:
        raise ScreenCastError("The screen share was cancelled.")
    if code != RESPONSE_SUCCESS:
        raise ScreenCastError("The portal could not share the screen.")
    return results


def _grab_frame(fd: int, node: int, output: Path) -> subprocess.Popen[bytes]:
    pipeline = (
        f"pipewiresrc fd={fd} path={node} num-buffers=1 ! videoconvert ! "
        f"video/x-raw,format=RGB ! pngenc compression-level=1 ! "
        f"filesink location={output}"
    ).split()
    return subprocess.Popen(
        ["gst-launch-1.0", "-q", *pipeline],
        pass_fds=[fd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def grab_frames(token_file: Path | None, wanted: Collection[Place]) -> list[Frame]:
    """Share the monitors through the portal and take a frame from each wanted one."""
    if shutil.which("gst-launch-1.0") is None:
        raise ScreenCastError("GStreamer (gst-launch-1.0) is not installed.")

    token = ""
    if token_file is not None and token_file.is_file():
        token = token_file.read_text().strip()

    try:
        connection = open_dbus_connection(bus="SESSION", enable_fds=True)
    except Exception as error:
        raise ScreenCastError("Could not reach the session bus.") from error

    session = ""
    try:
        results = _request(
            connection,
            "CreateSession",
            options={"session_handle_token": ("s", f"glance_{uuid4().hex}")},
        )
        session = results["session_handle"][1]

        select: dict[str, Any] = {
            "types": ("u", SOURCE_MONITOR),
            "multiple": ("b", True),
            "cursor_mode": ("u", CURSOR_HIDDEN),
            "persist_mode": ("u", PERSIST_UNTIL_REVOKED),
        }
        if token:
            select["restore_token"] = ("s", token)
        _request(connection, "SelectSources", session, options=select)

        results = _request(connection, "Start", session, "", options={})
        if token_file is not None and "restore_token" in results:
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(results["restore_token"][1])
        streams = results["streams"][1]
        if not streams:
            raise ScreenCastError("The portal shared no monitors.")
        return _read_streams(connection, session, streams, wanted)
    except ScreenCastError:
        raise
    except Exception as error:
        raise ScreenCastError(f"The ScreenCast portal failed: {error}") from error
    finally:
        if session:
            try:
                _call(connection, session, SESSION_INTERFACE, "Close")
            except Exception:
                pass
        connection.close()


def _read_streams(
    connection: DBusConnection,
    session: str,
    streams: list[Any],
    wanted: Collection[Place],
) -> list[Frame]:
    """Take a frame from each wanted stream at once, within `FRAME_BUDGET` seconds.

    Streams that deliver nothing in time are left out of the result.
    """
    with tempfile.TemporaryDirectory(prefix="glance-") as folder:
        jobs: list[tuple[Any, Path, subprocess.Popen[bytes]]] = []
        try:
            for node, properties in streams:
                place = (tuple(properties["position"][1]), tuple(properties["size"][1]))
                if place not in wanted:
                    continue
                output = Path(folder) / f"{node}.png"
                # A PipeWire connection cannot be shared between processes, so
                # each one gets its own.
                (remote,) = _call(
                    connection,
                    OBJECT_PATH,
                    SCREENCAST_INTERFACE,
                    "OpenPipeWireRemote",
                    session,
                    {},
                )
                try:
                    process = _grab_frame(remote.fileno(), node, output)
                finally:
                    remote.close()
                jobs.append((properties, output, process))

            deadline = time.monotonic() + FRAME_BUDGET
            frames: list[Frame] = []
            for properties, output, process in jobs:
                try:
                    process.wait(timeout=max(0.0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    continue
                image = QImage(str(output))
                if process.returncode == 0 and not image.isNull():
                    frames.append(
                        Frame(
                            position=tuple(properties["position"][1]),
                            size=tuple(properties["size"][1]),
                            image=image,
                        )
                    )
            return frames
        finally:
            for _, _, process in jobs:
                if process.poll() is None:
                    process.kill()
                process.wait()


class ScreenCastWorker(QThread):
    """Runs `grab_frames` off the GUI thread."""

    grabbed = Signal(object)
    failed = Signal(str)

    def __init__(self, token_file: Path | None, wanted: Collection[Place]) -> None:
        super().__init__()
        self._token_file = token_file
        self._wanted = wanted

    def run(self) -> None:
        try:
            frames = grab_frames(self._token_file, self._wanted)
        except ScreenCastError as error:
            self.failed.emit(str(error))
        else:
            self.grabbed.emit(frames)
