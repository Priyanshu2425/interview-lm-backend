"""SigLIP 2, embedding prose and figures into one space.

The model is a dual encoder: a text tower and an image tower trained against
each other, so a paragraph and the diagram it describes land near each other in
the same 768 dimensions. That is why one provider serves both modalities here,
and why a figure can be a row in the chunk table rather than a parallel system.

The awkward part is the text tower's 64-token limit, and §Window pooling below
is the whole answer to it.
"""

from __future__ import annotations

import io
import logging
import os
from typing import ClassVar, Sequence

from interviewer.adapters.s3 import ModelSpec, ensure_local
from .base import BaseEmbedder, normalise
from .errors import EmbeddingContractError, EmbeddingUnavailable
from .registry import register

log = logging.getLogger(__name__)

#: What the text tower accepts. Not a tuning knob — it is the trained position
#: count, and asking for more silently changes what the model was taught.
CONTEXT_TOKENS = 64

#: A chunk longer than this many windows is an upstream bug, not something to
#: spend on quietly. At 64 tokens a window, this is ~8k tokens: well past the
#: 500–800 a chunk is supposed to be.
MAX_WINDOWS = 32


@register("siglip")
class SiglipEmbedder(BaseEmbedder):
    """Both towers of one checkpoint, behind the one port."""

    default_model: ClassVar[str] = "google/siglip2-base-patch16-224"
    supports_images: ClassVar[bool] = True

    def __init__(self, *, device: str = "auto", max_windows: int = MAX_WINDOWS, **kw):
        super().__init__(**kw)
        self._device_preference = device
        self.max_windows = max_windows
        self._model = None
        self._processor = None
        self._tokenizer = None
        self._torch = None
        self.device = "cpu"

    @classmethod
    def options_from(cls, env: dict) -> dict:
        return {
            "device": env.get("EMBEDDING_DEVICE") or "auto",
            "max_windows": int(env.get("EMBEDDING_MAX_WINDOWS") or MAX_WINDOWS),
        }

    # -- lifecycle -----------------------------------------------------------

    def warm(self) -> None:
        """Load the weights. Imports torch, and nothing before this point does.

        Deliberately not at module import: the default deployment runs the
        hashing stub, and the test suite must never pay 2.5GB of wheels to
        assert something about chunking.
        """
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModel, AutoProcessor, AutoTokenizer
        except ModuleNotFoundError as exc:  # pragma: no cover - optional extra
            raise EmbeddingUnavailable(
                "siglip needs the 'embeddings' extra "
                "(pip install -e backend[embeddings])",
                provider=self.provider, model=self.model,
            ) from exc

        source = self._weights()
        log.info("loading %s from %s", self.model, source)
        self._torch = torch
        self.device = _device(torch, self._device_preference)
        dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        self._model = AutoModel.from_pretrained(source, dtype=dtype).to(self.device)
        self._model.eval()
        self._processor = AutoProcessor.from_pretrained(source)
        self._tokenizer = AutoTokenizer.from_pretrained(source)

        width = int(getattr(self._model.config, "projection_dim", 0) or 0)
        if width and width != self.dim:
            raise EmbeddingContractError(
                f"{self.model} emits {width} dimensions, configured for {self.dim}",
                provider=self.provider, model=self.model,
            )
        super().warm()

    def _weights(self) -> str:
        """Local weights where S3 is configured, the hub id otherwise."""
        spec = ModelSpec.from_env()
        if spec is not None and spec.repo_id == self.model:
            return str(ensure_local(spec))
        if os.environ.get("MODEL_BUCKET"):
            log.warning(
                "MODEL_BUCKET is set but EMBEDDING_REVISION is not; "
                "falling back to the hub for %s", self.model,
            )
        return self.model

    def close(self) -> None:
        self._model = self._processor = self._tokenizer = None
        super().close()

    # -- text ----------------------------------------------------------------

    def _encode_texts(self, batch: Sequence[str]) -> list[Sequence[float]]:
        """Window pooling — the reason a 64-token tower can embed a 700-token chunk.

        Truncating would keep the first ~250 characters of a chunk and throw the
        rest away, and every downstream number — the cluster it joins, the Topic
        it becomes, the span a citation points at — would be computed from that
        tenth. So the chunk is cut into consecutive windows, every window is
        embedded, and the windows are averaged back into one vector.

        The windows of every text in the batch go through the tower as a single
        pass. A 12-window chunk is one forward call, not twelve.
        """
        self.warm()
        torch = self._torch

        windows: list[list[int]] = []
        spans: list[tuple[int, int]] = []
        for text in batch:
            start = len(windows)
            windows.extend(self._windows(text))
            spans.append((start, len(windows)))

        vectors = []
        for begin in range(0, len(windows), self.batch_size):
            vectors.extend(self._encode_windows(windows[begin:begin + self.batch_size]))

        out: list[Sequence[float]] = []
        for start, end in spans:
            group = vectors[start:end]
            if not group:
                out.append([0.0] * self.dim)
                continue
            pooled = [sum(axis) / len(group) for axis in zip(*group)]
            out.append(normalise(pooled))
        return out

    def _windows(self, text: str) -> list[list[int]]:
        """Consecutive ≤64-token pieces, covering the whole text."""
        ids = self._tokenizer(text, add_special_tokens=False)["input_ids"]
        if not ids:
            return []
        size = CONTEXT_TOKENS
        pieces = [ids[i:i + size] for i in range(0, len(ids), size)]
        if len(pieces) > self.max_windows:
            raise EmbeddingContractError(
                f"a {len(ids)}-token input needs {len(pieces)} windows, over the "
                f"{self.max_windows} allowed; chunking should have divided it",
                provider=self.provider, model=self.model,
            )
        return pieces

    def _encode_windows(self, windows: list[list[int]]) -> list[list[float]]:
        torch = self._torch
        texts = [self._tokenizer.decode(w) for w in windows]
        # `padding="max_length"` is what SigLIP was trained with. Dynamic
        # padding produces different vectors for the same text, quietly.
        inputs = self._processor(
            text=texts,
            padding="max_length",
            max_length=CONTEXT_TOKENS,
            truncation=True,
            return_tensors="pt",
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.inference_mode():
            features = self._model.get_text_features(**inputs)
        return _vectors(features)

    # -- images --------------------------------------------------------------

    def _encode_images(self, batch: Sequence[bytes]) -> list[Sequence[float]]:
        self.warm()
        torch = self._torch
        try:
            from PIL import Image, ImageOps
        except ModuleNotFoundError as exc:  # pragma: no cover - optional extra
            raise EmbeddingUnavailable(
                "image embedding needs Pillow (the 'embeddings' extra)",
                provider=self.provider, model=self.model,
            ) from exc

        images = []
        for data in batch:
            try:
                image = Image.open(io.BytesIO(data))
                image.load()
            except Exception as exc:
                # A vector derived from noise is worse than no figure at all:
                # it would attach a citation to a page for no reason.
                raise EmbeddingContractError(
                    f"figure could not be decoded: {type(exc).__name__}",
                    provider=self.provider, model=self.model,
                ) from exc
            images.append(ImageOps.exif_transpose(image).convert("RGB"))

        inputs = self._processor(images=images, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.inference_mode():
            features = self._model.get_image_features(**inputs)
        return _vectors(features)


def _vectors(features) -> list[list[float]]:
    """The pooled embedding, whichever shape the library hands it back in.

    transformers 4.x returned a tensor from `get_*_features`; 5.x returns an
    output object carrying `pooler_output` beside the full hidden states. Taking
    `last_hidden_state` by mistake would yield one vector per *token* — a shape
    error at best, and at worst a plausible vector that means nothing.
    """
    tensor = getattr(features, "pooler_output", None)
    if tensor is None:
        tensor = features
    if tensor.dim() != 2:
        raise EmbeddingContractError(
            f"expected pooled vectors, got a tensor of rank {tensor.dim()}"
        )
    return tensor.float().cpu().tolist()


def _device(torch, preference: str) -> str:
    if preference and preference != "auto":
        return preference
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"
