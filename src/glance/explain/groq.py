"""Explanations from a language model hosted by Groq."""

import base64
from typing import Any

from glance.groq import chat

MODEL = "openai/gpt-oss-20b"
# Groq's preview model that reads images, which the text model above cannot.
VISION_MODEL = "qwen/qwen3.8-27b"
# A reasoning model thinks before it answers; a low effort keeps that short.
REASONING_EFFORT = "low"
MAX_ANSWER_TOKENS = 1024
# A whole screen of text is more than an explanation needs, and costs quota.
MAX_INPUT = 8000
PROMPT = (
    "You explain text that was read from a screenshot, so it may contain OCR "
    "mistakes. Say briefly what it means and, if it is long, summarize it. "
    "Always answer in English, whatever language the text is in, in plain text "
    "without Markdown."
)
IMAGE_PROMPT = (
    "You explain a screenshot or part of one. Say briefly what it shows and what "
    "any text in it means. Do not name people from their faces. Always answer in "
    "English, whatever language the image uses, in plain text without Markdown."
)


class GroqExplainer:
    def __init__(self, key: str | None = None) -> None:
        self._key = key

    def explain(self, text: str) -> str:
        """Explain the text."""
        return self._ask(
            {
                "model": MODEL,
                "reasoning_effort": REASONING_EFFORT,
                "max_completion_tokens": MAX_ANSWER_TOKENS,
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": text[:MAX_INPUT]},
                ],
            }
        )

    def explain_image(self, png: bytes) -> str:
        """Explain the image, given as PNG data."""
        url = "data:image/png;base64," + base64.b64encode(png).decode()
        return self._ask(
            {
                "model": VISION_MODEL,
                "max_completion_tokens": MAX_ANSWER_TOKENS,
                "messages": [
                    {"role": "system", "content": IMAGE_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Explain this image."},
                            {"type": "image_url", "image_url": {"url": url}},
                        ],
                    },
                ],
            }
        )

    def _ask(self, payload: dict[str, Any]) -> str:
        return chat(payload, self._key)
