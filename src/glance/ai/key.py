"""The Groq API key: where it is kept.

The user pastes it once (see `glance.ui.setup`) and it is kept in
`~/.config/glance/groq_key`. `GROQ_API_KEY` in the environment takes precedence, which
is handy when developing.
"""

import os
from pathlib import Path

KEY_VARIABLE = "GROQ_API_KEY"
CONSOLE_URL = "https://console.groq.com/keys"


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


def save_key(key: str) -> None:
    """Keep the key in the key file, readable by the user only."""
    path = key_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Created private, so it is never readable by others, even briefly.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(key.strip() + "\n")
    path.chmod(0o600)
