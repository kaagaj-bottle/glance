"""What can be done with text picked from a capture."""

from urllib.parse import quote_plus

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication

SEARCH_URL = "https://www.google.com/search?q="


def search_url(text: str) -> QUrl:
    return QUrl(SEARCH_URL + quote_plus(text))


def copy_text(text: str) -> None:
    QGuiApplication.clipboard().setText(text)


def search_web(text: str) -> None:
    QDesktopServices.openUrl(search_url(text))
