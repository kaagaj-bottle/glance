from typing import cast

from PySide6.QtCore import QSettings

ENABLED_KEY = "library/enabled"


def is_enabled() -> bool:
    """Whether kept screenshots are added to the library. Off until asked for."""
    return cast(
        bool, QSettings("glance", "glance").value(ENABLED_KEY, False, type=bool)
    )


def set_enabled(enabled: bool) -> None:
    QSettings("glance", "glance").setValue(ENABLED_KEY, enabled)
