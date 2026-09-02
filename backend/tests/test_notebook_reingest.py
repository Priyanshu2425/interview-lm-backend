"""ISSUE-0022 — a Topic means next month what it means today.

`topic_id` is the join key for months of accumulated Topic Confidence. These
tests are the whole reason ADR-0015 exists: a re-ingest may add Topics, and it
may say so loudly, but it may not silently re-point the ones already carrying
Evidence.
"""

from __future__ import annotations

import pytest

from interviewer.service.corpus.conformance import validate


@pytest.fixture()
def base(notebooks, real_notes):
    notebooks.create("nb-1", "cand-1", "Revision notes")
    added = notebooks.add_source(
        "nb-1", source_id="s1", title="AIML notes", text=real_notes
    )
    return added


def ids(notebooks) -> set[str]:
    return {t.id for t in notebooks.corpus("nb-1").topics}


def test_a_byte_identical_source_is_not_a_change(notebooks, base, real_notes, counting):
    before = ids(notebooks)
    counting.calls.clear()
    again = notebooks.add_source(
        "nb-1", source_id="s2", title="Same file", text=real_notes
    )
    assert again.deduplicated is True
    assert ids(notebooks) == before
    assert counting.calls == []  # nothing re-embedded, nothing re-billed
    assert notebooks.versions("nb-1") == []


def test_appending_a_paragraph_mints_no_new_topic(notebooks, base, real_notes):
    before = ids(notebooks)
    notebooks.replace_source(
        "nb-1",
        source_id=base.source_id,
        text=real_notes + "\n\nOne more sentence about bagging and variance.\n",
    )
    after = ids(notebooks)
    assert before <= after, "an append re-pointed a Topic that already carried evidence"
    assert after == before, "an append minted a Topic"


