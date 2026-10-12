from dataclasses import dataclass

Box = tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class OcrWord:
    """A word, or for scripts without spaces a single character.

    `start` and `end` locate it in its line's text, so a run of words can be cut
    from the line with its original spacing and punctuation.
    """

    start: int
    end: int
    box: Box


@dataclass(frozen=True)
class OcrLine:
    """One recognized line of text. Boxes run clockwise from the top-left."""

    text: str
    box: Box
    confidence: float
    words: tuple[OcrWord, ...] = ()


@dataclass(frozen=True)
class OcrResult:
    lines: tuple[OcrLine, ...]

    @property
    def text(self) -> str:
        return "\n".join(line.text.strip() for line in self.lines)
