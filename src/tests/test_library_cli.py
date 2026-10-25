import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402

from glance.library.cli import run  # noqa: E402
from glance.library.store import Library  # noqa: E402
from glance.ocr.types import OcrLine, OcrResult  # noqa: E402


class FakeEngine:
    def recognize(self, image: QImage) -> OcrResult:
        return OcrResult((OcrLine("quarterly report", (), 1.0),))


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.database = self.root / "library.db"
        self.enabled = MagicMock()
        for target, value in (
            ("glance.library.settings.set_enabled", self.enabled),
            ("glance.library.settings.is_enabled", MagicMock(return_value=True)),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = run(list(args), self.database, FakeEngine)
        return code, out.getvalue(), err.getvalue()

    def _capture(self, name: str) -> Path:
        image = QImage(4, 3, QImage.Format.Format_RGB32)
        path = self.root / name
        self.assertTrue(image.save(str(path)))
        with Library(self.database) as library:
            library.add(path, 1.0, 4, 3)
        return path

    def test_on_and_off_change_the_setting(self) -> None:
        self.assertEqual(self._run("on")[0], 0)
        self.enabled.assert_called_with(True)
        self.assertEqual(self._run("off")[0], 0)
        self.enabled.assert_called_with(False)

    def test_an_unknown_command_prints_the_usage(self) -> None:
        code, _, err = self._run("frobnicate")

        self.assertEqual(code, 2)
        self.assertIn("usage: glance library", err)

    def test_no_command_prints_the_usage(self) -> None:
        self.assertEqual(self._run()[0], 2)

    def test_search_needs_words_and_the_others_take_none(self) -> None:
        self.assertEqual(self._run("search")[0], 2)
        self.assertEqual(self._run("index", "extra")[0], 2)
        self.assertEqual(self._run("on", "extra")[0], 2)

    def test_index_then_search_finds_the_capture(self) -> None:
        path = self._capture("a.png")

        code, out, _ = self._run("index")
        self.assertEqual(code, 0)
        self.assertIn("Read 1, failed 0.", out)

        code, out, _ = self._run("search", "quarterly", "report")
        self.assertEqual(code, 0)
        self.assertIn(str(path.resolve()), out)
        self.assertIn("[quarterly]", out)

    def test_index_with_nothing_waiting_says_so(self) -> None:
        self.assertIn("Nothing to read.", self._run("index")[1])

    def test_a_missing_file_is_reported_and_fails_the_run(self) -> None:
        self._capture("gone.png").unlink()

        code, _, err = self._run("index")

        self.assertEqual(code, 1)
        self.assertIn("the file is missing", err)

    def test_retry_reads_failed_captures_again(self) -> None:
        path = self._capture("later.png")
        path.rename(self.root / "moved.png")
        self._run("index")
        (self.root / "moved.png").rename(path)

        code, out, _ = self._run("retry")

        self.assertEqual(code, 0)
        self.assertIn("1 queued", out)
        self.assertIn("Read 1, failed 0.", out)

    def test_search_with_no_match_exits_nonzero(self) -> None:
        code, _, err = self._run("search", "nothing")

        self.assertEqual(code, 1)
        self.assertIn("No captures match.", err)

    def test_punctuation_in_a_search_does_not_crash(self) -> None:
        self.assertEqual(self._run("search", 'error: "foo-bar')[0], 1)

    def test_status_counts_the_captures(self) -> None:
        self._capture("a.png")

        _, out, _ = self._run("status")

        self.assertIn("The library is on.", out)
        self.assertIn("1 capture: 1 waiting to be read, 0 that failed.", out)


if __name__ == "__main__":
    unittest.main()
