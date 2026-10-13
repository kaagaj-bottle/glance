"""The reverse image search engines Glance can hand a capture to.

None of them has a documented upload API. Each one is given the image the way
its own web page sends it and answers with the address of a results page, which
Glance then opens in the browser. They may change or start refusing at any time,
so every failure is reported rather than assumed away.
"""

import base64
import html
import json
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import Any

TIMEOUT = 20
# A browser-like agent: the default Python one is refused more often.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"

GOOGLE_URL = "https://lens.google.com/v3/upload?hl=en&re=df&st=1&ep=gisbubb"
YANDEX_URL = (
    "https://yandex.com/images-apphost/image-download"
    "?cbird=111&images_avatars_size=preview&images_avatars_namespace=images-cbir"
)
YANDEX_RESULTS = "https://yandex.com/images/search?rpt=imageview&cbir_id="
BING_URL = (
    "https://www.bing.com/images/search"
    "?view=detailv2&iss=sbiupload&FORM=SBIHMP&sbisrc=ImgDropper"
)


class SearchError(Exception):
    pass


class _KeepRedirects(urllib.request.HTTPRedirectHandler):
    """Stop at a redirect: the address it points to is the answer."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_KeepRedirects)


def multipart(
    fields: dict[str, str] | None = None,
    files: dict[str, bytes] | None = None,
) -> tuple[bytes, str]:
    """A multipart/form-data body and its content type."""
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in (fields or {}).items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
            f"\r\n\r\n{value}\r\n".encode()
        )
    for name, data in (files or {}).items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
            f'filename="glance.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
            + data
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _post(url: str, body: bytes, content_type: str) -> tuple[Message, str]:
    """POST and return the response headers and body. Redirects are not followed."""
    request = urllib.request.Request(
        url,
        data=body,
        headers={"User-Agent": USER_AGENT, "Content-Type": content_type},
    )
    try:
        with _opener.open(request, timeout=TIMEOUT) as response:
            return response.headers, response.read().decode()
    except urllib.error.HTTPError as error:
        if 300 <= error.code < 400:
            return error.headers, ""
        raise SearchError(f"The search engine refused the image (HTTP {error.code})")
    except (urllib.error.URLError, TimeoutError) as error:
        raise SearchError("Could not reach the search engine") from error


def _redirect(headers: Message, base: str) -> str:
    location = headers.get("Location")
    if not location:
        raise SearchError("Unexpected response from the search engine")
    return urllib.parse.urljoin(base, location)


_GOOGLE_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Searching with Google Lens</title>
<form id="f" method="post" enctype="multipart/form-data" action="{action}">
  <input type="file" name="encoded_image" id="i" hidden>
</form>
<p style="font: 16px sans-serif">Searching with Google Lens&hellip;</p>
<script>
  const bytes = Uint8Array.from(atob("{image}"), (c) => c.charCodeAt(0));
  const files = new DataTransfer();
  files.items.add(new File([bytes], "glance.png", {{ type: "image/png" }}));
  document.getElementById("i").files = files.files;
  document.getElementById("f").submit();
</script>
"""


def google_results(png: bytes) -> str:
    """A local page that has the browser upload the image to Google Lens.

    Lens ties its results page to the session cookies of the upload, so an upload
    made here would leave the browser with a page that never finds the image.
    """
    folder = Path(tempfile.gettempdir()) / "glance-search"
    folder.mkdir(exist_ok=True)
    for old in folder.glob("lens-*.html"):
        old.unlink(missing_ok=True)
    page = _GOOGLE_PAGE.format(
        action=html.escape(GOOGLE_URL), image=base64.b64encode(png).decode()
    )
    with tempfile.NamedTemporaryFile(
        "w", dir=folder, prefix="lens-", suffix=".html", delete=False
    ) as handle:
        handle.write(page)
    return Path(handle.name).as_uri()


def yandex_results(png: bytes) -> str:
    _, text = _post(YANDEX_URL, png, "image/png")
    try:
        data: Any = json.loads(text)
        cbir_id = str(data["cbir_id"])
    except (ValueError, KeyError, TypeError) as error:
        raise SearchError("Unexpected response from the search engine") from error
    return YANDEX_RESULTS + urllib.parse.quote(cbir_id, safe="/")


def bing_results(png: bytes) -> str:
    # Bing wants the image as base64 text in an ordinary field, not as a file.
    body, content_type = multipart(fields={"imageBin": base64.b64encode(png).decode()})
    headers, _ = _post(BING_URL, body, content_type)
    return _redirect(headers, BING_URL)


@dataclass(frozen=True, slots=True)
class Engine:
    key: str
    name: str
    results: Callable[[bytes], str]
    """Uploads a PNG and returns the address of the page showing the matches."""


ENGINES = (
    Engine("google", "Google Lens", google_results),
    Engine("yandex", "Yandex Images", yandex_results),
    Engine("bing", "Bing Visual Search", bing_results),
)


def engine(key: str) -> Engine | None:
    return next((candidate for candidate in ENGINES if candidate.key == key), None)
