import ctypes
import gc
import sys
from datetime import datetime
from pathlib import Path
from typing import cast

from PySide6.QtCore import QLocale, QRect, QSettings, QStandardPaths, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage
from PySide6.QtWidgets import QApplication

from glance.actions import copy_text, open_entity, search_web
from glance.background import BackgroundTask
from glance.capture.manager import CaptureManager
from glance.capture.types import Screenshot
from glance.codes import Code, CodeTask, ScreenCodes
from glance.notify import notify
from glance.ocr.rapid import RapidOcrEngine
from glance.ocr.screen import ScreenOcr, selection_result
from glance.ocr.types import OcrResult
from glance.ocr.worker import OcrTask
from glance.payloads import Wifi
from glance.search.engines import engine
from glance.search.worker import SearchTask
from glance.smart import Entity
from glance.translate.google import GoogleTranslator
from glance.translate.languages import DEFAULT, supported
from glance.translate.types import Translation
from glance.translate.worker import TranslateTask, Translator
from glance.ui.overlay import ScreenshotOverlay
from glance.wifi import connect as connect_wifi

SEARCH_EXIT_MS = 300
TARGET_KEY = "translate/target"
ICON = "network-wireless"


def screenshots_dir() -> Path:
    pictures = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.PicturesLocation
    )
    return Path(pictures or Path.home() / "Pictures") / "Screenshots"


def token_file() -> Path:
    data = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(data) / "screencast-token"


def save(image: QImage) -> Path | None:
    """Save the image the way GNOME Screenshot names it. None if it can't be written."""
    folder = screenshots_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"Screenshot From {datetime.now():%Y-%m-%d %H-%M-%S}.png"
    return path if image.save(str(path)) else None


