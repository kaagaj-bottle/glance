# pyright: basic
"""Meaning-based search: a CLIP model that puts images and sentences in one space.

CLIP turns an image and a sentence into vectors that are close when the sentence
describes the image, so a query can be matched against screenshots without reading
their text. The model is downloaded once, the first time it is wanted, and runs
offline from then on (ViT-B/32, 8-bit, ONNX files published by Xenova on Hugging Face).
"""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt
import onnxruntime
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from tokenizers import Tokenizer

BASE_URL = "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/"
FILES = (
    "tokenizer.json",
    "onnx/text_model_quantized.onnx",
    "onnx/vision_model_quantized.onnx",
)
DOWNLOAD_MEGABYTES = 156
SIZE = 224
CONTEXT = 77  # CLIP reads at most this many tokens of a sentence
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

Vector = npt.NDArray[np.float32]


class Embedder(Protocol):
    def embed_image(self, image: QImage) -> Vector: ...

    def embed_text(self, text: str) -> Vector: ...


def model_dir() -> Path:
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data) / "Glance" / "clip"


def is_downloaded(folder: Path) -> bool:
    return all((folder / name).is_file() for name in FILES)


def download(
    folder: Path,
    fetch: Callable[[str, Path], None] | None = None,
) -> None:
    """Fetch the model files that are missing into `folder`.

    Each file is written under a temporary name and moved into place when whole, so
    an interrupted download is never mistaken for a model.
    """
    fetch = fetch or _fetch
    for name in FILES:
        target = folder / name
        if target.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        fetch(BASE_URL + name, partial)
        partial.replace(target)


def _fetch(url: str, destination: Path) -> None:
    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
        with open(destination, "wb") as file:
            while chunk := response.read(1 << 20):
                file.write(chunk)


def normalize(vector: npt.NDArray[np.float32]) -> Vector:
    """The vector scaled to length 1, so a dot product is the cosine similarity."""
    length = float(np.linalg.norm(vector))
    return (vector / length if length else vector).astype(np.float32)


def preprocess(image: QImage) -> npt.NDArray[np.float32]:
    """The image as the (1, 3, 224, 224) array CLIP expects.

    The whole screenshot is squeezed into the square rather than cropped to its
    middle: a wide screen would otherwise lose its sides, which hold sidebars and
    tabs. CLIP copes with the stretch well enough for a rough match.
    """
    scaled = image.convertToFormat(QImage.Format.Format_RGB888).scaled(
        SIZE,
        SIZE,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    rows = np.frombuffer(scaled.constBits(), dtype=np.uint8).reshape(
        SIZE, scaled.bytesPerLine()
    )
    pixels = rows[:, : SIZE * 3].reshape(SIZE, SIZE, 3).astype(np.float32) / 255.0
    return ((pixels - MEAN) / STD).transpose(2, 0, 1)[np.newaxis].astype(np.float32)


class ClipEmbedder:
    """Embeds images and text with the downloaded model. Loads it on first use."""

    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._text: onnxruntime.InferenceSession | None = None
        self._vision: onnxruntime.InferenceSession | None = None
        self._tokenizer: Tokenizer | None = None

    def embed_image(self, image: QImage) -> Vector:
        if self._vision is None:
            self._vision = _session(self._folder / FILES[2])
        output = self._vision.run(None, {"pixel_values": preprocess(image)})[0]
        return normalize(np.asarray(output, dtype=np.float32)[0])

    def embed_text(self, text: str) -> Vector:
        if self._text is None:
            self._text = _session(self._folder / FILES[1])
        if self._tokenizer is None:
            self._tokenizer = Tokenizer.from_file(str(self._folder / FILES[0]))
            self._tokenizer.enable_truncation(CONTEXT)
        ids = np.array([self._tokenizer.encode(text).ids], dtype=np.int64)
        output = self._text.run(None, {"input_ids": ids})[0]
        return normalize(np.asarray(output, dtype=np.float32)[0])


def _session(path: Path) -> onnxruntime.InferenceSession:
    return onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
