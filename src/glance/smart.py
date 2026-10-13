"""Links and email addresses found in recognized text.

OCR text is only ever acted on when the user clicks, so this just finds what
could be opened. Only web links and email addresses are offered: phone numbers
are left out because a desktop usually has nothing to open a `tel:` link with.
"""

import re
from dataclasses import dataclass
from enum import Enum, auto

_EMAIL = re.compile(r"[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_LINK = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
# Punctuation that ends a sentence rather than a link, and the brackets that
# may close one.
_SENTENCE_END = ".,;:!?"
_CLOSERS = {")": "(", "]": "[", "}": "{"}
MAX_LABEL = 40


class Kind(Enum):
    LINK = auto()
    EMAIL = auto()


@dataclass(frozen=True, slots=True)
class Entity:
    kind: Kind
    text: str
    url: str

    @property
    def label(self) -> str:
        """The text for a menu entry, shortened if it is long."""
        text = self.text
        if len(text) > MAX_LABEL:
            text = text[: MAX_LABEL - 1] + "…"
        return text


def find_entities(text: str) -> list[Entity]:
    """The distinct emails and web links in `text`, in reading order."""
    found: list[tuple[int, Entity]] = []
    taken: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= a or start >= b for a, b in taken)

    for match in _EMAIL.finditer(text):
        taken.append(match.span())
        address = match.group()
        found.append((match.start(), Entity(Kind.EMAIL, address, f"mailto:{address}")))

    for match in _LINK.finditer(text):
        link = _trim(match.group())
        span = (match.start(), match.start() + len(link))
        if not _has_host(link) or not free(*span):
            continue
        taken.append(span)
        url = link if link.lower().startswith("http") else f"https://{link}"
        found.append((match.start(), Entity(Kind.LINK, link, url)))

    seen: set[str] = set()
    entities: list[Entity] = []
    for _, entity in sorted(found, key=lambda item: item[0]):
        if entity.url not in seen:
            seen.add(entity.url)
            entities.append(entity)
    return entities


def _trim(link: str) -> str:
    while link:
        last = link[-1]
        if last in _SENTENCE_END:
            link = link[:-1]
        elif last in _CLOSERS and link.count(last) > link.count(_CLOSERS[last]):
            # A closing bracket belongs to the link only if it opened inside it.
            link = link[:-1]
        else:
            break
    return link


def _has_host(link: str) -> bool:
    """Whether something that looks like a host follows the scheme or `www.`."""
    host = re.sub(r"^(?:https?://)", "", link, flags=re.IGNORECASE).split("/")[0]
    return bool(re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?::\d+)?", host))