class App:
    def __init__(self, app: QApplication) -> None:
        self._app = app
        self._overlay: ScreenshotOverlay | None = None
        self._screenshot: Screenshot | None = None
        self._screen_ocr: ScreenOcr | None = None
        self._ocr_task: OcrTask | None = None
        self._code_task: CodeTask | None = None
        self._screen_codes: ScreenCodes | None = None
        self._ocr = RapidOcrEngine()
        self._translator: Translator = GoogleTranslator()
        self._translate_task: TranslateTask | None = None
        self._search_task: SearchTask | None = None
        self._wifi_task: BackgroundTask | None = None
        self.exit_code = 0

    def start(self) -> None:
        manager = CaptureManager(self._app, token_file())
        manager.captured.connect(self._show_overlay)
        manager.failed.connect(self._fail)
        manager.capture_screen()

    def _show_overlay(self, screenshot: Screenshot) -> None:
        # Read the whole screen while the user chooses, so the text of whatever
        # they select is ready by the time they ask for it.
        self._screenshot = screenshot
        self._screen_ocr = ScreenOcr(self._ocr, screenshot.images, self._app)
        self._screen_ocr.start()
        self._overlay = ScreenshotOverlay(screenshot, self._app)
        self._read_screen_codes(self._overlay, screenshot)
        self._overlay.captured.connect(self._finish)
        self._overlay.image_copied.connect(self._copy_image)
        self._overlay.image_saved.connect(self._save_image)
        self._overlay.image_searched.connect(self._search_image)
        self._overlay.selection_settled.connect(self._read_selection)
        self._overlay.text_copied.connect(self._copy_text)
        self._overlay.text_searched.connect(self._search_text)
        self._overlay.entity_opened.connect(self._open_entity)
        self._overlay.wifi_requested.connect(self._join_wifi)
        self._overlay.set_target(self._target_language())
        self._overlay.translate_requested.connect(self._translate)
        self._overlay.cancelled.connect(self._app.quit)
        self._overlay.show()

    def _read_screen_codes(
        self, overlay: ScreenshotOverlay, screenshot: Screenshot
    ) -> None:
        """Look for codes on each monitor, for Screen mode."""
        scan = ScreenCodes(screenshot.images, self._app)

        def found(index: int, codes: object) -> None:
            if overlay is self._overlay and isinstance(codes, list):
                overlay.set_screen_codes(index, cast(list[Code], codes))

        scan.found.connect(found)
        scan.start()
        self._screen_codes = scan

    def _finish(self, image: QImage) -> None:
        QGuiApplication.clipboard().setImage(image)
        self._write_image(image)
        self._quit_when_clipboard_taken()

    def _copy_image(self, image: QImage) -> None:
        QGuiApplication.clipboard().setImage(image)
        self._quit_when_clipboard_taken()

    def _save_image(self, image: QImage) -> None:
        self._write_image(image)
        self._app.quit()

    def _search_image(self, image: QImage, key: str) -> None:
        """Upload the image to a search engine, then open its results in the browser."""
        chosen = engine(key)
        if chosen is None:
            self._fail("unknown search engine.")
            return
        # The overlay is already closed, so the app stays alive until this ends.
        self._release_capture()
        task = SearchTask(chosen, image, self._app)
        task.done.connect(self._open_results)
        task.failed.connect(self._fail)
        task.start()
        self._search_task = task

    def _open_results(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))
        # Give the browser request time to leave before the app exits.
        QTimer.singleShot(SEARCH_EXIT_MS, self._app.quit)

    def _write_image(self, image: QImage) -> None:
        path = save(image)
        if path is None:
            print("glance: could not save the screenshot.", file=sys.stderr)
            self.exit_code = 1
        else:
            print(path)

    def _read_selection(self, area: QRect) -> None:
        """Show the text and the codes in a selection.

        The text comes from the screen read ahead if it is done.
        """
        overlay, screenshot = self._overlay, self._screenshot
        if overlay is None or screenshot is None:
            return
        codes = CodeTask(screenshot.crop(area), self._app)

        def show_codes(found: object) -> None:
            if isinstance(found, list):
                overlay.set_codes(cast(list[Code], found), area)

        codes.done.connect(show_codes)
        codes.start()
        self._code_task = codes
        results = self._screen_ocr.results if self._screen_ocr else None
        if results is not None:
            overlay.set_words(selection_result(screenshot, results, area), area)
            return

        # The screen is not read yet (or could not be), so read just the selection.
        task = OcrTask(self._ocr, screenshot.crop(area), self._app)

        def show(result: object) -> None:
            if isinstance(result, OcrResult):
                overlay.set_words(result, area)

        task.done.connect(show)
        task.start()
        self._ocr_task = task

    def _target_language(self) -> str:
        """The language last translated into, or else the system language."""
        saved = str(QSettings("glance", "glance").value(TARGET_KEY, ""))
        return supported(saved) or supported(QLocale.system().name()) or DEFAULT

    def _translate(self, text: str, target: str) -> None:
        QSettings("glance", "glance").setValue(TARGET_KEY, target)
        overlay = self._overlay
        if overlay is None:
            return
        task = TranslateTask(self._translator, text, target, self._app)

        def show(translation: object) -> None:
            # The overlay is gone if the user closed it while this was in flight.
            if overlay is self._overlay and isinstance(translation, Translation):
                overlay.set_translation(text, translation)

        def fail(message: str) -> None:
            if overlay is self._overlay:
                overlay.set_translation_failed(text, target, message)

        task.done.connect(show)
        task.failed.connect(fail)
        task.start()
        self._translate_task = task

    def _copy_text(self, text: str) -> None:
        copy_text(text)
        self._quit_when_clipboard_taken()

    def _quit_when_clipboard_taken(self) -> None:
        """Stay alive until another app copies something: the copied data lives here."""
        self._release_capture()
        clipboard = QGuiApplication.clipboard()

        def taken() -> None:
            if not clipboard.ownsClipboard():
                self._app.quit()

        clipboard.dataChanged.connect(taken)

    def _release_capture(self) -> None:
        """Drop the screenshots and OCR models: only the clipboard is still needed."""
        self._overlay = None
        self._screenshot = None
        self._screen_ocr = None
        self._ocr_task = None
        self._code_task = None
        self._screen_codes = None
        self._translate_task = None
        self._ocr = RapidOcrEngine()
        gc.collect()
        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass

    def _search_text(self, text: str) -> None:
        search_web(text)
        # Give the browser request time to leave before the app exits.
        QTimer.singleShot(SEARCH_EXIT_MS, self._app.quit)

    def _open_entity(self, entity: Entity) -> None:
        open_entity(entity)
        QTimer.singleShot(SEARCH_EXIT_MS, self._app.quit)

    def _join_wifi(self, wifi: Wifi) -> None:
        """Save the network and start joining it, then say how that went."""
        self._release_capture()
        task = BackgroundTask(lambda: connect_wifi(wifi), self._app)

        def started() -> None:
            notify(f"Joining {wifi.ssid}", "NetworkManager is connecting.", ICON)
            self._app.quit()

        def failed(message: str) -> None:
            notify(f"Could not join {wifi.ssid}", message, ICON)
            self._fail(message)

        task.done.connect(started)
        task.failed.connect(failed)
        task.start()
        self._wifi_task = task

    def _fail(self, message: str) -> None:
        print(f"glance: {message}", file=sys.stderr)
        self.exit_code = 1
        self._app.quit()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Glance")
    # Closing the overlay must not end the app while OCR is still running.
    app.setQuitOnLastWindowClosed(False)
    glance = App(app)
    glance.start()
    app.exec()
    return glance.exit_code
