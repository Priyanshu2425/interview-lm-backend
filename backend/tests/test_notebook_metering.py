"""ISSUE-0026 — what an ingest costs, and what happens when it cannot be paid for.

The BYOK question this slice raises is a product decision and is not settled
here (see ADR draft). Everything below is settled: the gate is a refusal rather
than a quote, a Source lands whole or not at all, and nothing is embedded twice.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from interviewer.adapters.internal.notebook import HashingEmbedder
from interviewer.service.notebooks.metering import InsufficientBalance, estimate


class Priced(HashingEmbedder):
    """A stand-in for a provider-backed embedder, with a price attached.

    Exists because the real provider is the open decision in this slice, and the
    metering around it must be testable before that decision is taken.
    """

    model_name = "priced-test-v1"
    credits_per_1k_tokens = 4.0

    def __init__(self):
        super().__init__()
        self.calls = []

    def embed(self, texts):
        self.calls.append(len(texts))
        return super().embed(texts)


@dataclass
class Priced_Setup:
    service: object
    embedder: Priced
    ledger: object


@pytest.fixture()
def priced(content_db, clean_db):
    from interviewer.service.metering.ledger import CreditLedger
    from interviewer.service.notebooks import NotebookService

    embedder = Priced()
    ledger = CreditLedger(clean_db)
    return Priced_Setup(
        service=NotebookService(content_db, embedder=embedder, credits=ledger),
        embedder=embedder,
        ledger=ledger,
    )


def _candidate(engine, candidate_id="cand-m"):
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import insert

    from interviewer.db import schema as S

    with engine.begin() as c:
        c.execute(
            insert(S.candidate)
            .values(candidate_id=candidate_id)
            .on_conflict_do_nothing()
        )
    return candidate_id


# -- measurement -------------------------------------------------------------


def test_ingest_cost_is_measured_from_our_own_token_count():
    cost = estimate(["x" * 4000], embedder=Priced(), route="credits")
    assert cost.tokens == 1000
    assert cost.credits == 4
    assert cost.model == "priced-test-v1"


def test_a_local_embedder_costs_nothing_and_says_so():
    cost = estimate(["x" * 4000], embedder=HashingEmbedder(), route="credits")
    assert cost.is_free
    assert cost.credits == 0


def test_a_byok_candidate_is_never_charged_credits():
    cost = estimate(["x" * 400_000], embedder=Priced(), route="byok")
    assert cost.credits == 0
    assert cost.tokens == 100_000
    assert cost.route == "byok"


# -- the gate ----------------------------------------------------------------


def test_an_insufficient_balance_refuses_before_the_first_call(
    priced, clean_db, real_notes
):
    candidate = _candidate(clean_db)
    priced.service.create("nb-poor", candidate, "Notes")
    priced.embedder.calls.clear()

    with pytest.raises(InsufficientBalance) as raised:
        priced.service.add_source(
            "nb-poor", source_id="s1", title="Notes", text=real_notes
        )

    assert raised.value.shortfall > 0
    assert priced.embedder.calls == [], "it embedded anyway"
    # The upload outlives the refusal (ISSUE-0035): the document is listed and
    # marked failed, so the Candidate can top up and retry rather than upload it
    # again. What must not exist is a Module — and it does not.
    listed = priced.service.store.get("nb-poor").sources
    assert [s.state for s in listed] == ["failed"]
    assert priced.service.corpus("nb-poor") is None


def test_a_refused_ingest_leaves_no_ledger_entry(priced, clean_db, real_notes):
    candidate = _candidate(clean_db, "cand-poor")
    priced.service.create("nb-poor2", candidate, "Notes")
    with pytest.raises(InsufficientBalance):
        priced.service.add_source(
            "nb-poor2", source_id="s1", title="Notes", text=real_notes
        )
    assert priced.ledger.balance(candidate) == 0
    assert priced.ledger.rows(candidate) == []


def test_a_funded_ingest_lands_and_is_charged(priced, clean_db, real_notes):
    candidate = _candidate(clean_db, "cand-rich")
    priced.ledger.grant(candidate, 5000, "test-grant")
    priced.service.create("nb-rich", candidate, "Notes")

    added = priced.service.add_source(
        "nb-rich", source_id="s1", title="Notes", text=real_notes
    )

    assert added.state == "ready"
    assert added.cost.credits > 0
    assert priced.ledger.balance(candidate) == (
        5000 - added.cost.credits
    )


# -- resume, and never paying twice ------------------------------------------


def test_re_uploading_the_same_material_embeds_nothing_new(
    priced, clean_db, real_notes
):
    candidate = _candidate(clean_db, "cand-again")
    priced.ledger.grant(candidate, 5000, "grant")
    priced.service.create("nb-again", candidate, "Notes")
    priced.service.add_source("nb-again", source_id="s1", title="A", text=real_notes)

    balance = priced.ledger.balance(candidate)
    priced.embedder.calls.clear()

    again = priced.service.add_source(
        "nb-again", source_id="s2", title="A again", text=real_notes
    )

    assert again.deduplicated is True
    assert priced.embedder.calls == []
    assert priced.ledger.balance(candidate) == balance


def test_material_shared_between_two_sources_is_embedded_once(
    priced, clean_db, real_notes
):
    """Content-addressed: the same passage in a second file is already known."""
    candidate = _candidate(clean_db, "cand-shared")
    priced.ledger.grant(candidate, 5000, "grant")
    priced.service.create("nb-shared", candidate, "Notes")
    priced.service.add_source(
        "nb-shared", source_id="s1", title="Part one", text=real_notes
    )

    priced.embedder.calls.clear()
    second = priced.service.add_source(
        "nb-shared",
        source_id="s2",
        title="Part one plus a note",
        text=real_notes + "\n\nOne further remark about calibration curves.\n",
    )

    assert second.state == "ready"
    embedded_now = sum(priced.embedder.calls)
    assert embedded_now < second.chunks, (
        "every chunk was re-embedded even though most were already known"
    )


def test_the_embedding_model_is_recorded_on_the_notebook(priced, clean_db):
    candidate = _candidate(clean_db, "cand-model")
    priced.service.create("nb-model", candidate, "Notes")
    assert priced.service.store.get("nb-model").embedding_model == "priced-test-v1"


# -- atomicity ---------------------------------------------------------------


def test_a_provider_failure_leaves_no_partial_module(
    priced, clean_db, real_notes
):
    candidate = _candidate(clean_db, "cand-fail")
    priced.ledger.grant(candidate, 5000, "grant")
    priced.service.create("nb-fail", candidate, "Notes")

    def explode(texts):
        raise RuntimeError("provider unavailable")

    original = priced.embedder.embed
    priced.embedder.embed = explode
    try:
        with pytest.raises(RuntimeError):
            priced.service.add_source(
                "nb-fail", source_id="s1", title="Notes", text=real_notes
            )
    finally:
        priced.embedder.embed = original

    listed = priced.service.store.get("nb-fail").sources
    assert [s.state for s in listed] == ["failed"]
    assert "provider unavailable" in (listed[0].stub_reason or "")
    # No Module, no Topic, no chunk. Atomicity is unchanged by the split: the
    # material lands in one transaction at the end or not at all.
    assert priced.service.store.chunks_of("nb-fail") == []
    assert priced.service.store.frozen_topics("nb-fail") == {}
    assert priced.service.corpus("nb-fail") is None
    assert priced.ledger.balance(candidate) == 5000
