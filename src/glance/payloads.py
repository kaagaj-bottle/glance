"""What a code can say beyond a link: a Wi-Fi network, a place, a contact.

Everything here only reads text. Codes are untrusted, so a payload that does not
parse cleanly is treated as plain text rather than guessed at.
"""

import re
from dataclasses import dataclass
from urllib.parse import quote

MAX_SSID_BYTES = 32
_SECURITY = {
    "": "none",
    "nopass": "none",
    "none": "none",
    "wep": "WEP",
    "wpa": "WPA",
    "wpa2": "WPA",
    "sae": "WPA3",
    "wpa3": "WPA3",
}


@dataclass(frozen=True, slots=True)
class Wifi:
    ssid: str
    password: str
    # "none", "WEP", "WPA" or "WPA3"; empty for kinds Glance cannot join (EAP).
    security: str
    hidden: bool

    @property
    def connectable(self) -> bool:
        if not self.ssid or len(self.ssid.encode()) > MAX_SSID_BYTES:
            return False
        if self.security == "none":
            return True
        return bool(self.security and self.password)


def _fields(body: str) -> dict[str, str]:
    """Split `K:value;K:value;;` on semicolons that are not backslash-escaped."""
    fields: dict[str, str] = {}
    for part in re.split(r"(?<!\\);", body):
        key, colon, value = part.partition(":")
        if colon and key.strip():
            fields.setdefault(key.strip().upper(), value)
    return fields


def _unescape(value: str) -> str:
    return re.sub(r"\\(.)", r"\1", value)


def parse_wifi(text: str) -> Wifi | None:
    """A network from a `WIFI:T:WPA;S:name;P:password;H:true;;` payload."""
    if text[:5].upper() != "WIFI:":
        return None
    fields = _fields(text[5:])
    ssid = fields.get("S")
    if ssid is None:
        return None
    if "E" in fields:  # enterprise networks need a login Glance has no place for
        security = ""
    else:
        security = _SECURITY.get(fields.get("T", "").strip().lower(), "")
    password = fields.get("P", "")
    # A value in quotes is text even when it looks like hex.
    ssid, password = (_unquote(_unescape(v)) for v in (ssid, password))
    hidden = fields.get("H", "").strip().lower() == "true"
    return Wifi(ssid, password, security, hidden)


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


@dataclass(frozen=True, slots=True)
class Geo:
    latitude: str
    longitude: str

    @property
    def text(self) -> str:
        return f"{self.latitude}, {self.longitude}"

    @property
    def url(self) -> str:
        lat, lon = quote(self.latitude), quote(self.longitude)
        return (
            f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}"
        )


_NUMBER = r"-?\d{1,3}(?:\.\d+)?"
_GEO = re.compile(rf"geo:({_NUMBER}),({_NUMBER})(?:,-?\d+(?:\.\d+)?)?(?:[;?].*)?", re.I)


def parse_geo(text: str) -> Geo | None:
    """A place from a `geo:lat,lon` payload, if the coordinates are on Earth."""
    match = _GEO.fullmatch(text.strip())
    if match is None:
        return None
    latitude, longitude = match.groups()
    if abs(float(latitude)) > 90 or abs(float(longitude)) > 180:
        return None
    return Geo(latitude, longitude)


@dataclass(frozen=True, slots=True)
class Contact:
    name: str
    phones: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()
    organization: str = ""

    @property
    def text(self) -> str:
        """The contact as lines, for copying."""
        lines = [self.name, self.organization, *self.phones, *self.emails]
        return "\n".join(line for line in lines if line)


def parse_contact(text: str) -> Contact | None:
    """A contact from a vCard or a `MECARD:` payload, if it has a name."""
    stripped = text.strip()
    if stripped[:11].upper() == "BEGIN:VCARD":
        return _vcard(stripped)
    if stripped[:7].upper() == "MECARD:":
        return _mecard(stripped[7:])
    return None


def _vcard(text: str) -> Contact | None:
    # A line that starts with a space or tab continues the one before it.
    lines = re.sub(r"\r?\n[ \t]", "", text).splitlines()
    name = organization = ""
    structured = ""
    phones: list[str] = []
    emails: list[str] = []
    for line in lines:
        head, colon, value = line.partition(":")
        if not colon:
            continue
        # Drop a group prefix ("item1.TEL") and parameters (";TYPE=CELL").
        prop = head.split(";")[0].rsplit(".", 1)[-1].upper()
        value = _unescape(value.strip())
        if prop == "FN":
            name = value
        elif prop == "N":
            structured = " ".join(p for p in reversed(value.split(";")[:2]) if p)
        elif prop == "ORG":
            organization = value.replace(";", ", ")
        elif prop == "TEL" and value:
            phones.append(value)
        elif prop == "EMAIL" and value:
            emails.append(value)
    name = name or structured.strip()
    if not name:
        return None
    return Contact(name, tuple(phones), tuple(emails), organization)


def _mecard(body: str) -> Contact | None:
    name = ""
    phones: list[str] = []
    emails: list[str] = []
    for part in re.split(r"(?<!\\);", body):
        key, colon, value = part.partition(":")
        value = _unescape(value.strip())
        key = key.strip().upper()
        if not colon or not value:
            continue
        if key == "N" and not name:
            # MECARD writes "Last,First".
            name = " ".join(p for p in reversed(value.split(",", 1)) if p)
        elif key == "TEL":
            phones.append(value)
        elif key == "EMAIL":
            emails.append(value)
    return Contact(name, tuple(phones), tuple(emails)) if name else None
