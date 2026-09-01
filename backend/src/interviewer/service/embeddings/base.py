"""The base every real embedding provider inherits.

The port lives in `corpus/adapters/notebook/embedding.py` and is structural, so
that the hashing stub and the reuse decorator can satisfy it without carrying a
model. This is the other half: a provider inherits from here and writes one
method, and gets batching, retries, deadlines, validation, normalisation,
accounting and locking without writing any of them.

The rule that keeps it honest: nothing in this module knows what a chunk is, and
nothing in the pipeline knows this module exists. `api/deps.py` is the only
place the two meet.
"""

from __future__ import annotations

import math
import random
import threading
import time
from abc import ABC, abstractmethod
from typing import ClassVar, Sequence

from .errors import EmbeddingContractError, EmbeddingTimeout, UnsupportedModality

#: Retried, because they are a statement about this moment. Anything else is a
#: statement about the request, and asking again gets the same answer.
TRANSIENT = (EmbeddingTimeout,)


class BaseEmbedder(ABC):
    """Content in, unit vectors out, with the machinery a provider should not rewrite.

    A subclass supplies `_encode_texts`, and `_encode_images` if it has an image
    tower. Everything else is inherited and identical across providers, which is
    the point: a second provider is the encode call and nothing else.
    """

    #: How the registry names it, and the first field of `model_name`.
    provider: ClassVar[str] = "base"
    supports_images: ClassVar[bool] = False

    def __init__(
        self,
        *,
        model: str,
        dim: int,
        revision: str = "",
        batch_size: int = 32,
        timeout: float = 30.0,
        max_retries: int = 3,
        credits_per_1k_tokens: float = 0.0,
    ) -> None:
        self.model = model
        self.dim = dim
        self.revision = revision
        self.batch_size = max(1, batch_size)
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.credits_per_1k_tokens = credits_per_1k_tokens
        self._lock = threading.Lock()
        self._warm = False
        self._calls = 0
        self._failures = 0
        self._items = 0
        self._latencies: list[float] = []

    # -- identity ------------------------------------------------------------

    @property
    def model_name(self) -> str:
        """One string that identifies the whole space.

        Provider, model, width and revision together, because each of them can
        move the vectors: the same checkpoint at a different revision is a
        different space, and a notebook embedded in it needs re-embedding rather
        than a shrug. It is what `notebook.embedding_model` stores.
        """
        base = f"{self.provider}:{self.model}@{self.dim}"
        return f"{base}#{self.revision[:12]}" if self.revision else base

    # -- the port ------------------------------------------------------------

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        """Document-side embedding, in input order."""
        return self._run(list(texts), self._encode_texts, blank=str.strip)

    def embed_query(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        """Query-side embedding. Identical unless a subclass says otherwise."""
        return self.embed(texts)

    def embed_images(
        self, images: Sequence[bytes], hashes: Sequence[str] | None = None
    ) -> list[tuple[float, ...]]:
        """`hashes` is accepted and ignored: it is the reuse decorator's business."""
        if not self.supports_images:
            raise UnsupportedModality(
                f"{self.provider} has no image tower",
                provider=self.provider, model=self.model,
            )
        return self._run(list(images), self._encode_images, blank=lambda b: b)

    # -- what a subclass writes ----------------------------------------------

    @abstractmethod
    def _encode_texts(self, batch: Sequence[str]) -> list[Sequence[float]]:
        """One batch, already non-empty and already deduplicated of blanks."""

    def _encode_images(self, batch: Sequence[bytes]) -> list[Sequence[float]]:
        raise UnsupportedModality(
            f"{self.provider} has no image tower",
            provider=self.provider, model=self.model,
        )

    # -- lifecycle -----------------------------------------------------------

    def warm(self) -> None:
        """Do the expensive part now, so the first Candidate does not wait for it."""
        self._warm = True

    def close(self) -> None:
        self._warm = False

    def health(self) -> dict:
        latencies = sorted(self._latencies)
        return {
            "model": self.model_name,
            "provider": self.provider,
            "dim": self.dim,
            "warm": self._warm,
            "supports_images": self.supports_images,
            "calls": self._calls,
            "failures": self._failures,
            "items": self._items,
            "p50_ms": _percentile(latencies, 0.50),
            "p99_ms": _percentile(latencies, 0.99),
        }

    # -- the machinery -------------------------------------------------------

    def _run(self, items: list, encode, *, blank) -> list[tuple[float, ...]]:
        """Batch, retry, validate, normalise — in input order, always.

        Order is a contract rather than a convenience: the pipeline zips these
        vectors against its chunks positionally, so a reordered result would
        attach every embedding to the wrong span and nothing would fail loudly.
        """
        if not items:
            return []

        # An empty string has no direction. It is the zero vector by definition,
        # and sending it to a provider buys a fabricated one at full price.
        live = [i for i, item in enumerate(items) if blank(item)]
        out: list[tuple[float, ...]] = [(0.0,) * self.dim] * len(items)

        for start in range(0, len(live), self.batch_size):
            window = live[start:start + self.batch_size]
            batch = [items[i] for i in window]
            vectors = self._attempt(encode, batch)
            if len(vectors) != len(batch):
                raise EmbeddingContractError(
                    f"{self.provider} returned {len(vectors)} vectors for "
                    f"{len(batch)} inputs",
                    provider=self.provider, model=self.model,
                )
            for index, vector in zip(window, vectors):
                out[index] = self._validated(vector)
        return out

    def _attempt(self, encode, batch: list) -> list[Sequence[float]]:
        """Retry what this moment caused; never retry what the request caused."""
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            started = time.monotonic()
            try:
                # One model, several threads: FastAPI serves sync endpoints from
                # a threadpool, and a torch module under MPS is not reliably
                # re-entrant.
                with self._lock:
                    vectors = encode(batch)
            except TRANSIENT as exc:
                last = exc
                self._failures += 1
                if attempt == self.max_retries:
                    break
                # Jittered, so several workers recovering together do not
                # synchronise into a second stampede.
                delay = min(8.0, 2.0 ** attempt) * (0.5 + random.random() / 2)
                time.sleep(delay)
                continue
            except Exception:
                self._failures += 1
                raise
            self._calls += 1
            self._items += len(batch)
            self._record(time.monotonic() - started)
            return vectors
        assert last is not None
        raise last

    def _validated(self, vector: Sequence[float]) -> tuple[float, ...]:
        if len(vector) != self.dim:
            raise EmbeddingContractError(
                f"{self.provider}:{self.model} returned {len(vector)} dimensions, "
                f"expected {self.dim}",
                provider=self.provider, model=self.model,
            )
        values = [float(v) for v in vector]
        if not all(math.isfinite(v) for v in values):
            # A NaN reaching a centroid freezes into a Topic that matches
            # nothing forever, and nothing about the symptom points back here.
            raise EmbeddingContractError(
                f"{self.provider}:{self.model} returned a non-finite vector",
                provider=self.provider, model=self.model,
            )
        return normalise(values)

    def _record(self, seconds: float) -> None:
        self._latencies.append(seconds * 1000.0)
        if len(self._latencies) > 512:
            del self._latencies[:256]


def normalise(values: Sequence[float]) -> tuple[float, ...]:
    """Unit length, always, even when the model swears it already did.

    Cosine is then a dot product, and `centroid_of` averaging unit vectors means
    what the clusterer assumes it means.
    """
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0.0:
        return tuple(values)
    return tuple(v / norm for v in values)


def _percentile(ordered: list[float], q: float) -> float | None:
    if not ordered:
        return None
    index = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return round(ordered[index], 2)
