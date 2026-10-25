import ctypes
import gc
import sqlite3
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from PySide6.QtCore import QLocale, QRect, QSettings, QStandardPaths, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage
from PySide6.QtWidgets import QApplication

from glance.actions import copy_text, open_entity, search_web
from glance.ai.explain import GroqExplainer
from glance.ai.image import png_for_model
from glance.ai.key import find_key
from glance.ai.translate import GroqTranslator
from glance.ai.worker import ExplainTask
from glance.background import BackgroundTask
from glance.capture.manager import CaptureManager
from glance.capture.recording import Recorder, choose_codec, crop_for, output_size
from glance.capture.types import Monitor, Screenshot
from glance.codes import Code, CodeTask, ScreenCodes
from glance.library.settings import is_enabled as library_enabled
from glance.library.store import Library
from glance.notify import notify
from glance.ocr.rapid import RapidOcrEngine
from glance.ocr.screen import ScreenOcr, selection_result
from glance.ocr.types import OcrResult
from glance.ocr.worker import OcrTask
from glance.payloads import Document, Wifi
from glance.search.engines import engine
from glance.search.worker import SearchTask
from glance.smart import Entity
from glance.translate.languages import DEFAULT, supported
from glance.translate.types import Translation
from glance.translate.worker import TranslateTask
from glance.ui.guide import RecordingGuide
from glance.ui.overlay import IMAGE_SOURCE, ScreenshotOverlay
from glance.ui.recording import RecordingControls
from glance.ui.setup import KeyDialog
from glance.wifi import connect as connect_wifi

SEARCH_EXIT_MS = 300
# The overlay must be off the screen before the first frame is recorded.
RECORD_START_MS = 250
RECORD_ICON = "media-record"
DOCUMENT_KEEP_SECONDS = 24 * 60 * 60
TARGET_KEY = "translate/target"
ICON = "network-wireless"
ASKED_KEY = "setup/asked-for-key"


def screenshots_dir() -> Path:
    pictures = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.PicturesLocation
    )
    return Path(pictures or Path.home() / "Pictures") / "Screenshots"


def videos_dir() -> Path:
    movies = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.MoviesLocation
    )
    return Path(movies or Path.home() / "Videos") / "Screencasts"


def token_file() -> Path:
    data = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(data) / "screencast-token"


def library_path() -> Path:
    data = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(data) / "library.db"


def documents_dir() -> Path:
    cache = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation
    )
    return Path(cache) / "documents"


def write_document(document: Document) -> Path | None:
    """Save the file where it stays until it has been opened. None if it can't be.

    Files from earlier runs are removed, since each one holds a stranger's data.
    """
    folder = documents_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - DOCUMENT_KEEP_SECONDS
        for old in folder.iterdir():
            if old.is_file() and old.stat().st_mtime < cutoff:
                old.unlink()
        path = folder / f"glance-{uuid4().hex[:8]}{document.suffix}"
        path.write_text(document.content, encoding="utf-8", newline="")
    except OSError:
        return None
    return path


def save(image: QImage) -> Path | None:
    """Save the image the way GNOME Screenshot names it. None if it can't be written."""
    folder = screenshots_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"Screenshot From {datetime.now():%Y-%m-%d %H-%M-%S}.png"
    return path if image.save(str(path)) else None


