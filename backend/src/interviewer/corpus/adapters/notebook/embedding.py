"""The embedding port, and an implementation that needs no provider.

ADR-0005 refuses a vector store *in the interview loop*; ADR-0015 adds one
alongside, for deriving Topics at ingest and citing spans at read time. Nothing
here calls a network. The real provider arrives in ISSUE-0026 through this same
port, which is the point of it being a port.
"""

from __future__ import annotations

import math
import re
from typing import Protocol, Sequence, runtime_checkable

#: Wide enough that two passages are similar because they share vocabulary, not
#: because they collided. At 256 buckets a few hundred distinct terms fill the
#: space and every pair of long passages looks alike — which showed up as a
#: re-ingest matching unrelated material to a frozen Topic.
#:
#: It matches the width of the model that ships (ADR-0017) so that the stub and
#: the real thing are stored in the same column, and swapping between them is a
#: re-embed rather than a migration.
DIM = 768
_WORD = re.compile(r"[a-z0-9]+")


@runtime_checkable
class Embedder(Protocol):
    """Texts in, unit vectors out. The pipeline knows nothing more.

    Three attributes exist for reasons other than embedding: `model_name`,
    recorded on the notebook so a change of model is a visible event; `dim`,
    which the store checks against the column it is about to write into; and
    `credits_per_1k_tokens`, which is zero for anything that runs locally.

    Structural on purpose. Two things satisfy this port without being providers
    — the stub below, which must stay dependency-free so the test suite never
    loads a model, and `ReusingEmbedder`, which wraps an embedder and could not
    inherit from one without inheriting its weights too. Providers themselves
    inherit `embeddings.BaseEmbedder`, which is where the machinery lives.
    """

    model_name: str
    dim: int
    credits_per_1k_tokens: float

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]: ...

    def embed_query(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        """What to embed a *question* with, when the model is asymmetric.

        SigLIP is symmetric, so this is `embed`. Retrieval-trained encoders are
        not — E5, BGE and harrier all want an instruction prefix on the query
        side and nothing on the document side — and a citation lookup that
        forgets this silently loses accuracy rather than failing.
        """
        ...


@runtime_checkable
class ImageEmbedder(Protocol):
    """Image bytes in, unit vectors out, in the same space as the text.

    Separate from `Embedder` because most embedders have no image tower, and a
    pipeline that asks for one should fail at the boundary rather than deep in a
    provider call.
    """

    model_name: str
    dim: int
    supports_images: bool

    def embed_images(self, images: Sequence[bytes]) -> list[tuple[float, ...]]: ...


class HashingEmbedder:
    """A deterministic lexical embedder.

    It carries real similarity — texts sharing vocabulary land near each other —
    without a model, a key or a bill, which is what lets ingest be tested at all.
    It is not a semantic model and does not pretend to be one.
    """

    __slots__ = ("dim",)

    model_name = "hashing-v1"
    #: It runs here. There is no provider to pay and no number to invent.
    credits_per_1k_tokens = 0.0
    #: No image tower, and it does not pretend to have one.
    supports_images = False

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim

    def embed_query(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        """Symmetric: the stub scores a query the way it scores a passage."""
        return self.embed(texts)

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        """Weighted against the batch it arrives in.

        A term appearing in every chunk of a source distinguishes nothing within
        it, so it is discounted. Without that, prose separates badly: two
        passages about unrelated subjects still share the language they are
        written in.
        """
        counted = [self._counts(t) for t in texts]
        document_frequency: dict[int, int] = {}
        for counts in counted:
            for bucket in counts:
                document_frequency[bucket] = document_frequency.get(bucket, 0) + 1
        n = max(1, len(texts))
        out = []
        for counts in counted:
            vec = [0.0] * self.dim
            for bucket, count in counts.items():
                idf = math.log(1.0 + n / document_frequency[bucket])
                vec[bucket] = (1.0 + math.log(count)) * idf
            out.append(normalise(vec))
        return out

    def _counts(self, text: str) -> dict[int, float]:
        counts: dict[int, float] = {}
        for word in _WORD.findall(text.lower()):
            if len(word) < 4:
                continue
            bucket = hash_word(word) % self.dim
            counts[bucket] = counts.get(bucket, 0.0) + 1.0
        return counts


def hash_word(word: str) -> int:
    """Stable across processes — Python's own hash() is salted and is not."""
    h = 2166136261
    for ch in word.encode("utf-8"):
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return h


def normalise(vec: Sequence[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return tuple(vec)
    return tuple(v / norm for v in vec)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def centroid_of(vectors: Sequence[Sequence[float]]) -> tuple[float, ...]:
    if not vectors:
        return ()
    dim = len(vectors[0])
    acc = [0.0] * dim
    for v in vectors:
        for i, x in enumerate(v):
            acc[i] += x
    return normalise([x / len(vectors) for x in acc])
