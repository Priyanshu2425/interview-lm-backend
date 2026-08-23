"""ISSUE-0035 — a document is in the Library before it is ingested.

Embedding a 200-page PDF takes roughly forty seconds and SPEC-0000 refuses Redis
and a message queue outright, so the work runs in-process and the surface polls.
The part that makes a failure survivable is not the background thread, though —
it is that **the upload and the ingestion are separated**. A Source exists as
soon as its bytes do, so a forty-second embed that dies leaves a document
somebody can retry rather than an upload that never happened.

What must not change is ISSUE-0026's atomicity, and most of what is asserted
here is that it did not: no partial Module, no orphan Topic, no chunk belonging
to nothing, no double charge.
"""

from __future__ import annotations

import pytest
from conftest import signed_in_client
from fastapi.testclient import TestClient

PROSE = (
    "Attention weights every token against every other token, and the softmax "
    "over scaled dot products is what keeps the gradient from vanishing. "
)


@pytest.fixture()
def client(content_db, clean_db):
    from interviewer.api.app import create_app
    from interviewer.api.deps import refresh_corpus

    refresh_corpus()
    with signed_in_client() as c:
        yield c
    refresh_corpus()


@pytest.fixture()
def notebook(client):
    return client.post(
        "/v1/notebooks", json={"candidate_id": "cand-bg", "title": "Notes"}
    ).json()["notebook_id"]


def _upload(client, notebook_id, *, title="AIML notes", text=None):
    return client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": title, "text": text if text is not None else PROSE * 200},
    ).json()


def _sources(client, notebook_id):
    return client.get(f"/v1/notebooks/{notebook_id}").json()["sources"]


# -- the upload outlives the ingestion --------------------------------------

def test_a_document_appears_in_the_library_before_it_is_ingested(client, notebook):
    body = _upload(client, notebook)
    assert body["state"] == "uploaded"
    listed = _sources(client, notebook)
    assert [s["title"] for s in listed] == ["AIML notes"]


def test_adding_a_source_does_not_block_on_embedding(client, notebook):
    """The response is written before the embedder has been asked for anything."""
    body = _upload(client, notebook)
    assert body["state"] in ("uploaded", "ingesting")
    assert "topics" not in body


def test_ingestion_starts_by_itself(client, notebook, ingested):
    _upload(client, notebook)
    assert ingested(client, notebook)["state"] == "ready"


def test_progress_is_work_done_against_work_found(client, notebook, ingested):
    """Never indeterminate: the total is measured at upload, not discovered."""
    body = _upload(client, notebook)
    assert body["progress_total"] > 0
    assert body["progress_done"] == 0
    done = ingested(client, notebook)
    assert done["progress_done"] == done["progress_total"] > 0


def test_a_completed_ingest_is_a_usable_module_the_moment_it_reads_ready(
    client, notebook, ingested
):
    """`ready` has to imply *composed*, or the progress bar lies by one step."""
    body = _upload(client, notebook)
    ingested(client, notebook)
    started = client.post("/v1/sessions", json={
        "candidate_id": "cand-bg",
        "module_ids": [body["module_id"]],
        "duration_seconds": 600,
    })
    assert started.status_code == 201, started.text


# -- not ready is listed, not selectable, and says why -----------------------

def test_a_document_that_is_not_ready_is_listed_and_not_selectable(client, notebook):
    from interviewer.api.deps import get_notebook_service

    svc = get_notebook_service()
    svc.upload_source(
        notebook, source_id="src-waiting", title="Waiting", text=PROSE * 40
    )
    modules = client.get("/v1/corpus/modules?candidate_id=cand-bg").json()
    listed = next(m for m in modules if m["title"] == "Waiting")
    assert listed["selectable"] is False
    assert listed["state"] == "uploaded"
    assert listed["stub_reason"], "listed and greyed out with no explanation"


def test_a_stub_still_states_why_it_carries_nothing(client, notebook, ingested):
    from pdf_fixtures import scanned_pdf

    client.post(
        f"/v1/notebooks/{notebook}/files",
        files={"file": ("scan.pdf", scanned_pdf(), "application/pdf")},
        data={"title": "A scan"},
    )
    ingested(client, notebook)
    modules = client.get("/v1/corpus/modules?candidate_id=cand-bg").json()
    listed = next(m for m in modules if m["title"] == "A scan")
    assert listed["state"] == "stub"
    assert listed["selectable"] is False
    assert listed["stub_reason"]


def test_a_session_cannot_be_scoped_to_a_document_that_is_not_ready(client, notebook):
    from interviewer.api.deps import get_notebook_service

    uploaded = get_notebook_service().upload_source(
        notebook, source_id="src-waiting", title="Waiting", text=PROSE * 40
    )
    started = client.post("/v1/sessions", json={
        "candidate_id": "cand-bg",
        "module_ids": [uploaded.module_id],
        "duration_seconds": 600,
    })
    assert started.status_code == 422


# -- failure is a state on the document --------------------------------------

def test_a_failed_ingest_leaves_the_document_listed_and_marked_failed(
    content_db, counting
):
    from interviewer.notebooks import NotebookService

    class Exploding(type(counting)):
        def embed(self, texts):
            raise RuntimeError("the provider fell over")

    svc = NotebookService(content_db, embedder=Exploding())
    svc.create("nb-fail2", "cand-fail2", "Notes")
    uploaded = svc.upload_source(
        "nb-fail2", source_id="src-1", title="Notes", text=PROSE * 40
    )
    with pytest.raises(RuntimeError):
        svc.ingest_source("nb-fail2", uploaded.source_id)

    source = svc.store.get("nb-fail2").sources[0]
    assert source.state == "failed"
    assert "the provider fell over" in (source.stub_reason or "")
    # Nothing partial: no Module, no Topic, no chunk.
    assert svc.corpus("nb-fail2") is None
    assert svc.store.frozen_topics("nb-fail2") == {}
    assert svc.store.chunks_of("nb-fail2") == []


