# pyright: basic
# jeepney ships no type information, which strict mode cannot work with.
"""Joining a Wi-Fi network from a code, through NetworkManager.

NetworkManager is spoken to over the system bus with jeepney, as the ScreenCast
portal is, because the connection settings need typed values QtDBus cannot
build. The calls block, so they run on a worker thread (see `background`).
`AddAndActivateConnection` saves the network as a profile and starts joining it
without waiting, so success here means the join was started.
"""

from typing import Any

from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection
from jeepney.wrappers import unwrap_msg

from glance.payloads import Wifi

SERVICE = "org.freedesktop.NetworkManager"
OBJECT_PATH = "/org/freedesktop/NetworkManager"
DEVICE_INTERFACE = "org.freedesktop.NetworkManager.Device"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
DEVICE_TYPE_WIFI = 2
TIMEOUT = 10

Settings = dict[str, dict[str, tuple[str, Any]]]


class WifiError(Exception):
    pass


def connection_settings(wifi: Wifi) -> Settings:
    """The NetworkManager profile for joining `wifi`, as D-Bus variants."""
    radio: dict[str, tuple[str, Any]] = {
        "ssid": ("ay", wifi.ssid.encode()),
        "mode": ("s", "infrastructure"),
    }
    if wifi.hidden:
        radio["hidden"] = ("b", True)
    settings: Settings = {
        "connection": {
            "id": ("s", wifi.ssid),
            "type": ("s", "802-11-wireless"),
        },
        "802-11-wireless": radio,
    }
    match wifi.security:
        case "WPA":
            settings["802-11-wireless-security"] = {
                "key-mgmt": ("s", "wpa-psk"),
                "psk": ("s", wifi.password),
            }
        case "WPA3":
            settings["802-11-wireless-security"] = {
                "key-mgmt": ("s", "sae"),
                "psk": ("s", wifi.password),
            }
        case "WEP":
            settings["802-11-wireless-security"] = {
                "key-mgmt": ("s", "none"),
                "wep-key0": ("s", wifi.password),
                "wep-key-type": ("u", 1),
            }
        case "none":
            pass
        case _:
            raise WifiError("This kind of network cannot be joined from here.")
    return settings


def _call(connection: Any, address: DBusAddress, method: str, signature: str, *args):
    message = new_method_call(address, method, signature, args)
    return unwrap_msg(connection.send_and_get_reply(message, timeout=TIMEOUT))


def wifi_device(connection: Any) -> str:
    """The object path of the first Wi-Fi adapter."""
    manager = DBusAddress(OBJECT_PATH, bus_name=SERVICE, interface=SERVICE)
    (devices,) = _call(connection, manager, "GetDevices", "")
    for path in devices:
        properties = DBusAddress(path, bus_name=SERVICE, interface=PROPERTIES_INTERFACE)
        (kind,) = _call(
            connection, properties, "Get", "ss", DEVICE_INTERFACE, "DeviceType"
        )
        if kind[1] == DEVICE_TYPE_WIFI:
            return path
    raise WifiError("No Wi-Fi adapter was found.")


def connect(wifi: Wifi) -> None:
    """Save `wifi` as a network and start joining it. Raises `WifiError`."""
    if not wifi.connectable:
        raise WifiError("This network cannot be joined from here.")
    settings = connection_settings(wifi)
    try:
        connection = open_dbus_connection(bus="SYSTEM")
    except OSError as error:
        raise WifiError(f"Could not reach NetworkManager: {error}") from error
    try:
        device = wifi_device(connection)
        manager = DBusAddress(OBJECT_PATH, bus_name=SERVICE, interface=SERVICE)
        _call(
            connection,
            manager,
            "AddAndActivateConnection",
            "a{sa{sv}}oo",
            settings,
            device,
            "/",
        )
    except WifiError:
        raise
    except Exception as error:  # a refusal from NetworkManager, or a timeout
        raise WifiError(str(error) or type(error).__name__) from error
    finally:
        connection.close()
