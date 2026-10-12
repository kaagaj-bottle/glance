import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtDBus import QDBusConnection, QDBusMessage
from PySide6.QtGui import QImage

from glance.capture.portal import (
    OBJECT_PATH,
    REQUEST_INTERFACE,
    RESPONSE_CANCELLED,
    RESPONSE_SLOT,
    RESPONSE_SUCCESS,
    SERVICE,
    PortalScreenshot,
)


def _fake_bus() -> MagicMock:
    bus = MagicMock()
    bus.isConnected.return_value = True
    bus.baseService.return_value = ":1.42"
    bus.connect.return_value = True
    bus.call.return_value.type.return_value = QDBusMessage.MessageType.ReplyMessage
    return bus


def _portal(bus: MagicMock) -> PortalScreenshot:
    with patch("glance.capture.portal.QDBusConnection") as connection:
        connection.sessionBus.return_value = bus
        return PortalScreenshot()


class PortalStartTest(unittest.TestCase):
    def test_subscribes_before_calling_the_portal(self) -> None:
        bus = _fake_bus()
        calls: list[str] = []
        reply = bus.call.return_value

        def connect(*_args: object) -> bool:
            calls.append("connect")
            return True

        def call(_message: object) -> MagicMock:
            calls.append("call")
            return reply

        bus.connect.side_effect = connect
        bus.call.side_effect = call

        self.assertTrue(_portal(bus).start())

        self.assertEqual(calls, ["connect", "call"])

    def test_error_reply_unsubscribes_and_returns_false(self) -> None:
        bus = _fake_bus()
        bus.call.return_value.type.return_value = QDBusMessage.MessageType.ErrorMessage

        self.assertFalse(_portal(bus).start())

        bus.disconnect.assert_called_once()
        self.assertEqual(
            bus.disconnect.call_args.args[1], bus.connect.call_args.args[1]
        )


class PortalResponseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.portal = _portal(_fake_bus())
        self.images: list[QImage] = []
        self.errors: list[str] = []
        self.portal.captured.connect(self.images.append)
        self.portal.failed.connect(self.errors.append)

    def test_cancelled_response_fails(self) -> None:
        self.portal._on_response(RESPONSE_CANCELLED, {})  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(self.errors, ["Screenshot was cancelled."])
        self.assertEqual(self.images, [])

    def test_other_error_code_fails(self) -> None:
        self.portal._on_response(2, {})  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(self.errors, ["The portal could not take a screenshot."])
        self.assertEqual(self.images, [])

    def test_success_loads_the_image_from_the_uri(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shot.png"
            source = QImage(3, 2, QImage.Format.Format_RGB32)
            source.fill(0xFF0000)
            self.assertTrue(source.save(str(path)))
            uri = QUrl.fromLocalFile(str(path)).toString()

            self.portal._on_response(RESPONSE_SUCCESS, {"uri": uri})  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(self.errors, [])
        self.assertEqual(len(self.images), 1)
        self.assertEqual((self.images[0].width(), self.images[0].height()), (3, 2))

    def test_unreadable_file_fails(self) -> None:
        self.portal._on_response(  # pyright: ignore[reportPrivateUsage]
            RESPONSE_SUCCESS, {"uri": "file:///nonexistent/shot.png"}
        )

        self.assertEqual(len(self.errors), 1)
        self.assertIn("Could not read the screenshot", self.errors[0])
        self.assertEqual(self.images, [])


class PortalRealBusTest(unittest.TestCase):
    """Uses the real session bus, which mocks can't check.

    The Response subscription must be accepted by Qt's real `connect`, which
    rejects a wrongly typed or mis-prefixed slot signature.
    """

    def test_response_slot_can_be_subscribed_on_the_real_bus(self) -> None:
        _app = QCoreApplication.instance() or QCoreApplication([])
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            self.skipTest("No D-Bus session bus available.")

        portal = PortalScreenshot()
        path = f"{OBJECT_PATH}/request/test/glance_real_bus_test"
        args = (SERVICE, path, REQUEST_INTERFACE, "Response", portal, RESPONSE_SLOT)

        self.assertTrue(bus.connect(*args))  # pyright: ignore[reportArgumentType]
        bus.disconnect(*args)  # pyright: ignore[reportArgumentType]
