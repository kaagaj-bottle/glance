# Google Lens-like features for Glance

Ideas for features that fit Glance's capture-first workflow: select an area (or the whole screen), then act on what is in it. Each feature starts from a captured image, so none of them need a separate camera or file-picker flow.

Effort is a rough guess: **S** is days, **M** is a week or two, **L** is longer or needs a new dependency or service.

## Core (matches the project goals)

| Feature | What it does | Possible approach | Effort |
| --- | --- | --- | --- |
| OCR / copy text | Extract text from the selection and copy it, or select individual words on the frozen screenshot. | Tesseract (`tesseract` binary or `tesserocr`), or RapidOCR / PaddleOCR (ONNX) for better accuracy. Needs word bounding boxes to overlay selectable text. | M |
| Translate | Translate the recognized text, optionally drawn back over the image in place. | OCR first. Online: DeepL or Google Translate API. Offline: Argos Translate or Bergamot (the engine behind Firefox Translations). In-place overlay needs the OCR boxes plus text re-rendering. | M–L |
| Visual search | Find where an image, or a part of it, appears on the web and find similar images. | Reverse image search; see the provider options below. | M |

## Text-based extras (cheap once OCR exists)

- **Smart actions on recognized text.** Detect URLs, emails, phone numbers, addresses, dates and tracking numbers, then offer open / copy / call / add to calendar. Plain regexes cover most of it. **S**
- **Copy as structured text.** Keep line breaks and column order, strip hyphenation, and offer "copy as single line". **S**
- **Search selected text.** Send the recognized text to a search engine or dictionary. **S**
- **Define / explain.** Look up a word in a local dictionary (e.g. WordNet or Wiktionary dumps), or ask an LLM to explain a snippet. **S–M**
- **Table extraction.** Detect a table in the selection and copy it as CSV or Markdown. Needs a layout or table model (e.g. Table Transformer) or heuristics on OCR boxes. **L**
- **Handwriting recognition.** Same flow as OCR with a handwriting-capable model (TrOCR). Accuracy varies a lot. **L**
- **Math to LaTeX.** Recognize equations in the selection and copy LaTeX (pix2tex or similar). **M**
- **Code snippets.** Detect code in a screenshot and copy it with indentation preserved. This is OCR plus post-processing. **M**

## Image-based features

- **Reverse image search.** Upload the selection to a search service and open the results page. See providers below. **M**
- **Object and product identification.** Label what is in the selection (plant, animal, landmark, product). Use a vision-language model, or a dedicated classifier for narrow cases. **M–L**
- **Shopping search.** Reverse image search filtered to product results. This is only practical through a paid API or a provider that exposes shopping matches. **M**
- **Similar images.** Show visually similar images next to the result. This comes with most reverse-image providers. **M**
- **Color picker and palette.** Sample a pixel, or extract a palette from the selection. It needs no network and is a good small first feature. **S**
- **QR code and barcode scanning.** Decode and offer to open or copy the contents. `zxing-cpp` or `pyzbar` handle it. **S**
- **Background removal.** Cut out the subject and copy it with a transparent background (rembg / U²-Net / SAM). **M**
- **Face blur / redaction.** Detect faces, emails, and numbers, and blur them before saving or sharing. Pairs well with the OCR smart actions. **M**

## Ask about the selection (LLM-powered)

A vision-capable model turns the selection into a question-answering surface, which is the part of Lens that has grown the most in recent years:

- "What is this?" / "Describe this image."
- "Explain this error message / chart / diagram."
- "Summarize this text."
- "Translate and explain the idioms."
- Free-form follow-up questions in a small chat panel attached to the capture.

This could use a hosted API (e.g. Claude) or a local model through Ollama / llama.cpp. If it is added, make the provider configurable, since sending screen contents to a third party has privacy implications (see below).

## Reverse image search providers

| Provider | Access | Notes |
| --- | --- | --- |
| Google Lens | Upload to `lens.google.com` and open the results in a browser | No official API. The upload endpoint is undocumented and may change or add bot checks. Opening it in the browser is the least fragile option. |
| Google Cloud Vision, Web Detection | Official API, paid per request | Returns web entities, matching pages and visually similar images. This is what `image-search.md` in this folder refers to. Needs a Google Cloud project and credentials. |
| SerpApi (Google Lens engine) | Paid third-party API | Returns Lens-like results as JSON without scraping. |
| Bing Visual Search | Microsoft API | Check current availability and terms before relying on it. |
| TinEye | Paid API, or browser upload | Good for finding the original source of an image. |
| Yandex Images | Browser upload | Strong at finding faces and similar images, but no stable API. |
| SauceNAO / IQDB | Free API with limits | Specialized in anime and artwork. |

A simple design is a "Search with…" menu that uploads the capture to the chosen service and opens the results in the default browser, rather than rendering results inside Glance. That avoids building a results UI and avoids most API-terms issues.

## Suggested order

1. **OCR and copy text.** Unlocks the most features and fits the existing overlay.
2. **Smart actions** and **QR scanning.** Small and useful, and they validate the OCR plumbing.
3. **Translate.** Start with a text-only result panel, then add the in-place overlay.
4. **Visual search** through a "Search with…" menu that opens the browser.
5. **LLM "ask about this"**, with a configurable provider.
6. Everything else, driven by what users ask for.

## Constraints and open questions

- **Privacy.** Screenshots often contain passwords, messages, and personal data. Anything that uploads an image should be opt-in, show where it is sending the data, and never run automatically on capture. Offline OCR and translation should be the default where quality allows.
- **Flatpak.** Network access, bundled models, and any external binaries (e.g. `tesseract`) have to be declared and packaged. Model files can be large, so downloading on first use may be better than shipping them.
- **Dependencies.** The project currently depends only on `jeepney` and `pyside6`. Each feature above adds something (an OCR engine, a model runtime, an HTTP client). Choose one OCR engine and one runtime rather than several.
- **Where results appear.** The capture overlay already shows the selection. Decide whether OCR text is drawn on the frozen screenshot (like Lens) or shown in a side panel.
- **Language packs.** OCR and offline translation both need per-language data. Decide how users pick and install languages.
- **Cost.** Hosted APIs charge per request, so a bring-your-own-key setting is probably needed.
