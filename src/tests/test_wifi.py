import unittest
from unittest.mock import patch

from glance.payloads import Wifi
from glance.wifi import WifiError, connect, connection_settings


class SettingsTest(unittest.TestCase):
    def test_a_wpa_network_uses_a_preshared_key(self) -> None:
        settings = connection_settings(Wifi("Home", "pw", "WPA", False))

        self.assertEqual(settings["connection"]["id"], ("s", "Home"))
        self.assertEqual(settings["802-11-wireless"]["ssid"], ("ay", b"Home"))
        self.assertNotIn("hidden", settings["802-11-wireless"])
        self.assertEqual(
            settings["802-11-wireless-security"],
            {"key-mgmt": ("s", "wpa-psk"), "psk": ("s", "pw")},
        )

    def test_wpa3_wep_and_open_networks(self) -> None:
        wpa3 = connection_settings(Wifi("A", "pw", "WPA3", True))
        wep = connection_settings(Wifi("B", "pw", "WEP", False))
        open_ = connection_settings(Wifi("C", "", "none", False))

        self.assertEqual(wpa3["802-11-wireless-security"]["key-mgmt"], ("s", "sae"))
        self.assertEqual(wpa3["802-11-wireless"]["hidden"], ("b", True))
        self.assertEqual(wep["802-11-wireless-security"]["wep-key0"], ("s", "pw"))
        self.assertNotIn("802-11-wireless-security", open_)

    def test_an_unknown_kind_of_network_is_refused(self) -> None:
        with self.assertRaises(WifiError):
            connection_settings(Wifi("Work", "pw", "", False))

    def test_a_network_that_cannot_be_joined_never_reaches_the_bus(self) -> None:
        with patch("glance.wifi.open_dbus_connection") as opened:
            with self.assertRaises(WifiError):
                connect(Wifi("Home", "", "WPA", False))

        opened.assert_not_called()

    def test_a_missing_system_bus_is_reported(self) -> None:
        with patch("glance.wifi.open_dbus_connection", side_effect=OSError("no bus")):
            with self.assertRaisesRegex(WifiError, "no bus"):
                connect(Wifi("Home", "pw", "WPA", False))


if __name__ == "__main__":
    unittest.main()
