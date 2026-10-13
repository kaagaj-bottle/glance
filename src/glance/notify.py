# pyright: basic
# jeepney ships no type information, which strict mode cannot work with.
"""A desktop notification, for what happens after Glance's window is gone."""

from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection
from jeepney.wrappers import unwrap_msg

SERVICE = "org.freedesktop.Notifications"
TIMEOUT = 5
EXPIRE_MS = 6000


def notify(summary: str, body: str = "", icon: str = "") -> bool:
    """Show a notification. False if there is no notification service."""
    address = DBusAddress(
        "/org/freedesktop/Notifications", bus_name=SERVICE, interface=SERVICE
    )
    args = ("Glance", 0, icon, summary, body, [], {}, EXPIRE_MS)
    try:
        connection = open_dbus_connection(bus="SESSION")
        try:
            message = new_method_call(address, "Notify", "susssasa{sv}i", args)
            unwrap_msg(connection.send_and_get_reply(message, timeout=TIMEOUT))
        finally:
            connection.close()
    except Exception:  # a notification is a courtesy, never worth a failure
        return False
    return True
