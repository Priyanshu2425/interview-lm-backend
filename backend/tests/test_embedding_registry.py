"""Which embedder runs, and what happens when the answer is wrong.

The registry is the whole extension point for a new provider, so what it
refuses matters as much as what it builds: an unknown name, a paid provider
while ADR-0016 is unsigned, and a width the column cannot hold are all failures
that must happen at boot rather than at a Candidate's first upload.
"""

from __future__ import annotations

import sys

import pytest

from interviewer.service.embeddings.hashing import DIM, Embedder
from interviewer.service.embeddings import make_embedder, registered
from interviewer.service.embeddings.base import BaseEmbedder
from interviewer.service.embeddings.errors import PaidProviderRefused


def test_the_default_is_the_stub_and_is_explicit():
    e = make_embedder({})
    assert e.model_name == "hashing-v1"
    assert e.dim == DIM


def test_the_registered_providers_are_discoverable():
    assert {"hashing", "siglip", "http"} <= set(registered())


def test_an_unknown_provider_fails_at_boot_naming_what_exists():
    with pytest.raises(ValueError) as caught:
        make_embedder({"EMBEDDING_PROVIDER": "gpt5-embeddings"})
    assert "siglip" in str(caught.value)


def test_selecting_a_provider_never_silently_falls_back():
    """`INTERVIEWER_FAKE_MODEL` set the precedent: stand-ins are chosen, not inferred."""
    with pytest.raises(ValueError):
        make_embedder({"EMBEDDING_PROVIDER": "typo"})


def test_a_paid_provider_is_refused_while_adr_0016_is_unsigned():
    with pytest.raises(PaidProviderRefused) as caught:
        make_embedder({
            "EMBEDDING_PROVIDER": "http",
            "EMBEDDING_CREDITS_PER_1K": "0.5",
        })
    assert "ADR-0016" in str(caught.value)


def test_a_paid_provider_runs_once_that_decision_is_taken():
    e = make_embedder({
        "EMBEDDING_PROVIDER": "http",
        "EMBEDDING_CREDITS_PER_1K": "0.5",
        "EMBEDDING_ALLOW_PAID": "1",
    })
    assert e.credits_per_1k_tokens == 0.5


def test_a_local_provider_bills_nothing_so_byok_is_untouched():
    e = make_embedder({"EMBEDDING_PROVIDER": "siglip"})
    assert e.credits_per_1k_tokens == 0.0


def test_the_model_identity_records_the_revision():
    e = make_embedder({
        "EMBEDDING_PROVIDER": "siglip",
        "EMBEDDING_MODEL": "google/siglip2-base-patch16-224",
        "EMBEDDING_REVISION": "0123456789abcdef",
    })
    assert e.model_name == "siglip:google/siglip2-base-patch16-224@768#0123456789ab"


def test_selecting_an_embedder_does_not_load_a_model():
    """Construction is cheap; weights are the lifespan's business."""
    make_embedder({"EMBEDDING_PROVIDER": "siglip"})
    assert "torch" not in sys.modules


def test_every_provider_satisfies_the_port_it_is_injected_through():
    for name in registered():
        if name == "hashing":
            continue
        e = make_embedder({"EMBEDDING_PROVIDER": name})
        assert isinstance(e, BaseEmbedder)
        assert isinstance(e, Embedder), name
