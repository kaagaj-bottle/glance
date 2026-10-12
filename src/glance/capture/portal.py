from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtDBus import QDBusConnection, QDBusMessage
from PySide6.QtGui import QImage

SERVICE = "org.freedesktop.portal.Desktop"
OBJECT_PATH = "/org/freedesktop/portal/desktop"
SCREENSHOT_INTERFACE = "org.freedesktop.portal.Screenshot"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"

# Qt's SLOT() macro prefixes the signature with "1". PySide6's stubs say
# `bytes` for the slot, but only `str` works at runtime.
RESPONSE_SLOT = "1_on_response(uint,QVariantMap)"

RESPONSE_SUCCESS = 0
RESPONSE_CANCELLED = 1


class PortalScreenshot(QObject):
    """Takes one screenshot through the XDG Desktop Portal.

    Call `start()` once, then wait for `captured` or `failed`.
    """

    captured = Signal(QImage)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bus = QDBusConnection.sessionBus()

    def start(self) -> bool:
        """Send the request. Returns False if the portal can't be reached."""
        if not self._bus.isConnected():
            return False

        token = f"glance_{uuid4().hex}"
        # The portal answers on a request path derived from our bus name and
        # the handle token, so subscribe before calling to avoid a race.
        sender = self._bus.baseService().removeprefix(":").replace(".", "_")
        request_path = f"{OBJECT_PATH}/request/{sender}/{token}"
        if not self._bus.connect(
            SERVICE,
            request_path,
            REQUEST_INTERFACE,
            "Response",
            self,
            RESPONSE_SLOT,  # pyright: ignore[reportArgumentType]
        ):
            return False

        message = QDBusMessage.createMethodCall(
            SERVICE, OBJECT_PATH, SCREENSHOT_INTERFACE, "Screenshot"
        )
        message.setArguments(["", {"handle_token": token, "interactive": False}])
        reply = self._bus.call(message)
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            self._bus.disconnect(
                SERVICE,
                request_path,
                REQUEST_INTERFACE,
                "Response",
                self,
                RESPONSE_SLOT,  # pyright: ignore[reportArgumentType]
            )
            return False
        return True

    @Slot("uint", "QVariantMap", name="_on_response")
    def _on_response(self, code: int, results: dict[str, Any]) -> None:
        if code == RESPONSE_CANCELLED:
            self.failed.emit("Screenshot was cancelled.")
            return
        if code != RESPONSE_SUCCESS:
            self.failed.emit("The portal could not take a screenshot.")
            return

        path = QUrl(str(results.get("uri", ""))).toLocalFile()
        image = QImage(path)
        if image.isNull():
            self.failed.emit(f"Could not read the screenshot at {path!r}.")
            return
        self.captured.emit(image)
