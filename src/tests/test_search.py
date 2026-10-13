import base64
import contextlib
import io
import json
import os
import unittest
import urllib.error
import urllib.parse
from email.message import Message
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QThreadPool  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glance.app import App  # noqa: E402
from glance.capture.types import Monitor, Screenshot  # noqa: E402
from glance.search import engines  # noqa: E402
from glance.search.engines import ENGINES, SearchError, engine  # noqa: E402
from glance.search.worker import SearchTask, png_bytes  # noqa: E402
from glance.ui.overlay import ScreenshotOverlay  # noqa: E402

MONITOR = Monitor(0, "A", QRect(0, 0, 400, 300))
PNG = b"\x89PNGdata"


def _image() -> QImage:
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    return image


def _headers(**values: str) -> Message:
    headers = Message()
    for name, value in values.items():
        headers[name] = value
    return headers


class MultipartTest(unittest.TestCase):
    def test_files_and_fields_are_in_the_body(self) -> None:
        body, content_type = engines.multipart({"a": "1"}, {"img": PNG})

        boundary = content_type.split("boundary=")[1].encode()
        self.assertTrue(content_type.startswith("multipart/form-data"))
        self.assertIn(b'name="a"\r\n\r\n1\r\n', body)
        self.assertIn(b'name="img"; filename="glance.png"', body)
        self.assertIn(PNG, body)
        self.assertTrue(body.endswith(b"--" + boundary + b"--\r\n"))


class EngineTest(unittest.TestCase):
    def test_an_engine_is_found_by_its_key(self) -> None:
        self.assertEqual(engine("google"), ENGINES[0])
        self.assertIsNone(engine("nope"))

    def test_google_hands_the_browser_a_page_that_uploads_the_image(self) -> None:
        url = engines.google_results(PNG)

        self.assertTrue(url.startswith("file://"))
        page = Path(urllib.parse.urlparse(url).path).read_text()
        self.assertIn(engines.GOOGLE_URL.replace("&", "&amp;"), page)
        self.assertIn('name="encoded_image"', page)
        self.assertIn(base64.b64encode(PNG).decode(), page)

    def test_yandex_opens_the_uploaded_image(self) -> None:
        sent = (_headers(), json.dumps({"cbir_id": "10232618/NZTR Fp1"}))
        with patch.object(engines, "_post", return_value=sent) as post:
            url = engines.yandex_results(PNG)

        self.assertEqual(url, engines.YANDEX_RESULTS + "10232618/NZTR%20Fp1")
        self.assertEqual(post.call_args.args[1], PNG)
        self.assertEqual(post.call_args.args[2], "image/png")

    def test_bing_sends_the_image_as_base64_and_resolves_the_redirect(self) -> None:
        sent = (_headers(Location="/images/search?view=detailV2&insightsToken=x"), "")
        with patch.object(engines, "_post", return_value=sent) as post:
            url = engines.bing_results(PNG)

        self.assertEqual(
            url, "https://www.bing.com/images/search?view=detailV2&insightsToken=x"
        )
        self.assertIn(base64.b64encode(PNG), post.call_args.args[1])

    def test_a_missing_redirect_or_id_is_an_error(self) -> None:
        with patch.object(engines, "_post", return_value=(_headers(), "")):
            with self.assertRaises(SearchError):
                engines.bing_results(PNG)
            with self.assertRaises(SearchError):
                engines.yandex_results(PNG)

    def test_a_redirect_is_returned_rather_than_followed(self) -> None:
        error = urllib.error.HTTPError(
            "https://x", 303, "See Other", _headers(Location="/next"), None
        )
        with patch.object(engines._opener, "open", side_effect=error):  # pyright: ignore[reportPrivateUsage]
            headers, body = engines._post("https://x", b"", "text/plain")  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(headers["Location"], "/next")
        self.assertEqual(body, "")

    def test_a_refusal_and_a_network_failure_are_errors(self) -> None:
        refused = urllib.error.HTTPError("https://x", 429, "Slow", _headers(), None)
        for failure in (refused, urllib.error.URLError("down"), TimeoutError()):
            with (
                patch.object(engines._opener, "open", side_effect=failure),  # pyright: ignore[reportPrivateUsage]
                self.assertRaises(SearchError),
            ):
                engines._post("https://x", b"", "text/plain")  # pyright: ignore[reportPrivateUsage]


class SearchTaskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_an_image_is_encoded_as_png(self) -> None:
        self.assertEqual(png_bytes(_image())[:8], b"\x89PNG\r\n\x1a\n")

    def _run(self, results: MagicMock) -> tuple[MagicMock, MagicMock]:
        fake = engines.Engine("fake", "Fake", results)
        task = SearchTask(fake, _image())
        done, failed = MagicMock(), MagicMock()
        task.done.connect(done)
        task.failed.connect(failed)
        task.start()
        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()
        return done, failed

    def test_the_results_address_is_reported(self) -> None:
        done, failed = self._run(MagicMock(return_value="https://r"))

        done.assert_called_once_with("https://r")
        failed.assert_not_called()

    def test_a_failure_is_reported(self) -> None:
        done, failed = self._run(MagicMock(side_effect=SearchError("nope")))

        done.assert_not_called()
        failed.assert_called_once_with("nope")


class OverlaySearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_choosing_an_engine_sends_the_selection_and_closes(self) -> None:
        image = QImage(MONITOR.geometry.size(), QImage.Format.Format_RGB32)
        overlay = ScreenshotOverlay(Screenshot((MONITOR,), (image,)))
        searched = MagicMock()
        overlay.image_searched.connect(searched)
        overlay._selection = QRect(10, 10, 50, 40)  # pyright: ignore[reportPrivateUsage]

        overlay._panel.search_requested.emit("yandex")  # pyright: ignore[reportPrivateUsage]

        searched.assert_called_once()
        sent, key = searched.call_args.args
        self.assertEqual(sent.width(), 50)
        self.assertEqual(key, "yandex")
        self.assertTrue(overlay._finished)  # pyright: ignore[reportPrivateUsage]

    def test_nothing_is_searched_without_a_selection(self) -> None:
        image = QImage(MONITOR.geometry.size(), QImage.Format.Format_RGB32)
        overlay = ScreenshotOverlay(Screenshot((MONITOR,), (image,)))
        searched = MagicMock()
        overlay.image_searched.connect(searched)

        overlay._panel.search_requested.emit("google")  # pyright: ignore[reportPrivateUsage]

        searched.assert_not_called()


class AppSearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = cast(QApplication, QApplication.instance() or QApplication([]))

    def setUp(self) -> None:
        self.glance = App(self.app)
        self.quit = MagicMock()
        self.glance._app = MagicMock(quit=self.quit)  # pyright: ignore[reportPrivateUsage]

    def test_a_search_uploads_then_opens_the_results_in_the_browser(self) -> None:
        with (
            patch("glance.app.SearchTask") as task,
            patch("glance.app.QDesktopServices.openUrl") as opened,
            patch("glance.app.QTimer.singleShot") as later,
        ):
            self.glance._search_image(_image(), "bing")  # pyright: ignore[reportPrivateUsage]
            task.return_value.start.assert_called_once()
            opened.assert_not_called()

            self.glance._open_results("https://results")  # pyright: ignore[reportPrivateUsage]

            self.assertEqual(opened.call_args.args[0].toString(), "https://results")
            later.assert_called_once()

    def test_an_unknown_engine_fails_without_uploading(self) -> None:
        with (
            patch("glance.app.SearchTask") as task,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.glance._search_image(_image(), "nope")  # pyright: ignore[reportPrivateUsage]

        task.assert_not_called()
        self.assertEqual(self.glance.exit_code, 1)
        self.quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
