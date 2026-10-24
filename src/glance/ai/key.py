"""The Groq API key: where it is kept.

It is read from `GROQ_API_KEY` or, for an app started from a launcher that has no
shell, from `~/.config/glance/groq_key`.
"""

import os
from pathlib import Path

KEY_VARIABLE = "GROQ_API_KEY"


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
