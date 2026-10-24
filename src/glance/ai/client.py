"""The part of talking to Groq that every feature shares: the request.

The key comes from `glance.ai.key`. Callers send text or an image to Groq only when the
user asks for it.
"""

import json
import urllib.error
import urllib.request
from typing import Any, cast

from glance.ai.key import find_key

URL = "https://api.groq.com/openai/v1/chat/completions"
MODELS_URL = "https://api.groq.com/openai/v1/models"
TIMEOUT = 30
# Groq sits behind Cloudflare, which refuses the default Python user agent.
USER_AGENT = "Glance"


class GroqError(Exception):
    pass


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
        raise GroqError("Add your Groq API key first (run `glance key`)")
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


def check_key(key: str) -> None:
    """Ask Groq to list its models, which costs nothing. Raises `GroqError` if it
    does not accept the key or cannot be reached."""
    request = urllib.request.Request(
        MODELS_URL,
        headers={"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT):
            return
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise GroqError("Groq rejected the API key") from error
        detail = reason(error)
        suffix = f": {detail}" if detail else ""
        raise GroqError(f"Groq failed (HTTP {error.code}){suffix}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        cause = getattr(error, "reason", error)
        raise GroqError(f"Could not reach Groq ({cause})") from error
