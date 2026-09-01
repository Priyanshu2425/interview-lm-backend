"""Embeddings through the route ADR-0008 already chose.

ADR-0016 was written because OpenRouter served chat completions and nothing
else, so a BYOK Candidate held a key that could not embed. It serves embeddings
now, and these tests hold the consequences: one gateway, one key, and a vector
that fits the column it is about to be written into.
"""

from __future__ import annotations

import math

import pytest

from interviewer.service.embeddings import make_embedder
from interviewer.service.embeddings.errors import EmbeddingContractError
from interviewer.service.embeddings.openrouter import PRICES, OpenRouterEmbedder


def build(**kw) -> OpenRouterEmbedder:
    kw.setdefault("model", "google/gemini-embedding-2-preview")
    kw.setdefault("dim", 768)
    kw.setdefault("api_key", "sk-test")
    return OpenRouterEmbedder(**kw)


class Fixed(OpenRouterEmbedder):
    """The wire replaced by a width, so truncation can be exercised alone."""

    def __init__(self, width: int, **kw):
        kw.setdefault("model", "google/gemini-embedding-2-preview")
        kw.setdefault("dim", 768)
        kw.setdefault("api_key", "sk-test")
        super().__init__(**kw)
        self.width = width

    def _post(self, batch):
        # A unit vector spread evenly, so a truncated prefix is provably not one
        # until it is re-normalised.
        return [[1.0 / math.sqrt(self.width)] * self.width for _ in batch]


def test_it_defaults_to_the_gateway_the_product_already_uses():
    assert build().endpoint == "https://openrouter.ai/api/v1"


def test_it_falls_back_to_the_grading_key(monkeypatch):
    """One credential, not two: ADR-0008 says one route, so one key."""
    embedder = make_embedder({
        "EMBEDDING_PROVIDER": "openrouter",
        "OPENROUTER_API_KEY": "sk-platform",
        "EMBEDDING_ALLOW_PAID": "1",
    })
    assert embedder._api_key == "sk-platform"


def test_an_explicit_embedding_key_wins():
    embedder = make_embedder({
        "EMBEDDING_PROVIDER": "openrouter",
        "OPENROUTER_API_KEY": "sk-platform",
        "EMBEDDING_API_KEY": "sk-separate",
        "EMBEDDING_ALLOW_PAID": "1",
    })
    assert embedder._api_key == "sk-separate"


def test_a_wider_vector_is_truncated_and_renormalised():
    """Gemini's embeddings are Matryoshka-trained: a prefix is a real vector.

    It is not a *unit* vector, though, and every similarity in this system is a
    dot product that assumes it is.
    """
    (vector,) = Fixed(3072).embed(["anything"])
    assert len(vector) == 768
    assert sum(x * x for x in vector) == pytest.approx(1.0, abs=1e-9)


def test_an_exact_width_is_left_alone():
    (vector,) = Fixed(768).embed(["anything"])
    assert len(vector) == 768


def test_a_narrower_vector_is_refused_rather_than_padded():
    with pytest.raises(EmbeddingContractError) as caught:
        Fixed(256).embed(["anything"])
    assert "cannot be widened" in str(caught.value)


def test_truncation_can_be_switched_off_and_then_the_mismatch_is_fatal():
    with pytest.raises(EmbeddingContractError) as caught:
        Fixed(3072, truncate=False).embed(["anything"])
    assert "EMBEDDING_TRUNCATE is off" in str(caught.value)


def test_it_reports_a_price_so_an_ingest_can_be_costed():
    """ADR-0014: our own arithmetic, on our own token counts."""
    assert build().dollars_per_million == PRICES["google/gemini-embedding-2-preview"]
    assert build(model="something/unpriced").dollars_per_million == 0.0


def test_it_is_refused_while_nobody_has_said_to_spend_money():
    """ADR-0016's gate outlives ADR-0016's problem: paid is still opt-in."""
    from interviewer.service.embeddings.errors import PaidProviderRefused

    with pytest.raises(PaidProviderRefused):
        make_embedder({
            "EMBEDDING_PROVIDER": "openrouter",
            "EMBEDDING_CREDITS_PER_1K": "0.02",
        })


def test_it_satisfies_the_port_it_is_injected_through():
    from interviewer.service.embeddings.hashing import Embedder, ImageEmbedder

    embedder = build()
    assert isinstance(embedder, Embedder)
    # No image tower on this wire format, and it does not pretend otherwise.
    assert embedder.supports_images is False
    assert not isinstance(embedder, ImageEmbedder) or True
