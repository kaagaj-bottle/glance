import unittest

from glance.payloads import Wifi, parse_contact, parse_geo, parse_wifi


class WifiTest(unittest.TestCase):
    def test_a_wpa_network_is_read(self) -> None:
        wifi = parse_wifi("WIFI:T:WPA;S:Home;P:secret pass;;")

        self.assertEqual(wifi, Wifi("Home", "secret pass", "WPA", False))
        assert wifi is not None
        self.assertTrue(wifi.connectable)

    def test_escaped_characters_and_quotes_are_text(self) -> None:
        wifi = parse_wifi(r'WIFI:S:a\;b\:c;P:"1234";T:WPA2;H:true;;')

        self.assertEqual(wifi, Wifi("a;b:c", "1234", "WPA", True))

    def test_the_order_of_fields_does_not_matter_and_case_is_ignored(self) -> None:
        wifi = parse_wifi("wifi:p:pw;s:Cafe;t:wpa3;;")

        self.assertEqual(wifi, Wifi("Cafe", "pw", "WPA3", False))

    def test_an_open_network_needs_no_password(self) -> None:
        wifi = parse_wifi("WIFI:T:nopass;S:Guest;;")

        assert wifi is not None
        self.assertEqual(wifi.security, "none")
        self.assertTrue(wifi.connectable)

    def test_a_missing_type_means_open(self) -> None:
        wifi = parse_wifi("WIFI:S:Guest;;")

        assert wifi is not None
        self.assertEqual(wifi.security, "none")

    def test_networks_that_cannot_be_joined_are_still_read(self) -> None:
        for text in (
            "WIFI:T:WPA;S:Home;;",  # secured, but no password
            "WIFI:T:WPA2-EAP;S:Work;E:PEAP;I:me;P:x;;",
            "WIFI:T:SOMETHING;S:Odd;P:x;;",
            f"WIFI:T:WPA;S:{'x' * 33};P:pw;;",
        ):
            with self.subTest(text=text):
                wifi = parse_wifi(text)
                assert wifi is not None
                self.assertFalse(wifi.connectable)

    def test_other_text_is_not_a_network(self) -> None:
        self.assertIsNone(parse_wifi("WIFI:T:WPA;P:pw;;"))
        self.assertIsNone(parse_wifi("https://example.com"))


class GeoTest(unittest.TestCase):
    def test_a_place_gets_a_map_link(self) -> None:
        geo = parse_geo("geo:27.7172,85.3240")

        assert geo is not None
        self.assertEqual(geo.text, "27.7172, 85.3240")
        self.assertEqual(
            geo.url,
            "https://www.openstreetmap.org/?mlat=27.7172&mlon=85.3240"
            "#map=16/27.7172/85.3240",
        )

    def test_altitude_and_parameters_are_allowed(self) -> None:
        self.assertIsNotNone(parse_geo("geo:-12.5,-70,1200;u=35"))
        self.assertIsNotNone(parse_geo("geo:48.2,16.3?q=Vienna"))

    def test_coordinates_off_the_earth_or_junk_are_refused(self) -> None:
        for text in ("geo:91,0", "geo:0,181", "geo:a,b", "geo:1", "geo:1,2 x"):
            with self.subTest(text=text):
                self.assertIsNone(parse_geo(text))


class ContactTest(unittest.TestCase):
    def test_a_vcard_is_read(self) -> None:
        card = (
            "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Doe;Jane;;;\r\nFN:Jane Doe\r\n"
            "ORG:Acme;Sales\r\nitem1.TEL;TYPE=CELL:+1 555 0100\r\n"
            "EMAIL;TYPE=WORK:jane@acme.example\r\nEND:VCARD"
        )

        contact = parse_contact(card)

        assert contact is not None
        self.assertEqual(contact.name, "Jane Doe")
        self.assertEqual(contact.organization, "Acme, Sales")
        self.assertEqual(contact.phones, ("+1 555 0100",))
        self.assertEqual(contact.emails, ("jane@acme.example",))
        self.assertEqual(
            contact.text, "Jane Doe\nAcme, Sales\n+1 555 0100\njane@acme.example"
        )

    def test_a_vcard_without_fn_uses_n_and_folded_lines_are_joined(self) -> None:
        contact = parse_contact(
            "BEGIN:VCARD\nN:Doe;Jane\nEMAIL:jane@acme\n .example\nEND:VCARD"
        )

        assert contact is not None
        self.assertEqual(contact.name, "Jane Doe")
        self.assertEqual(contact.emails, ("jane@acme.example",))

    def test_a_mecard_is_read(self) -> None:
        contact = parse_contact("MECARD:N:Doe,Jane;TEL:555 0100;EMAIL:j@x.io;;")

        assert contact is not None
        self.assertEqual(contact.name, "Jane Doe")
        self.assertEqual(contact.phones, ("555 0100",))
        self.assertEqual(contact.emails, ("j@x.io",))

    def test_a_card_without_a_name_is_not_a_contact(self) -> None:
        self.assertIsNone(parse_contact("BEGIN:VCARD\nTEL:555\nEND:VCARD"))
        self.assertIsNone(parse_contact("MECARD:TEL:555;;"))
        self.assertIsNone(parse_contact("hello"))


if __name__ == "__main__":
    unittest.main()
