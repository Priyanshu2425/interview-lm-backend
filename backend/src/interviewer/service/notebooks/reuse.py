"""Never embed the same span twice.

An ingest that failed halfway leaves chunks already embedded and already stored.
Resuming it must not pay for them again, and the cheapest way to guarantee that
is content-addressing: a chunk is keyed by the hash of its text, so "have we
embedded this?" is a lookup rather than a judgement.
"""

from __future__ import annotations

from typing import Sequence

from interviewer.adapters.internal.notebook.sources import digest


class ReusingEmbedder:
    """Wraps an Embedder and answers from stored vectors where it can.

    Satisfies the same port, so nothing in the pipeline knows it is there —
    which is what lets the saving apply to every source type and every provider.
    """

    __slots__ = (
        "_inner", "_known", "embedded_texts", "embedded_tokens", "reused",
        "embedded_images",
    )

    def __init__(self, inner, known: dict[str, tuple[float, ...]] | None = None) -> None:
        self._inner = inner
        self._known = known or {}
        self.embedded_texts = 0
        self.embedded_tokens = 0
        self.embedded_images = 0
        self.reused = 0

    @property
    def model_name(self) -> str:
        return getattr(self._inner, "model_name", "unknown")

    @property
    def credits_per_1k_tokens(self) -> float:
        return float(getattr(self._inner, "credits_per_1k_tokens", 0.0) or 0.0)

    @property
    def dim(self) -> int:
        return int(getattr(self._inner, "dim", 0))

    @property
    def supports_images(self) -> bool:
        return bool(getattr(self._inner, "supports_images", False))

    def embed_query(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        """Never reused. A query is asked once and is not stored material."""
        return self._inner.embed_query(texts)

    def embed_images(
        self, images: Sequence[bytes], hashes: Sequence[str] | None = None
    ) -> list[tuple[float, ...]]:
        """The same content-addressed saving, for pixels.

        A figure repeated on forty slides is embedded once — and because the
        hash is also its object key, it is uploaded once too.
        """
        keys = list(hashes) if hashes is not None else [digest(b.hex()) for b in images]
        fresh_pairs = [
            (image, key) for image, key in zip(images, keys) if key not in self._known
        ]
        # Within one call the same figure can appear twice; embed it once.
        seen: dict[str, bytes] = {}
        for image, key in fresh_pairs:
            seen.setdefault(key, image)
        self.reused += len(images) - len(fresh_pairs)
        vectors: dict[str, tuple[float, ...]] = {}
        if seen:
            self.embedded_images += len(seen)
            produced = self._inner.embed_images(list(seen.values()))
            for key, vector in zip(seen, produced):
                vectors[key] = tuple(vector)
        return [
            self._known[k] if k in self._known else vectors[k] for k in keys
        ]

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        hashes = [digest(t) for t in texts]
        fresh = [t for t, h in zip(texts, hashes) if h not in self._known]
        self.reused += len(texts) - len(fresh)
        vectors: dict[str, tuple[float, ...]] = {}
        if fresh:
            self.embedded_texts += len(fresh)
            self.embedded_tokens += sum(len(t) // 4 for t in fresh)
            produced = self._inner.embed(fresh)
            for text, vector in zip(fresh, produced):
                vectors[digest(text)] = tuple(vector)
        return [
            self._known[h] if h in self._known else vectors[h] for h in hashes
        ]
