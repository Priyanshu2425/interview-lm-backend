"""The machinery every provider inherits, tested without a provider.

Nothing here loads a model. The point of `BaseEmbedder` is that batching,
ordering, retries, validation and normalisation are written once and are then
true of every embedder that will ever be added — so they are tested against a
fake subclass, where each failure mode can actually be provoked.
"""

from __future__ import annotations

import math

import pytest

from interviewer.embeddings.base import BaseEmbedder
from interviewer.embeddings.errors import (
    EmbeddingContractError, EmbeddingTimeout, UnsupportedModality,
)


class Fake(BaseEmbedder):
    """Returns a vector whose first axis is the input's length."""

    provider = "fake"

    def __init__(self, **kw):
        kw.setdefault("model", "fake-1")
        kw.setdefault("dim", 4)
        super().__init__(**kw)
        self.batches: list[list[str]] = []

    def _encode_texts(self, batch):
        self.batches.append(list(batch))
        return [[float(len(t)), 0.0, 0.0, 0.0] for t in batch]


def test_model_name_identifies_provider_model_width_and_revision():
    assert Fake().model_name == "fake:fake-1@4"
    assert Fake(revision="a" * 40).model_name == "fake:fake-1@4#" + "a" * 12


def test_order_survives_batching():
    """The pipeline zips vectors against chunks by position, so order is a contract."""
    e = Fake(batch_size=2)
    out = e.embed(["a", "bb", "ccc", "dddd", "eeeee"])
    assert [round(v[0] * 0 + len(t), 0) for v, t in zip(out, ["a", "bb", "ccc", "dddd", "eeeee"])]
    assert e.batches == [["a", "bb"], ["ccc", "dddd"], ["eeeee"]]
    # every vector is the unit vector along axis 0, so identity is the length
    assert all(pytest.approx(1.0) == sum(x * x for x in v) for v in out)


def test_a_blank_input_is_the_zero_vector_and_never_a_provider_call():
    e = Fake()
    out = e.embed(["", "   ", "real"])
    assert out[0] == (0.0,) * 4 and out[1] == (0.0,) * 4
    assert e.batches == [["real"]]


def test_vectors_come_back_normalised_even_when_the_model_did_not():
    class Big(Fake):
        def _encode_texts(self, batch):
            return [[3.0, 4.0, 0.0, 0.0] for _ in batch]

    (vector,) = Big().embed(["x"])
    assert vector == pytest.approx((0.6, 0.8, 0.0, 0.0))


def test_a_wrong_width_is_refused_rather_than_stored():
    class Narrow(Fake):
        def _encode_texts(self, batch):
            return [[1.0, 0.0] for _ in batch]

    with pytest.raises(EmbeddingContractError) as caught:
        Narrow().embed(["x"])
    assert "2 dimensions" in str(caught.value) and "expected 4" in str(caught.value)


def test_a_wrong_count_is_refused():
    class Short(Fake):
        def _encode_texts(self, batch):
            return [[1.0, 0.0, 0.0, 0.0]]

    with pytest.raises(EmbeddingContractError):
        Short().embed(["x", "y"])


def test_a_non_finite_vector_never_reaches_a_centroid():
    """A NaN freezes into a Topic and is close to undiagnosable months later."""
    class Nan(Fake):
        def _encode_texts(self, batch):
            return [[math.nan, 0.0, 0.0, 0.0] for _ in batch]

    with pytest.raises(EmbeddingContractError):
        Nan().embed(["x"])


def test_a_transient_failure_is_retried_and_then_succeeds():
    class Flaky(Fake):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.attempts = 0

        def _encode_texts(self, batch):
            self.attempts += 1
            if self.attempts < 3:
                raise EmbeddingTimeout("slow")
            return super()._encode_texts(batch)

    e = Flaky(max_retries=3)
    e.embed(["x"])
    assert e.attempts == 3
    assert e.health()["failures"] == 2


def test_a_permanent_failure_is_not_retried():
    """Asking a second time gets the same answer and costs the same money."""
    class Broken(Fake):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.attempts = 0

        def _encode_texts(self, batch):
            self.attempts += 1
            raise ValueError("malformed request")

    e = Broken(max_retries=3)
    with pytest.raises(ValueError):
        e.embed(["x"])
    assert e.attempts == 1


def test_retries_are_finite():
    class Down(Fake):
        def _encode_texts(self, batch):
            raise EmbeddingTimeout("always")

    with pytest.raises(EmbeddingTimeout):
        Down(max_retries=1).embed(["x"])


def test_images_are_refused_by_an_embedder_without_a_tower():
    with pytest.raises(UnsupportedModality):
        Fake().embed_images([b"\x89PNG"])


def test_health_reports_identity_and_counts():
    e = Fake()
    e.embed(["a", "b"])
    report = e.health()
    assert report["model"] == "fake:fake-1@4"
    assert report["dim"] == 4 and report["items"] == 2 and report["calls"] == 1
    assert report["supports_images"] is False


def test_nothing_is_a_no_op():
    assert Fake().embed([]) == []
