"""The part of talking to Groq that every feature shares: the key and the request.

It needs a key from https://console.groq.com, read from `GROQ_API_KEY` or, for an app
started from a launcher that has no shell, from `~/.config/glance/groq_key`. Callers
send text or an image to Groq only when the user asks for it.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

URL = "https://api.groq.com/openai/v1/chat/completions"
KEY_VARIABLE = "GROQ_API_KEY"
TIMEOUT = 30
# Groq sits behind Cloudflare, which refuses the default Python user agent.
USER_AGENT = "Glance"


class GroqError(Exception):
    pass


def key_file() -> Path:
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "glance" / "groq_key"


def find_key() -> str:
    """The key from the environment, else from the key file, else nothing."""
    key = os.environ.get(KEY_VARIABLE, "").strip()
    if key:
        return key
    try:
        return key_file().read_text().strip()
    except OSError:
        return ""


def parse(body: str) -> str:
    """The reply in a chat completion response."""
    try:
        data: Any = json.loads(body)
        choices = cast(list[dict[str, Any]], data["choices"])
        text = str(choices[0]["message"]["content"]).strip()
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise GroqError("Unexpected response from Groq") from error
    if not text:
        raise GroqError("Groq returned an empty answer")
    return text


def reason(error: urllib.error.HTTPError) -> str:
    """The message Groq put in an error response, or nothing if there is none."""
    try:
        data: Any = json.loads(error.read().decode())
        return str(data["error"]["message"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ""


def chat(payload: dict[str, Any], key: str | None = None) -> str:
    """Post a chat completion request and return the reply's text."""
    key = key or find_key()
    if not key:
        raise GroqError(f"Set {KEY_VARIABLE}, or put your Groq key in {key_file()}")
    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode()
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise GroqError("Groq rejected the API key") from error
        if error.code == 429:
            raise GroqError("Groq is limiting requests, try again later") from error
        detail = reason(error)
        suffix = f": {detail}" if detail else ""
        raise GroqError(f"Groq failed (HTTP {error.code}){suffix}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        cause = getattr(error, "reason", error)
        raise GroqError(f"Could not reach Groq ({cause})") from error
    return parse(body)