def recording_path(suffix: str) -> Path:
    """Where a recording goes, named the way GNOME names its own."""
    return videos_dir() / f"Screencast From {datetime.now():%Y-%m-%d %H-%M-%S}{suffix}"


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
        self._translate_task: TranslateTask | None = None
        self._explainer = GroqExplainer()
        self._explain_task: ExplainTask | None = None
        self._search_task: SearchTask | None = None
        self._wifi_task: BackgroundTask | None = None
        self._recorder: Recorder | None = None
        self._controls: RecordingControls | None = None
        self._guide: RecordingGuide | None = None
        self.exit_code = 0

    def start(self) -> None:
        self._ask_for_key_once()
        manager = CaptureManager(self._app, token_file())
        manager.captured.connect(self._show_overlay)
        manager.failed.connect(self._fail)
        manager.capture_screen()

    def _ask_for_key_once(self) -> None:
        """On the first run without a key, offer to add one. Skipping is remembered."""
        settings = QSettings("glance", "glance")
        if find_key() or settings.value(ASKED_KEY, False, type=bool):
            return
        settings.setValue(ASKED_KEY, True)
        KeyDialog().exec()

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
        self._overlay.document_opened.connect(self._open_document)
        self._overlay.set_ai_available(bool(find_key()))
        self._overlay.set_target(self._target_language())
        self._overlay.translate_requested.connect(self._translate)
        self._overlay.explain_requested.connect(self._explain)
        self._overlay.record_requested.connect(self._record)
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
            self._add_to_library(path, image)

    def _add_to_library(self, path: Path, image: QImage) -> None:
        """Note the saved file in the library, to be read later.

        Reading the text takes seconds and Glance quits right after a save, so
        `glance library index` does that. This must never fail or slow a save.
        """
        if not library_enabled():
            return
        try:
            with Library(library_path()) as library:
                library.add(path, time.time(), image.width(), image.height())
        except (sqlite3.Error, OSError) as error:
            print(f"glance: could not add it to the library: {error}", file=sys.stderr)

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
        task = TranslateTask(GroqTranslator(), text, target, self._app)

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

    def _explain(self, text: str, image: QImage) -> None:
        """Explain the text, or the image if there is no text."""
        if text:
            self._start_explaining(text, lambda: self._explainer.explain(text))
            return
        # Scaled and encoded on the worker thread, so a big monitor cannot stall the UI.
        self._start_explaining(
            IMAGE_SOURCE,
            lambda: self._explainer.explain_image(png_for_model(image)),
        )

    def _start_explaining(self, source: str, work: Callable[[], str]) -> None:
        """Run `work` and show its answer, if the overlay is still the same one."""
        overlay = self._overlay
        if overlay is None:
            return
        task = ExplainTask(work, self._app)

        def show(explanation: str) -> None:
            # The overlay is gone if the user closed it while this was in flight.
            if overlay is self._overlay:
                overlay.set_explanation(source, explanation)

        def fail(message: str) -> None:
            if overlay is self._overlay:
                overlay.set_explanation_failed(source, message)

        task.done.connect(show)
        task.failed.connect(fail)
        task.start()
        self._explain_task = task

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
        self._explain_task = None
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

    def _open_document(self, document: Document) -> None:
        """Write a contact or event file and open it in whatever handles it."""
        path = write_document(document)
        if path is None:
            self._fail("could not write the file.")
        elif QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QTimer.singleShot(SEARCH_EXIT_MS, self._app.quit)
        else:
            self._fail(f"nothing opens {document.suffix} files. It is saved at {path}.")

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

    def _record(self, area: QRect, monitor: Monitor) -> None:
        """Record the area, after the overlay has left the screen."""
        screenshot = self._screenshot
        if screenshot is None:
            return
        geometry = monitor.geometry
        place = ((geometry.x(), geometry.y()), (geometry.width(), geometry.height()))
        # A whole monitor needs no crop. For a part, the frame's pixels per
        # logical unit come from the native image, as Qt's own ratio is rounded.
        scale = screenshot.scale(monitor)
        crop = None
        if area != geometry:
            crop = crop_for(area, geometry, scale)
            if crop is None:
                self._fail("the selection is too small to record.")
                return
        self._release_capture()
        frame = (round(geometry.width() * scale), round(geometry.height() * scale))
        size = output_size(frame, crop)
        codec = choose_codec()
        recorder = Recorder(
            token_file(), place, crop, recording_path(codec.suffix), size, codec
        )
        # The stop bar is drawn by the guide's helper, beside the area; if there is no
        # X11 for it, or it dies, a small bar on Wayland takes over.
        controls = RecordingControls()
        guide = RecordingGuide(
            area, geometry, framed=crop is not None, parent=self._app
        )
        recorder.finished_with.connect(self._recorded)
        recorder.failed.connect(self._record_failed)
        controls.stop_requested.connect(recorder.request_stop)
        guide.stop_requested.connect(recorder.request_stop)
        self._recorder, self._controls, self._guide = recorder, controls, guide
        shown = False

        def running() -> None:
            if shown:
                guide.begin()
            else:
                controls.start()

        def lost() -> None:
            # Only matters while recording; `_hide_guide` disconnects it first.
            controls.start()

        guide.lost.connect(lost)
        recorder.running.connect(running)

        def begin() -> None:
            nonlocal shown
            shown = guide.start()
            recorder.start()

        # Showing the frame takes a moment, so it starts with the recording.
        QTimer.singleShot(RECORD_START_MS, begin)

    def _hide_guide(self) -> None:
        if self._guide is not None:
            self._guide.lost.disconnect()
            self._guide.stop()
            self._guide = None

    def _join_recorder(self) -> None:
        """The recorder reports from inside `run`; quitting before it returns aborts."""
        if self._recorder is not None:
            self._recorder.wait()

    def _recorded(self, path: Path) -> None:
        if self._controls is not None:
            self._controls.finish()
        self._hide_guide()
        print(path)
        notify("Recording saved", path.name, RECORD_ICON)
        self._join_recorder()
        self._app.quit()

    def _record_failed(self, message: str) -> None:
        if self._controls is not None:
            self._controls.finish()
        self._hide_guide()
        notify("Recording failed", message, RECORD_ICON)
        self._join_recorder()
        self._fail(message)

    def _fail(self, message: str) -> None:
        print(f"glance: {message}", file=sys.stderr)
        self.exit_code = 1
        self._app.quit()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Glance")
    if sys.argv[1:] == ["key"]:
        # `glance key`: change the Groq key, without taking a screenshot.
        KeyDialog().exec()
        return 0
    # Closing the overlay must not end the app while OCR is still running.
    app.setQuitOnLastWindowClosed(False)
    glance = App(app)
    glance.start()
    app.exec()
    return glance.exit_code
