# Glance

Glance is a planned Linux desktop app for capturing and understanding what is on your screen. It aims to combine familiar screenshot and screen recording tools with OCR, translation, and visual search, so you can act on content without leaving the capture workflow.

The goal is to support both a selected area and the whole screen. Planned actions include taking screenshots, recording the screen, extracting text, translating visible content, and searching for images or objects in a Google Lens-like way.

Flatpak is the intended distribution format. Windows support may be considered later, but the current focus is Linux.

## Run

Run the app from the project root:

```sh
uv run glance
```

Glance takes a screenshot, then shows it full-screen on every monitor so you can
choose what to keep, much like GNOME's screenshot tool:

- Drag to select an area. Drag a corner or edge to resize it, or drag inside to move it.
- **Selection** / **Screen** in the bottom bar switch between an area and a whole
  monitor (click the monitor).
- **Done** (`Enter` or `Space`) copies the image to the clipboard and saves it. **Copy**
  (`C`) only copies it and **Save** (`S`) only saves it. `Esc` cancels.
- **Search** (`I`) offers Google Lens, Yandex Images and Bing Visual Search. Pick one
  and Glance uploads the selection (or the monitor, in Screen mode) to it and opens
  the engine's results page in your browser. Nothing is sent until you choose an
  engine. Google Lens is uploaded by the browser itself (through a short-lived page in
  your temp folder), because its results only work with the browser's own session.
  These upload endpoints are undocumented and may change or be rate limited,
  and a Flatpak build will need network access for them. TinEye is not offered
  because it refuses uploads from a script.
- As soon as you let go of a selection, the text inside it gets a faint violet tint and
  a **Aa 42 words** label appears beside the size. Drag over the words to pick them,
  like text on a web page, or click the label (`Ctrl+A`) to pick all of them. A small
  bubble then offers **Copy**, **Translate** and **Search** (opens a web search in your
  browser) for the picked words. `T` or `Ctrl+C` copies, `L` translates and `V`
  searches without the bubble;
  with nothing picked they use all the text in the selection. If the picked words
  hold a web link (`http://…` or `www.…`) or an email address, the bubble also shows
  **Open link** or **Email**; with several, **Open…** lets you choose. Nothing is
  opened until you click it. Dragging anywhere
  else in the selection still moves it.
  Glance reads the whole screen in the background as soon as it starts, so the text
  usually appears instantly; if you select before that finishes, only the selection
  is read. OCR uses [RapidOCR](https://github.com/RapidAI/RapidOCR) with models
  bundled in the package, so it works offline; the first run takes a few seconds to
  load them.
- A QR code or barcode inside the selection is read too, offline (with
  [zxing-cpp](https://github.com/zxing-cpp/zxing-cpp)). A pill such as **QR example.com**
  appears beside the size; click it (or press `Q`) to choose **Open link** or **Email**
  (only when the whole code is a web link or a `mailto:` address, since a code can say
  anything), **Copy** its content, or, for product barcodes (EAN, UPC, ISBN), **Search**
  the number on the web. Nothing is opened until you choose it. Codes are looked for in
  a selection, not in Screen mode.

**Translate** shows the translation on a card beside the selection, with a **Copy**
button. It translates into your system language at first; pick another one from the
menu on the card (it translates again) and Glance remembers it for next time. Unlike OCR, this is not offline: the text is sent
to Google through the free `translate.googleapis.com` endpoint that its own web
clients use. It needs no key, but it is undocumented and may be rate limited or
change without notice. Nothing is sent until you click Translate (or press `L`).
A Flatpak build will need network access for it.

The look follows the designs in `docs/designs`; Record is not built yet, so it is not
shown. Translate shows the translated text on a card rather than in place of the
original, as in the design.

A kept capture is saved to
`~/Pictures/Screenshots/Screenshot From <date> <time>.png`.

### Screen capture requirements

On Wayland, Glance takes each monitor at its real resolution through the
ScreenCast portal, using `gst-launch-1.0` with the GStreamer PipeWire plugin
(`gstreamer1.0-pipewire` on Debian and Ubuntu). The first capture asks you to
share your screens; the choice is remembered. Without GStreamer, or when a
monitor sends no frame in time, Glance falls back to the Screenshot portal, where
monitors with a lower scale than the sharpest one look soft. On X11, Qt grabs
each screen directly.

## Tasks

Common commands are defined in `Taskfile.yml` and run with [Task](https://taskfile.dev):

```sh
task run-dev    # run the app
task run-test   # run the tests; extra unittest args go after --, e.g. task run-test -- -k portal
```

## Development checks

Install the Git hooks once:

```sh
uv run pre-commit install
```

Run all checks manually with `uv run pre-commit run --all-files`. The hooks
check whitespace and YAML, JSON, and TOML files; format and lint Python files
with Ruff; then type-check the `src` tree with Pyright. Hook versions are pinned
in `.pre-commit-config.yaml`, and the same tools are available as development
dependencies through `uv`.
