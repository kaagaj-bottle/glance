# Glance

A Linux desktop app for capturing and understanding what is on your screen. It is a
screenshot and screen-recording tool with OCR, translation, visual search, QR code and
color tools, and a library you can search by words or by what a screenshot looks like.
It works on a selected area or a whole monitor. Wayland is the main target; X11 also works.

## Quick start

You need Linux, [`uv`](https://docs.astral.sh/uv/) and Python 3.13 (`uv` fetches it if
missing). For Wayland capture and recording, install GStreamer with the PipeWire plugin:

```sh
# Debian / Ubuntu
sudo apt install gstreamer1.0-tools gstreamer1.0-pipewire gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-ugly
```

Then, from the project root:

```sh
uv run glance
```

The first run installs the dependencies and asks you to share your screens (the choice is
remembered). It also asks for a Groq API key; **Skip** it and everything except Translate
and Explain still works (see [AI features](#ai-features)).

## Using it

Glance takes a screenshot and shows it full-screen so you can choose what to keep.

- **Drag** to select an area; drag corners or edges to resize. **Selection** / **Screen**
  in the bottom bar switch between an area and a whole monitor.
- **Done** (`Enter`) copies and saves. **Copy** (`C`) only copies, **Save** (`S`) only
  saves, `Esc` cancels. Saved to `~/Pictures/Screenshots/`.
- **OCR:** text in the selection is tinted and counted (**Aa 42 words**). Drag over words
  to pick them, then **Copy** (`T`), **Translate** (`L`), **Web search** (`V`) or
  **Explain** (`E`). Links and emails get **Open link** / **Email** buttons. OCR is offline
  ([RapidOCR](https://github.com/RapidAI/RapidOCR)).
- **QR codes and barcodes** are read offline; click the pill or press `Q` to open a link,
  join Wi-Fi, add a contact or event, and so on. Nothing happens until you choose it.
- **Visual search** (`I`): upload the selection to Google Lens, Yandex Images or Bing and
  see results in your browser. Nothing is sent until you pick an engine.
- **Colors** (`K`): main colors of the selection, or an eyedropper for any pixel.
- **Record** (`R`): records the selection or monitor to
  `~/Videos/Screencasts/` (no audio yet). Click **Stop** or press `Esc`.
- **Ctrl+C** in the terminal closes Glance; during a recording it stops and keeps the video.

## Library: search your screenshots

Off by default, because it stores the text of what you capture. It is local; the only
network use is a one-time model download.

```sh
uv run glance library on              # add each screenshot saved from now on
uv run glance library index           # read the text and pictures not read yet
uv run glance library open            # window with a search box (also the Library button, F)
uv run glance library search a terminal showing an error
uv run glance library status
```

A search shows the top three: captures containing every word you typed, then captures that
look most like it. Search by meaning uses [CLIP](https://openai.com/index/clip/)
(ViT-B/32, ~156 MB from Hugging Face), downloaded once into `~/.local/share/Glance/clip`
the first time you index or press **Download the model**. The index is
`~/.local/share/Glance/library.db`; deleting it never deletes images.

## AI features

**Translate** (`L`) and **Explain** (`E`) use models hosted by [Groq](https://groq.com).
Get a free key at [console.groq.com/keys](https://console.groq.com/keys), then either
paste it when Glance asks, run `uv run glance key`, or set `GROQ_API_KEY`. The key is
saved to `~/.config/glance/groq_key` (readable by you only). Without one, those two
buttons are dimmed; everything else works.

| Feature | Model | License | Sends |
| --- | --- | --- | --- |
| Translate | [`openai/gpt-oss-120b`](https://huggingface.co/openai/gpt-oss-120b) | Apache 2.0 | the picked text (max 8000 chars) |
| Explain text | [`openai/gpt-oss-20b`](https://huggingface.co/openai/gpt-oss-20b) | Apache 2.0 | the picked text |
| Explain image | [`qwen/qwen3.8-27b`](https://huggingface.co/Qwen/Qwen3.8-27B) (preview) | Apache 2.0 | the selection, scaled to 1280 px |

All three models are open-weight; Groq's hosted API is what runs them, and it is not
open source. Nothing is sent until you click or press the key. Model names are in
`src/glance/ai/models.py`.

## What stays local

| Kind | Features |
| --- | --- |
| Local, offline | screenshots, recording, OCR, QR codes, colors, library (after model download) |
| Web, no key | Visual search, Web search (open your browser) |
| Groq key | Translate, Explain |

## Limitations

- No recording audio, pause, or global stop shortcut yet.
- No Flatpak packaging yet; `TODO.md` lists the sandbox problems to solve first.
- Visual search upload endpoints are undocumented and may change or be rate limited.
- Windows is out of scope for now.

## Development

```sh
task run-test                      # tests (or: uv run python -m unittest discover -s src -t src)
uv run pre-commit install          # once; then Ruff and Pyright run on each commit
uv run pre-commit run --all-files  # run all checks by hand
```

## AI usage disclosure

**AI inside the app.** Glance sends AI output to Groq-hosted models only for Translate and
Explain, and the app uses the output programmatically in these places:

- `GroqTranslator.translate` and `parse` in `src/glance/ai/translate.py`: the model is
  asked to reply with a first line `LANG: <code>` followed by the translation. `parse`
  splits the reply into the detected source language (shown as the card's "from" label in
  `src/glance/ui/translation.py`) and the translated text, which becomes the `Translation`
  object shown and copied from the card.
- `GroqExplainer.explain` and `explain_image` in `src/glance/ai/explain.py`: the reply is
  displayed as the explanation card text.
- `chat` and `parse` in `src/glance/ai/client.py`: the shared Groq request and response
  extraction used by both.

The library's search by meaning (`src/glance/library/clip.py`, `ClipEmbedder`) runs a
CLIP model locally; its image and text embeddings are compared to rank results. OCR and
QR decoding use local models too and call no external AI service.

**AI used to build it.** The code was written with the help of Claude Code (Anthropic),
under the author's direction and review. Commits made with it carry a `Co-Authored-By`
line.
