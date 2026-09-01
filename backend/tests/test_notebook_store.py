"""ISSUE-0021 — the notebook, persisted and served.

The Adapter is pure and tested elsewhere. What is tested here is the part that
touches Postgres: material lands in `content`, the Corpus read back is the one
that was frozen, and the picker shows it to its owner and to nobody else.
"""

from __future__ import annotations

import pytest
from conftest import signed_in_client
from fastapi.testclient import TestClient

from interviewer.app import create_app

from interviewer.service.corpus.conformance import validate


@pytest.fixture()
def notebook(notebooks, real_notes):
    notebooks.create("nb-1", "cand-1", "My revision notes")
    added = notebooks.add_source(
        "nb-1", source_id="s1", title="AIML notes", text=real_notes
    )
    return added


def test_a_source_becomes_a_module_of_topics(notebooks, notebook):
    corpus = notebooks.corpus("nb-1")
    assert len(corpus.modules) == 1
    assert corpus.modules[0].title == "AIML notes"
    assert len(corpus.modules[0].topics) == notebook.topics > 1


def test_the_corpus_read_back_from_the_store_is_conformant(notebooks, notebook):
    assert validate(notebooks.corpus("nb-1")).violations == []


def test_reading_the_corpus_back_never_re_clusters(notebooks, notebook):
    """ADR-0015: the clusterer runs once, at ingest. Reading is rows, not maths."""
    first = notebooks.corpus("nb-1")
    again = notebooks.corpus("nb-1")
    assert [t.id for t in first.topics] == [t.id for t in again.topics]
    assert first.model_dump() == again.model_dump()


def test_chunks_carry_their_locator_into_the_store(notebooks, notebook, real_notes):
    rows = notebooks.store.chunks_of("nb-1")
    assert rows
    for row in rows:
        assert real_notes[row["char_start"]:row["char_end"]] == row["text"]


def test_frozen_topics_persist_their_centroid_and_membership(notebooks, notebook):
    frozen = notebooks.store.frozen_topics("nb-1")
    assert len(frozen) == notebook.topics
    for topic in frozen.values():
        assert topic.centroid and topic.chunk_hashes


def test_the_same_file_twice_is_the_same_module(notebooks, notebook, real_notes):
    again = notebooks.add_source(
        "nb-1", source_id="s2", title="Uploaded twice", text=real_notes
    )
    assert again.deduplicated is True
    assert again.module_id == notebook.module_id
    assert len(notebooks.corpus("nb-1").modules) == 1


def test_a_source_with_no_text_is_a_stub_module_not_a_failure(notebooks):
    notebooks.create("nb-2", "cand-1", "Scans")
    added = notebooks.add_source("nb-2", source_id="s1", title="Scanned", text="")
    assert added.state == "stub"
    assert added.stub_reason == "no extractable text"
    assert added.chunks == 0
    # It carries no Topic, so it is visible in the record and unexaminable.
    assert notebooks.corpus("nb-2") is None


def test_deleting_a_notebook_empties_content_and_touches_nothing_else(
    notebooks, notebook
):
    notebooks.delete("nb-1")
    assert notebooks.store.get("nb-1") is None
    assert notebooks.store.chunks_of("nb-1") == []
    assert notebooks.store.frozen_topics("nb-1") == {}


# -- the picker and the Session ---------------------------------------------


@pytest.fixture()
def client(content_db, clean_db):
    from interviewer.app import create_app
    from interviewer.deps import refresh_corpus

    refresh_corpus()
    with signed_in_client() as c:
        yield c
    refresh_corpus()


def test_the_picker_lists_the_notebook_and_a_session_runs_on_it(
    client, ingested, real_notes
):
    created = client.post(
        "/v1/notebooks", json={"candidate_id": "cand-9", "title": "Notes"}
    )
    assert created.status_code == 201
    notebook_id = created.json()["notebook_id"]

    added = client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "AIML notes", "text": real_notes},
    )
    assert added.status_code == 201
    module_id = added.json()["module_id"]
    # The upload answers immediately and the ingest runs behind it, so the work
    # *found* is what the response carries and the Module arrives with the poll.
    assert added.json()["state"] == "uploaded"
    assert added.json()["progress_total"] >= 1
    assert ingested(client, notebook_id)["state"] == "ready"

    modules = client.get("/v1/skills/modules", params={"candidate_id": "cand-9"})
    listed = {m["module_id"]: m for m in modules.json()}
    assert module_id in listed
    assert listed[module_id]["title"] == "AIML notes"
    # Text-grounded: this slice mines no Ground Truth (ISSUE-0024 does).
    assert listed[module_id]["ceiling"] == "text_grounded"

    started = client.post(
        "/v1/sessions",
        json={
            "candidate_id": "cand-9",
            "module_ids": [module_id],
            "duration_seconds": 600,
        },
    )
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["kind"] == "question"
    assert body["question"].strip()

    # The question was asked from a Topic of the notebook, not from the
    # shipped Corpus that happens to be loaded alongside it.
    topic = client.get(f"/v1/skills/topics/{body['topic_id']}")
    assert topic.status_code == 200
    assert topic.json()["module_id"] == module_id


def test_a_notebook_is_not_listed_for_another_candidate(
    client, ingested, real_notes
):
    """"Nobody else's" stopped being a comment when the Candidate stopped
    being a query parameter: there is no id to name any more, only a token."""
    owner = signed_in_client("cand-owner")
    other = signed_in_client("cand-other")
    created = owner.post("/v1/notebooks", json={"title": "Private"})
    notebook_id = created.json()["notebook_id"]
    added = owner.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "Private notes", "text": real_notes},
    )
    module_id = added.json()["module_id"]
    ingested(owner, notebook_id)

    mine = owner.get("/v1/skills/modules")
    theirs = other.get("/v1/skills/modules")
    anonymous = TestClient(create_app()).get("/v1/skills/modules")

    assert module_id in {m["module_id"] for m in mine.json()}
    assert module_id not in {m["module_id"] for m in theirs.json()}
    # Not "not listed" any more — not answered at all.
    assert anonymous.status_code == 401
    # The same question, signed in as somebody with nothing: an empty Library
    # rather than a refusal. There is no Corpus that belongs to nobody any more
    # (ISSUE-0037), so a shared Library would show here and this deployment has
    # none.
    assert other.get("/v1/skills/modules").json() == []
