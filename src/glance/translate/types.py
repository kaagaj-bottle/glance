from dataclasses import dataclass


@dataclass(frozen=True)
class Translation:
    text: str
    source: str
    target: str
    # Who did the translating, shown on the card so it is clear where the text went.
    service: str = "Groq"
