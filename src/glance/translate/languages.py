"""The languages offered as translation targets: Google's codes and their names."""

LANGUAGES: tuple[tuple[str, str], ...] = (
    ("ar", "Arabic"),
    ("bn", "Bengali"),
    ("zh-CN", "Chinese (Simplified)"),
    ("zh-TW", "Chinese (Traditional)"),
    ("cs", "Czech"),
    ("da", "Danish"),
    ("nl", "Dutch"),
    ("en", "English"),
    ("fi", "Finnish"),
    ("fr", "French"),
    ("de", "German"),
    ("el", "Greek"),
    ("he", "Hebrew"),
    ("hi", "Hindi"),
    ("hu", "Hungarian"),
    ("id", "Indonesian"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("ms", "Malay"),
    ("no", "Norwegian"),
    ("fa", "Persian"),
    ("pl", "Polish"),
    ("pt", "Portuguese"),
    ("ro", "Romanian"),
    ("ru", "Russian"),
    ("es", "Spanish"),
    ("sv", "Swedish"),
    ("ta", "Tamil"),
    ("th", "Thai"),
    ("tr", "Turkish"),
    ("uk", "Ukrainian"),
    ("ur", "Urdu"),
    ("vi", "Vietnamese"),
)

DEFAULT = "en"


def supported(code: str) -> str | None:
    """The offered code for a locale name: "fr" for "fr_CA", "zh-TW" for "zh_TW"."""
    wanted = code.replace("_", "-").lower()
    codes = [known for known, _ in LANGUAGES]
    for known in codes:
        if known.lower() == wanted:
            return known
    base = wanted.split("-")[0]
    for known in codes:
        if known.lower().split("-")[0] == base:
            return known
    return None
