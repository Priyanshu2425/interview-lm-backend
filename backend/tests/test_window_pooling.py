"""The whole chunk reaches the model, or this file fails.

SigLIP 2's text tower accepts 64 tokens. A chunk is 500–800. Handing it over
whole would keep the first tenth and discard the rest, and every number derived
from it afterwards — the cluster it joins, the Topic it becomes, the span a
citation points at — would be computed from that tenth, silently and plausibly.

So the encoder windows the chunk and pools the windows. These tests hold that
open with a stubbed tower: no torch, no weights, the real pooling code.
"""

from __future__ import annotations

import math

import pytest

from interviewer.service.embeddings.errors import EmbeddingContractError
from interviewer.service.embeddings.siglip import CONTEXT_TOKENS, SiglipEmbedder


class WordTokenizer:
    """One token per word. Enough to exercise windowing honestly."""

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [abs(hash(w)) % 9973 for w in text.split()]}

    def decode(self, ids):
        return " ".join(str(i) for i in ids)


class Stubbed(SiglipEmbedder):
    """The real windowing and pooling; a tower that just reports what it saw."""

    def __init__(self, **kw):
        kw.setdefault("model", "google/siglip2-base-patch16-224")
        kw.setdefault("dim", 8)
        super().__init__(**kw)
        self.windows_seen: list[list[int]] = []
        self._tokenizer = WordTokenizer()

    def warm(self):
        self._warm = True

    def _encode_windows(self, windows):
        self.windows_seen.extend(windows)
        # Each window's vector encodes its own contents, so pooling over
        # different tails cannot come out the same.
        return [
            [float(sum(w) % 97), float(len(w)), 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            for w in windows
        ]


def words(n: int, seed: str = "w") -> str:
    return " ".join(f"{seed}{i}" for i in range(n))


def test_a_long_chunk_is_cut_into_windows_and_none_is_dropped():
    e = Stubbed()
    text = words(CONTEXT_TOKENS * 5 + 7)
    e.embed([text])
    assert len(e.windows_seen) == 6
    assert sum(len(w) for w in e.windows_seen) == CONTEXT_TOKENS * 5 + 7


def test_two_chunks_agreeing_on_their_first_window_still_differ():
    """The regression test against silent truncation.

    If anyone ever 'simplifies' pooling into a `truncation=True`, these two
    inputs collapse onto the same vector and this fails.
    """
    head = words(CONTEXT_TOKENS, "same")
    a = f"{head} {words(200, 'alpha')}"
    b = f"{head} {words(200, 'beta')}"
    e = Stubbed()
    va, vb = e.embed([a, b])
    assert va != vb


def test_a_chunk_shorter_than_one_window_is_a_single_pass():
    e = Stubbed()
    e.embed([words(10)])
    assert len(e.windows_seen) == 1


def test_pooled_vectors_are_unit_length():
    (vector,) = Stubbed().embed([words(200)])
    assert sum(x * x for x in vector) == pytest.approx(1.0)


def test_every_window_in_a_batch_goes_through_the_tower_together():
    """A 12-window chunk is one forward call, not twelve."""
    calls = []

    class Counting(Stubbed):
        def _encode_windows(self, windows):
            calls.append(len(windows))
            return super()._encode_windows(windows)

    e = Counting(batch_size=64)
    e.embed([words(CONTEXT_TOKENS * 3), words(CONTEXT_TOKENS * 2)])
    assert calls == [5]


def test_an_absurdly_long_input_is_refused_rather_than_paid_for():
    e = Stubbed(max_windows=4)
    with pytest.raises(EmbeddingContractError) as caught:
        e.embed([words(CONTEXT_TOKENS * 10)])
    assert "windows" in str(caught.value)


def test_a_blank_chunk_never_reaches_the_tower():
    e = Stubbed()
    assert e.embed([""]) == [(0.0,) * 8]
    assert e.windows_seen == []
