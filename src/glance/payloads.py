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


@dataclass(frozen=True, slots=True)
class Document:
    """A file Glance writes for another app to import: a contact or an event."""

    suffix: str
    content: str


@dataclass(frozen=True, slots=True)
class When:
    """A date or date-time from a calendar code, kept as written: `20261013T143000Z`."""

    value: str
    # The property parameter that gives it meaning: ";VALUE=DATE" or ";TZID=Zone".
    params: str = ""

    @property
    def text(self) -> str:
        """A readable form: `2026-10-13 14:30 UTC`."""
        date = f"{self.value[0:4]}-{self.value[4:6]}-{self.value[6:8]}"
        if len(self.value) == 8:
            return date
        text = f"{date} {self.value[9:11]}:{self.value[11:13]}"
        if self.value.endswith("Z"):
            return f"{text} UTC"
        zone = self.params.removeprefix(";TZID=")
        return f"{text} ({zone})" if zone else text


@dataclass(frozen=True, slots=True)
class Event:
    summary: str
    start: When
    end: When | None = None
    location: str = ""

    @property
    def text(self) -> str:
        """The event as lines, for copying."""
        when = self.start.text + (f" – {self.end.text}" if self.end else "")
        return "\n".join(line for line in (self.summary, when, self.location) if line)


_WHEN = re.compile(r"\d{8}(?:T\d{6}Z?)?")
_PARAM = re.compile(r";(?:VALUE=DATE(?:-TIME)?|TZID=[A-Za-z0-9_+\-/]{1,64})", re.I)


def _when(head: str, value: str) -> When | None:
    """A date from a DTSTART or DTEND line, whose parameters are checked."""
    params = head.partition(";")[2]
    value = value.strip()
    if not _WHEN.fullmatch(value):
        return None
    kept = ""
    for part in filter(None, params.split(";")):
        if not _PARAM.fullmatch(f";{part}"):
            return None
        # A date-time's type is clear from its value; only the zone matters.
        if part.upper().startswith("TZID=") and not value.endswith("Z"):
            kept = f";{part}"
    return When(value, kept)


def parse_event(text: str) -> Event | None:
    """An event from `BEGIN:VEVENT`, bare or inside a `VCALENDAR`, with a start."""
    stripped = text.strip()
    if not re.match(r"BEGIN:(VCALENDAR|VEVENT)\b", stripped, re.I):
        return None
    lines = re.sub(r"\r?\n[ \t]", "", stripped).splitlines()
    inside = False
    summary = location = ""
    start = end = None
    for line in lines:
        if line.strip().upper() == "BEGIN:VEVENT":
            if inside:
                break
            inside = True
            continue
        if line.strip().upper() == "END:VEVENT":
            break
        head, colon, value = line.partition(":")
        if not inside or not colon:
            continue
        prop = head.split(";")[0].upper()
        if prop == "SUMMARY":
            summary = _unescape_text(value)
        elif prop == "LOCATION":
            location = _unescape_text(value)
        elif prop == "DTSTART":
            start = _when(head, value)
        elif prop == "DTEND":
            end = _when(head, value)
    if start is None:
        return None
    return Event(summary or "Event", start, end, location)


def _unescape_text(value: str) -> str:
    return re.sub(r"\\(.)", lambda m: "\n" if m[1] in "nN" else m[1], value).strip()


def _escape_text(value: str) -> str:
    value = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return " ".join(value.split("\r")).replace("\n", "\\n")


def _fold(line: str) -> str:
    """Wrap a line at 75 bytes, as the calendar format asks, never inside a letter."""
    parts: list[str] = []
    current = ""
    for char in line:
        limit = 75 if not parts else 74
        if len((current + char).encode()) > limit:
            parts.append(current)
            current = ""
        current += char
    parts.append(current)
    return "\r\n ".join(parts)


def _document(lines: list[str]) -> str:
    return "".join(_fold(line) + "\r\n" for line in lines)


def event_ics(event: Event, uid: str, stamp: str) -> str:
    """A calendar file holding only what was read from the code."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Glance//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART{event.start.params}{_value_param(event.start)}:{event.start.value}",
        f"SUMMARY:{_escape_text(event.summary)}",
    ]
    if event.end:
        lines.insert(
            -1, f"DTEND{event.end.params}{_value_param(event.end)}:{event.end.value}"
        )
    if event.location:
        lines.append(f"LOCATION:{_escape_text(event.location)}")
    return _document([*lines, "END:VEVENT", "END:VCALENDAR"])


def _value_param(when: When) -> str:
    return ";VALUE=DATE" if len(when.value) == 8 else ""


def contact_vcard(contact: Contact) -> str:
    """A contact file holding only what was read from the code."""
    lines = ["BEGIN:VCARD", "VERSION:4.0", f"FN:{_escape_text(contact.name)}"]
    if contact.organization:
        lines.append(f"ORG:{_escape_text(contact.organization)}")
    lines += [f"TEL:{_escape_text(phone)}" for phone in contact.phones]
    lines += [f"EMAIL:{_escape_text(email)}" for email in contact.emails]
    return _document([*lines, "END:VCARD"])
