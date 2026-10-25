# Glance

Glance is a Linux desktop app for capturing and understanding what is on your screen. It combines a familiar screenshot tool with OCR, translation, visual search, and QR code and color tools, so you can act on content without leaving the capture workflow. It works on a selected area or on a whole monitor.

## Status

Working today: screenshots (area and whole monitor), screen recording, OCR with selectable words, translation, visual search, link and email actions, QR code and barcode actions, and a color picker and palette. Wayland is the main target; X11 also works.

Not built yet:

- **Recording audio, pause, and a global stop shortcut.**
- **Flatpak packaging.** Flatpak is the intended distribution format, but there is no manifest yet. `TODO.md` lists the sandbox problems to solve first.

Windows support may be considered later; the current focus is Linux. Ideas for further features are in `docs/research/lens-like-features.md`.

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
- **Visual search** (`I`) offers Google Lens, Yandex Images and Bing Visual Search. Pick one
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
  bubble then offers **Copy**, **Translate**, **Web search** (opens a web search in your
  browser) and **Explain** for the picked words. `T` or `Ctrl+C` copies, `L`
  translates, `V` searches the web and `E` explains the text without the bubble;
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
  appears beside the size; click it (or press `Q`) to choose what to do. Every code can
  be copied, and some offer more, but nothing happens until you choose it:
  - a web link or `mailto:` address: **Open link** or **Email** (only when the whole
    code is one, since a code can say anything);
  - a Wi-Fi network (`WIFI:…`): **Connect to "name"**, plus **Copy network name** and
    **Copy password**. Connecting saves the network in NetworkManager and starts
    joining it, and a desktop notification says it began (or why it could not).
    Open, WEP, WPA and WPA3 networks work; enterprise (EAP) networks can only be copied;
  - a location (`geo:lat,lon`): **Open map** (OpenStreetMap) and **Copy coordinates**;
  - a contact (vCard or `MECARD:`): **Add to contacts**, **Copy contact**, or copy each
    phone or email;
  - a calendar event (`BEGIN:VEVENT`, bare or in a `VCALENDAR`): **Add to calendar**,
    **Copy event** and **Copy location**;
  - a product barcode (EAN, UPC, ISBN): **Search** the number on the web.

  **Add to contacts** and **Add to calendar** write a `.vcf` or `.ics` file to
  `~/.cache/Glance/documents` and open it in your contacts or calendar app, which then
  asks you to import it. Glance builds that file itself from the name, numbers, dates and
  so on it read, rather than passing the code's own text on; an event with dates or
  time zones it cannot read safely can only be copied. Files older than a day are
  removed the next time one is written. If nothing on your system opens them, Glance
  says so and tells you where the file is.

  Codes are also looked for on each whole monitor in the background, so in Screen mode
  the same pill appears in the corner of the monitor under the pointer; click it (or press
  `Q`) rather than the monitor.
- **Colors** (`K`) in the bottom bar lists the main colors of the selection (or of the
  monitor, in Screen mode) with how much of it each covers; pick one to copy its
  `#RRGGBB` value. **Pick from the screen…** turns the pointer into an eyedropper: click
  any pixel, on any monitor, to copy its exact color. `Esc` leaves the eyedropper
  without closing Glance. The Colors button is an addition to the designs in
  `docs/designs`.
- **Ctrl+C** in the terminal that started Glance closes it. During a recording it stops
  the recording first, so the video is kept; a second Ctrl+C quits at once.

### What is local, what opens your browser, what needs a key

Glance sorts its features into three kinds, and marks the ones that send something
away with a small cloud.

- **Local, always on, offline:** screenshots, recording, OCR, QR codes and barcodes,
  colors, links, Wi-Fi codes. Nothing leaves your computer.
- **Web, no key:** **Visual search** (the image) and **Web search** (the picked words)
  hand their content to a search engine and open the results in your browser.
- **AI, one key:** **Translate** and **Explain** are answered by models hosted by
  [Groq](https://groq.com). The only setup Glance has is a free API key from
  [console.groq.com/keys](https://console.groq.com/keys).

The first time Glance starts without a key it asks for one; **Skip** is remembered and
everything local and web keeps working. `uv run glance key` opens the same window to
add or change the key later. Without a key, Translate and Explain are dimmed and say so
when clicked, rather than failing after the click. The key is checked with Groq and
saved to `~/.config/glance/groq_key`, readable by you only. `GROQ_API_KEY` in the
environment takes precedence, which is handy for development.

Nothing is sent until you click a button or press its key.

**Translate** (`L`) shows the translation on a card beside the selection, with a
**Copy** button. It translates into your system language at first; pick another one from
the menu on the card (it translates again) and Glance remembers it for next time. It
uses `openai/gpt-oss-120b`, which copes with slang, context and OCR slips. Text over
8000 characters is refused rather than cut short. The answer's card says it was sent to
Groq.

**Explain** (`E`) explains what you selected, always in English, on a card with a
**Copy** button. It sends the picked words if any are picked (`openai/gpt-oss-20b`,
cut to the first 8000 characters); otherwise it sends the selected image, or the
monitor in Screen mode, scaled down to 1280 pixels on its longer side, and no text
(`qwen/qwen3.8-27b`, which Groq lists as a preview model, so it may change or
disappear). The image goes up as a screenshot, so check it first for anything private.
The bubble's **Explain** always explains words, the picked ones or all of them. The
card says whether it explained the text or the image. The model names live in
`src/glance/ai/models.py`.

**Record** (`R`) records the selection (or, in Screen mode, the monitor) to a video
file. Glance closes the capture screen and a dashed red frame marks the selection, with
a bar centered under its bottom border showing a timer and a red **Stop** button. The
bar has a dark red tint so it shows on any background. The video has no sound yet and
includes the mouse pointer. It is saved to
`~/Videos/Screencasts/Screencast From <date> <time>.mp4` and a notification says
so. A selection that spans monitors records only the part on the monitor that holds
most of it. The first recording asks you to share your screens, like the first
capture. Record is a button in the bar rather than the Capture/Record switch in the
designs.

The frame and the bar sit just outside the area, so they are not in the video. When
there is no room below the area they go above it, and for a whole monitor, which has
no outside, the bar is inside it at the bottom, so it is in the video, and there is no
frame. Wayland does not let an app place a window, and a full-screen one would blank
the recording, so a small helper process draws them through XWayland. Without X11 (no
`DISPLAY`), or if the helper dies, a plain bar with a timer and Stop appears wherever
your desktop puts it instead (drag it; `Esc`, `Enter` and `Space` also stop), and
there is no frame. You can also stop a recording from your desktop's own screen-sharing
indicator.

The look follows the designs in `docs/designs`. Translate shows the translated text on a card rather than in place of the
original, as in the design.

A kept capture is saved to
`~/Pictures/Screenshots/Screenshot From <date> <time>.png`.

### Screen capture requirements

Recording encodes in a separate `gst-launch-1.0` process, with the capture, conversion and
encoding on threads of their own, so it does not slow down the app. It uses the best
encoder installed: H.264 from x264 (`gstreamer1.0-plugins-ugly`) in an MP4 file, which is
the fastest and gives the smallest files; else H.264 from OpenH264 (`gstreamer1.0-plugins-bad`),
also MP4; else VP8 in a WebM file (`gstreamer1.0-plugins-good`). x264 keeps a constant
quality, so a still screen costs almost nothing. The MP4 index is written as it goes, so a
recording that is cut short still plays. At a high resolution the machine has to keep up:
full 1440p at 30 frames a second needs a few free CPU cores, and frames are dropped (and the
previous one repeated) if it does not.

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
