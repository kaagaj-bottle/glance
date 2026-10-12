from dataclasses import dataclass


@dataclass(frozen=True)
class OcrLine:
    """One recognized piece of text and its corners (clockwise from top-left)."""

    text: str
    box: tuple[tuple[float, float], ...]
    confidence: float


@dataclass(frozen=True)
class OcrResult:
    lines: tuple[OcrLine, ...]

    @property
    def text(self) -> str:
        return "\n".join(line.text.strip() for line in self.lines)