def test_a_killed_run_leaves_no_ledger_entry(content_db, clean_db, counting):
    from interviewer.metering.ledger import CreditLedger
    from interviewer.notebooks import NotebookService

    class Exploding(type(counting)):
        credits_per_1k_tokens = 1.0

        def embed(self, texts):
            raise RuntimeError("the provider fell over")

    ledger = CreditLedger(content_db)
    ledger.grant("cand-fail3", 100_000, "seed")
    svc = NotebookService(content_db, embedder=Exploding(), credits=ledger)
    svc.create("nb-fail3", "cand-fail3", "Notes")
    uploaded = svc.upload_source(
        "nb-fail3", source_id="src-1", title="Notes", text=PROSE * 40
    )
    with pytest.raises(RuntimeError):
        svc.ingest_source("nb-fail3", uploaded.source_id)
    assert ledger.balance("cand-fail3") == 100_000


def test_rows_left_ingesting_are_reset_at_startup(content_db, counting):
    """No timeout, and none invented: no worker survives a restart."""
    from interviewer.api import ingest_worker
    from interviewer.api.deps import get_notebook_service
    from interviewer.notebooks import NotebookService

    svc = NotebookService(content_db, embedder=counting)
    svc.create("nb-stale", "cand-stale", "Notes")
    uploaded = svc.upload_source(
        "nb-stale", source_id="src-1", title="Notes", text=PROSE * 40
    )
    assert svc.store.begin_ingest(uploaded.source_id) is True
    assert svc.store.get("nb-stale").sources[0].state == "ingesting"

    get_notebook_service.cache_clear()
    try:
        assert ingest_worker.reset_stale() >= 1
    finally:
        get_notebook_service.cache_clear()
    source = svc.store.get("nb-stale").sources[0]
    assert source.state == "failed"
    assert "restart" in (source.stub_reason or "")


def test_a_stalled_worker_reports_elapsed_time_and_last_progress(
    client, content_db, counting
):
    """The harder case, reported rather than guessed at."""
    from interviewer.api.deps import get_notebook_service

    svc = get_notebook_service()
    svc.create("nb-stall", "cand-bg", "Notes")
    uploaded = svc.upload_source(
        "nb-stall", source_id="src-1", title="Notes", text=PROSE * 40
    )
    svc.store.begin_ingest(uploaded.source_id)
    source = client.get("/v1/notebooks/nb-stall").json()["sources"][0]
    assert source["state"] == "ingesting"
    assert source["elapsed_seconds"] is not None
    assert source["since_progress_seconds"] is not None


# -- retry -------------------------------------------------------------------

def test_a_retry_re_ingests_without_re_uploading(client, notebook, ingested, tmp_path):
    from interviewer.api.deps import get_notebook_service

    svc = get_notebook_service()
    uploaded = svc.upload_source(
        notebook, source_id="src-retry", title="Notes", text=PROSE * 40
    )
    svc.store.fail_ingest(uploaded.source_id, "the provider fell over")

    response = client.post(
        f"/v1/notebooks/{notebook}/sources/{uploaded.source_id}/retry"
    )
    assert response.status_code == 202
    assert ingested(client, notebook, uploaded.source_id)["state"] == "ready"
    # One Source, not two: the bytes were never uploaded again.
    assert len(_sources(client, notebook)) == 1


def test_a_completed_ingest_cannot_be_retried_and_so_cannot_bill_twice(
    client, notebook, ingested
):
    body = _upload(client, notebook)
    ingested(client, notebook)
    response = client.post(
        f"/v1/notebooks/{notebook}/sources/{body['source_id']}/retry"
    )
    assert response.status_code == 409
    assert response.json()["code"] == "ingest_not_claimable"


def test_a_source_already_ingesting_refuses_a_second_start(client, notebook):
    """Two tabs race in the database, and exactly one of them wins."""
    from interviewer.api.deps import get_notebook_service
    from interviewer.notebooks import IngestNotClaimable

    svc = get_notebook_service()
    uploaded = svc.upload_source(
        notebook, source_id="src-race", title="Notes", text=PROSE * 40
    )
    assert svc.store.begin_ingest(uploaded.source_id) is True
    assert svc.store.begin_ingest(uploaded.source_id) is False
    with pytest.raises(IngestNotClaimable):
        svc.ingest_source(notebook, uploaded.source_id)


def test_retrying_a_document_in_a_shared_corpus_is_refused(client):
    from interviewer.api.deps import get_notebook_service
    from interviewer.db.content import SHARED

    svc = get_notebook_service()
    svc.create("nb-shared-retry", "platform", "InterviewLM", visibility=SHARED)
    uploaded = svc.upload_source(
        "nb-shared-retry", source_id="src-1", title="Notes",
        text=PROSE * 40, as_operator=True,
    )
    svc.store.fail_ingest(uploaded.source_id, "the provider fell over")
    response = client.post(
        f"/v1/notebooks/nb-shared-retry/sources/{uploaded.source_id}/retry"
    )
    assert response.status_code == 409
    assert response.json()["code"] == "corpus_is_shared"
