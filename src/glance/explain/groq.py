"""Explanations from a language model hosted by Groq.

It needs a key from https://console.groq.com, read from `GROQ_API_KEY` or, for an app
started from a launcher that has no shell, from `~/.config/glance/groq_key`. The
picked text is sent to Groq only when the user asks for an explanation.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-20b"
KEY_VARIABLE = "GROQ_API_KEY"
TIMEOUT = 30
# A reasoning model thinks before it answers; a low effort keeps that short.
REASONING_EFFORT = "low"
MAX_ANSWER_TOKENS = 1024
# A whole screen of text is more than an explanation needs, and costs quota.
MAX_INPUT = 8000
# Groq sits behind Cloudflare, which refuses the default Python user agent.
USER_AGENT = "Glance"
PROMPT = (
    "You explain text that was read from a screenshot, so it may contain OCR "
    "mistakes. Say briefly what it means and, if it is long, summarize it. "
    "Answer in the language of the text, in plain text without Markdown."
)


class ExplainError(Exception):
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
        raise ExplainError("Unexpected response from Groq") from error
    if not text:
        raise ExplainError("Groq returned an empty answer")
    return text


def reason(error: urllib.error.HTTPError) -> str:
    """The message Groq put in an error response, or nothing if there is none."""
    try:
        data: Any = json.loads(error.read().decode())
        return str(data["error"]["message"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ""


class GroqExplainer:
    def __init__(self, key: str | None = None) -> None:
        self._key = key

    def explain(self, text: str) -> str:
        key = self._key or find_key()
        if not key:
            raise ExplainError(
                f"Set {KEY_VARIABLE}, or put your Groq key in {key_file()}"
            )
        payload = {
            "model": MODEL,
            "reasoning_effort": REASONING_EFFORT,
            "max_completion_tokens": MAX_ANSWER_TOKENS,
            "messages": [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": text[:MAX_INPUT]},
            ],
        }
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
                raise ExplainError("Groq rejected the API key") from error
            if error.code == 429:
                raise ExplainError(
                    "Groq is limiting requests, try again later"
                ) from error
            detail = reason(error)
            suffix = f": {detail}" if detail else ""
            raise ExplainError(f"Groq failed (HTTP {error.code}){suffix}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            cause = getattr(error, "reason", error)
            raise ExplainError(f"Could not reach Groq ({cause})") from error
        return parse(body)
