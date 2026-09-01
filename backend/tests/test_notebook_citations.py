"""ISSUE-0025 (backend half) — where in my sources did this come from?

The feature the embedding route was chosen for. Two invariants matter more than
the feature itself: a citation resolves to text that really is in the source,
and producing one never sends a query anywhere during a Session.
"""

from __future__ import annotations

import pytest
from conftest import signed_in_client
from fastapi.testclient import TestClient

from interviewer.service.corpus.citations import render, resolve
from interviewer.service.corpus.loader import DossierLoader


@pytest.fixture()
def notebook_corpus(notebooks, real_notes):
    notebooks.create("nb-c", "cand-c", "Revision notes")
    notebooks.add_source("nb-c", source_id="s1", title="AIML notes", text=real_notes)
    return notebooks.corpus("nb-c")


def test_a_citation_resolves_to_a_span_that_is_really_in_the_source(
    notebook_corpus, real_notes
):
    loader = DossierLoader(notebook_corpus)
    topic = notebook_corpus.topics[0]
    dossier = loader.load(topic.id)
    grounding = {"kind": "text", "leaf_ids": [l.id for l in dossier.content[:3]]}

    citations = resolve(dossier, grounding)

    assert citations
    for citation in citations:
        assert citation["text"] in real_notes
        assert citation["chunk_id"]
        assert citation["topic_id"] == topic.id


def test_a_citation_names_a_source_and_a_page_never_an_offset(notebook_corpus):
    loader = DossierLoader(notebook_corpus)
    dossier = loader.load(notebook_corpus.topics[0].id)
    citation = resolve(dossier, {"kind": "text", "leaf_ids": [dossier.content[0].id]})[0]
    label = render(citation)
    assert "char" not in label
    assert str(citation["chunk_id"]) not in label


def test_model_judgment_cites_nothing_rather_than_citing_vaguely(notebook_corpus):
    loader = DossierLoader(notebook_corpus)
    dossier = loader.load(notebook_corpus.topics[0].id)
    assert resolve(dossier, {"kind": "syllabus", "syllabus": ["anything"]}) == []
    assert resolve(dossier, None) == []


def test_only_spans_that_were_in_the_grounding_can_be_cited(notebook_corpus):
    loader = DossierLoader(notebook_corpus)
    dossier = loader.load(notebook_corpus.topics[0].id)
    grounding = {"kind": "text", "leaf_ids": [dossier.content[0].id, "not-a-leaf"]}
    citations = resolve(dossier, grounding)
    assert [c["chunk_id"] for c in citations] == [dossier.content[0].id]


def test_a_cortex_topic_cites_nothing_and_still_renders(corpus, loader):
    """The shipped Corpus has no chunks. A citation list of none is not an error."""
    topic = corpus.topics[0]
    dossier = loader.load(topic.id)
    citations = resolve(dossier, {"kind": "syllabus", "syllabus": []})
    assert citations == []


# -- through a real Session --------------------------------------------------


@pytest.fixture()
def client(content_db, clean_db):
    from interviewer.app import create_app
    from interviewer.deps import refresh_corpus

    refresh_corpus()
    with signed_in_client() as c:
        yield c
    refresh_corpus()


def _run_one_visit(client, ingested, real_notes):
    created = client.post(
        "/v1/notebooks", json={"candidate_id": "cand-cite", "title": "Notes"}
    )
    notebook_id = created.json()["notebook_id"]
    module_id = client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "AIML notes", "text": real_notes},
    ).json()["module_id"]
    ingested(client, notebook_id)
    started = client.post(
        "/v1/sessions",
        json={
            "candidate_id": "cand-cite",
            "module_ids": [module_id],
            "duration_seconds": 600,
        },
    ).json()
    session_id = started["session_id"]
    result = started
    # Answer the whole plan, then grade it. Since ISSUE-0042 the loop writes no
    # Evidence, and a citation is a property of an Evidence row — so the
    # Session is graded here the way ISSUE-0044 will grade it at the end.
    for _ in range(6):
        result = client.post(
            f"/v1/sessions/{session_id}/turns",
            json={"answer": "Scaling keeps the softmax in a region with gradient."},
        ).json()
        if result.get("kind") == "session_ended":
            break
    from conftest import grade_session
    from interviewer.wiring import wiring

    grade_session(wiring().deps, session_id)
    return session_id, result.get("payload", result)


def test_a_graded_visit_carries_the_spans_that_grounded_its_question(
    client, ingested, real_notes, engine
):
    session_id, payload = _run_one_visit(client, ingested, real_notes)
    assert payload, "no Visit closed"

    from interviewer.service.confidence.store import EvidenceLedger

    rows = EvidenceLedger(engine).for_session(session_id)
    assert rows, "a graded Visit wrote no Evidence"
    row = rows[0]
    assert row["citations"], "Evidence carries no citation"
    for citation in row["citations"]:
        assert citation["text"] in real_notes
    assert row["topic_title_snapshot"]
    assert row["module_title_snapshot"] == "AIML notes"


def test_citations_reach_the_session_summary(client, ingested, real_notes):
    session_id, _ = _run_one_visit(client, ingested, real_notes)
    summary = client.get(f"/v1/sessions/{session_id}/summary").json()
    per_topic = summary["per_topic"]
    assert per_topic
    assert any(t["citations"] for t in per_topic)


def test_no_citation_path_queries_anything_during_a_session(
    client, ingested, real_notes
):
    """ADR-0005 as amended: the index is read at ingest and for attribution,
    never to answer a question."""
    from interviewer.adapters.internal import embedding

    embedded = []
    original = embedding.HashingEmbedder.embed

    def watched(self, texts):
        embedded.append(len(texts))
        return original(self, texts)

    embedding.HashingEmbedder.embed = watched
    try:
        created = client.post(
            "/v1/notebooks", json={"candidate_id": "cand-q", "title": "Notes"}
        )
        notebook_id = created.json()["notebook_id"]
        module_id = client.post(
            f"/v1/notebooks/{notebook_id}/sources",
            json={"title": "AIML notes", "text": real_notes},
        ).json()["module_id"]
        ingested(client, notebook_id)
        during_ingest = len(embedded)
        assert during_ingest, "ingest embedded nothing"

        session = client.post(
            "/v1/sessions",
            json={
                "candidate_id": "cand-q",
                "module_ids": [module_id],
                "duration_seconds": 600,
            },
        ).json()
        for _ in range(3):
            client.post(
                f"/v1/sessions/{session['session_id']}/turns",
                json={"answer": "An answer."},
            )
    finally:
        embedding.HashingEmbedder.embed = original

    assert len(embedded) == during_ingest, "the Session embedded something"