def test_replacing_half_the_source_mints_a_topic_and_says_so(
    notebooks, base, real_notes
):
    before = ids(notebooks)
    half = real_notes[: len(real_notes) // 2]
    replacement = half + "\n\n" + _unrelated()
    notebooks.replace_source("nb-1", source_id=base.source_id, text=replacement)

    after = ids(notebooks)
    assert after - before, "new material produced no new Topic"
    events = notebooks.versions("nb-1")
    assert len(events) == 1
    event = events[0]
    assert event["source_id"] == base.source_id
    assert set(event["new_topic_ids"]) == after - before
    assert set(event["surviving_topic_ids"]) <= before


def test_a_surviving_topic_keeps_the_id_its_evidence_is_keyed_on(
    notebooks, base, real_notes
):
    before = ids(notebooks)
    notebooks.replace_source(
        "nb-1",
        source_id=base.source_id,
        text=real_notes + "\n\n" + _unrelated(),
    )
    survivors = ids(notebooks) & before
    assert survivors, "every Topic was re-minted by a re-ingest"
    frozen = notebooks.store.frozen_topics("nb-1")
    for topic_id in survivors:
        assert frozen[topic_id].topic_id == topic_id


def test_deleting_material_retires_no_topic_and_rewrites_no_id(
    notebooks, base, real_notes
):
    before = ids(notebooks)
    notebooks.replace_source(
        "nb-1", source_id=base.source_id, text=real_notes[: len(real_notes) // 2]
    )
    after = ids(notebooks)
    assert after <= before
    assert not after - before
    assert notebooks.versions("nb-1"), "a shrunk dossier was not recorded"


def test_a_version_event_survives_the_notebook_it_describes(
    notebooks, base, real_notes
):
    """The event is permanent. That is its whole purpose."""
    notebooks.replace_source(
        "nb-1", source_id=base.source_id, text=real_notes + "\n\n" + _unrelated()
    )
    assert notebooks.versions("nb-1")
    notebooks.delete("nb-1")
    assert notebooks.versions("nb-1"), "deleting content erased the record of a change"


def test_re_ingest_never_re_clusters_a_frozen_source(notebooks, base, real_notes):
    from interviewer.service.corpus.sources.notebook.documents import reingest

    calls = []
    original = reingest.cluster_chunks

    def watched(chunks):
        calls.append(len(chunks))
        return original(chunks)

    reingest.cluster_chunks = watched
    try:
        notebooks.replace_source(
            "nb-1", source_id=base.source_id, text=real_notes + "\n\n" + _unrelated()
        )
    finally:
        reingest.cluster_chunks = original

    total_chunks = len(notebooks.store.chunks_of("nb-1"))
    assert calls, "nothing clustered at all"
    assert max(calls) < total_chunks, (
        "the whole source was re-clustered; only unmatched chunks may be"
    )


def test_changing_the_embedding_model_preserves_every_membership(
    notebooks, base, real_notes
):
    before = {
        row["chunk_id"]: row["topic_id"] for row in notebooks.store.chunks_of("nb-1")
    }
    notebooks.re_embed("nb-1", embedding_model="hashing-v2")
    after = {
        row["chunk_id"]: row["topic_id"] for row in notebooks.store.chunks_of("nb-1")
    }
    assert after == before, "membership was recomputed rather than carried across"
    assert notebooks.store.get("nb-1").embedding_model == "hashing-v2"
    assert all(
        row["embedding_model"] == "hashing-v2"
        for row in notebooks.store.chunks_of("nb-1")
    ), "a chunk's vector was replaced but its model string still names the old space"
    assert any(
        e["reason"] == "embedding_model_changed" for e in notebooks.versions("nb-1")
    )


def test_the_corpus_stays_conformant_across_a_re_ingest(notebooks, base, real_notes):
    notebooks.replace_source(
        "nb-1", source_id=base.source_id, text=real_notes + "\n\n" + _unrelated()
    )
    assert validate(notebooks.corpus("nb-1")).violations == []


def test_the_similarity_floor_is_named_not_buried():
    """The one judgement call in the matcher is a named, explained constant."""
    import inspect

    from interviewer.service.corpus.sources.notebook.documents import reingest

    assert isinstance(reingest.MATCH_FLOOR, float)
    assert 0.0 < reingest.MATCH_FLOOR < 1.0
    source = inspect.getsource(reingest)
    body = source.split("MATCH_FLOOR = ")[1].splitlines()[0]
    assert body.strip(), "the floor has no value"
    # It is stated, and the matcher reads the name rather than a literal.
    assert "#:" in source.split("MATCH_FLOOR = ")[0].splitlines()[-2]
    assert "best_similarity = None, MATCH_FLOOR" in source or (
        "MATCH_FLOOR" in source.split("def _nearest")[1]
    )


def _unrelated() -> str:
    """Material with no vocabulary in common with the AIML notes."""
    return "\n\n".join(
        "# Baking sourdough\n\n"
        "Sourdough starter ferments flour and water with wild yeast. Hydration "
        "governs crumb structure, and a longer bulk proof develops sour flavour "
        "through acetic and lactic acid. Shaping tightens the dough surface so "
        "the loaf holds its height in the oven." * 6
        for _ in range(3)
    )


def test_evidence_accumulated_before_a_re_ingest_still_reads_after_it(
    notebooks, base, real_notes, clean_db
):
    """The reason all of this exists.

    A posterior accumulates against `topic_id` for months. A re-ingest that
    re-minted ids would leave that posterior orphaned — no error, just a number
    that stopped meaning what it meant.
    """
    from interviewer.repository.core import ConfidenceStore
    from interviewer.db import schema as S
    import sqlalchemy as sa

    confidence = ConfidenceStore(clean_db)
    topic_id = sorted(ids(notebooks))[0]
    with clean_db.begin() as c:
        c.execute(sa.insert(S.candidate).values(candidate_id="cand-1"))
        c.execute(
            sa.insert(S.topic_confidence).values(
                candidate_id="cand-1",
                topic_id=topic_id,
                alpha=4.0,
                beta=2.0,
            )
        )
    before = confidence.get("cand-1", topic_id)

    notebooks.replace_source(
        "nb-1", source_id=base.source_id, text=real_notes + "\n\n" + _unrelated()
    )

    assert topic_id in ids(notebooks), "the Topic the posterior belongs to vanished"
    after = confidence.get("cand-1", topic_id)
    assert (after.alpha, after.beta) == (before.alpha, before.beta) == (4.0, 2.0)
