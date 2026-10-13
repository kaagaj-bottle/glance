"""Translation through the free endpoint behind Google's own web clients.

It needs no key, but it is not a documented API: Google may throttle or change
it at any time, so every failure is reported rather than assumed away.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, cast

from glance.translate.types import Translation

URL = "https://translate.googleapis.com/translate_a/single"
TIMEOUT = 10
# A browser-like agent: the default Python one is refused more often.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) Glance"


class TranslateError(Exception):
    pass


def parse(body: str, target: str) -> Translation:
    """The translation in a `dj=1` response. The sentences keep their line breaks."""
    try:
        data: Any = json.loads(body)
        sentences = cast(list[dict[str, Any]], data["sentences"])
        text = "".join(
            str(sentence["trans"]) for sentence in sentences if "trans" in sentence
        )
        source = str(data.get("src", ""))
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise TranslateError(
            "Unexpected response from the translation service"
        ) from error
    return Translation(text.strip(), source, target)


class GoogleTranslator:
    """Translates from any language into a language code such as "en"."""

    def translate(self, text: str, target: str) -> Translation:
        query = urllib.parse.urlencode(
            {"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "dj": "1"}
        )
        # POST, so a long selection is not limited by the length of a URL.
        request = urllib.request.Request(
            f"{URL}?{query}",
            data=urllib.parse.urlencode({"q": text}).encode(),
            headers={"User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                body = response.read().decode()
        except urllib.error.HTTPError as error:
            if error.code == 429:
                raise TranslateError(
                    "Google is limiting requests, try again later"
                ) from error
            raise TranslateError(f"Translation failed (HTTP {error.code})") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise TranslateError("Could not reach the translation service") from error
        return parse(body, target)
