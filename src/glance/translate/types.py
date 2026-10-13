from dataclasses import dataclass


@dataclass(frozen=True)
class Translation:
    text: str
    source: str
    target: str
