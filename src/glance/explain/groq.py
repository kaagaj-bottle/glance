"""Explanations from a language model hosted by Groq.

It needs a key from https://console.groq.com, read from `GROQ_API_KEY`. The picked
text is sent to Groq only when the user asks for an explanation.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any, cast

URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"
KEY_VARIABLE = "GROQ_API_KEY"
TIMEOUT = 30
# Groq sits behind Cloudflare, which refuses the default Python user agent.
USER_AGENT = "Glance"
PROMPT = (
    "You explain text that was read from a screenshot, so it may contain OCR "
    "mistakes. Say briefly what it means and, if it is long, summarize it. "
    "Answer in the language of the text, in plain text without Markdown."
)


class ExplainError(Exception):
    pass


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


class GroqExplainer:
    def __init__(self, key: str | None = None) -> None:
        self._key = key

    def explain(self, text: str) -> str:
        key = self._key or os.environ.get(KEY_VARIABLE, "")
        if not key:
            raise ExplainError(f"Set {KEY_VARIABLE} to your Groq API key")
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": text},
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
            raise ExplainError(f"Groq failed (HTTP {error.code})") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise ExplainError("Could not reach Groq") from error
        return parse(body)
