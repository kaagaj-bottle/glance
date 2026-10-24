import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from glance.ai.client import GroqError  # noqa: E402
from glance.ai.key import find_key  # noqa: E402
from glance.ui.setup import KeyDialog  # noqa: E402


class KeyDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QApplication([])

    def _save(self, key: str, check: object = None) -> tuple[KeyDialog, str]:
        """Type `key` and click Save, waiting for the check. Returns the stored key."""
        dialog = KeyDialog()
        loop = QEventLoop()
        dialog.finished.connect(loop.quit)
        dialog._key.setText(key)  # pyright: ignore[reportPrivateUsage]
        stored = ""
        with tempfile.TemporaryDirectory() as config:
            environment = {"XDG_CONFIG_HOME": config}
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("glance.ui.setup.check_key", side_effect=check),
            ):
                dialog._save_button.click()  # pyright: ignore[reportPrivateUsage]
                QTimer.singleShot(1500, loop.quit)
                loop.exec()
                stored = find_key()
        return dialog, stored

    def test_an_accepted_key_is_kept_and_the_dialog_accepted(self) -> None:
        dialog, stored = self._save("  gsk_ok ")

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(stored, "gsk_ok")

    def test_a_rejected_key_is_not_kept_and_the_reason_is_shown(self) -> None:
        dialog, stored = self._save("bad", GroqError("Groq rejected the API key"))

        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(stored, "")
        self.assertEqual(dialog._status.text(), "Groq rejected the API key")  # pyright: ignore[reportPrivateUsage]
        self.assertTrue(dialog._save_button.isEnabled())  # pyright: ignore[reportPrivateUsage]

    def test_an_empty_key_is_not_checked(self) -> None:
        with patch("glance.ui.setup.check_key") as check:
            dialog = KeyDialog()
            dialog._save_button.click()  # pyright: ignore[reportPrivateUsage]

        check.assert_not_called()
        self.assertIn("Paste", dialog._status.text())  # pyright: ignore[reportPrivateUsage]

    def test_skip_rejects_the_dialog(self) -> None:
        dialog = KeyDialog()
        dialog._skip.click()  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
