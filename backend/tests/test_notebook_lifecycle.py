"""ISSUE-0027 — two persistence layers with opposite lifecycles, meeting at a
delete button.

The product exists to build a durable, honest record. That record cannot be as
durable as the Candidate's file hygiene, and their material cannot be less
deletable than the record is permanent. Both hold here, or neither does.
"""

from __future__ import annotations

import pytest
from conftest import signed_in_client
from fastapi.testclient import TestClient


@pytest.fixture()
def client(content_db, clean_db):
    from interviewer.api.app import create_app
    from interviewer.api.deps import refresh_corpus

    refresh_corpus()
    with signed_in_client() as c:
        yield c
    refresh_corpus()


def _notebook_with_a_graded_visit(client, ingested, real_notes, candidate="cand-l"):
    created = client.post(
        "/v1/notebooks", json={"candidate_id": candidate, "title": "Notes"}
    ).json()
    notebook_id = created["notebook_id"]
    module_id = client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "AIML notes", "text": real_notes},
    ).json()["module_id"]
    # The upload outlives the ingestion (ISSUE-0035), so a Module exists only
    # once the embedding has finished. Waiting is what the Library does.
    ingested(client, notebook_id)
    started = client.post(
        "/v1/sessions",
        json={
            "candidate_id": candidate,
            "module_ids": [module_id],
            "duration_seconds": 600,
        },
    ).json()
    session_id = started["session_id"]
    for _ in range(6):
        result = client.post(
            f"/v1/sessions/{session_id}/turns",
            json={"answer": "Averaging cancels the differences between resamples."},
        ).json()
        payload = result.get("payload", {})
        if payload.get("kind") == "visit_closed":
            break
    return notebook_id, module_id, session_id, candidate


# -- upload ------------------------------------------------------------------


def test_each_source_reports_its_own_state(client, ingested, real_notes):
    from pdf_fixtures import scanned_pdf

    created = client.post(
        "/v1/notebooks", json={"candidate_id": "cand-u", "title": "Mixed"}
    ).json()
    notebook_id = created["notebook_id"]
    client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "Good notes", "text": real_notes},
    )
    client.post(
        f"/v1/notebooks/{notebook_id}/files",
        files={"file": ("scan.pdf", scanned_pdf(), "application/pdf")},
        data={"title": "A scan"},
    )
    ingested(client, notebook_id)

    listed = client.get("/v1/notebooks", params={"candidate_id": "cand-u"}).json()
    states = {s["title"]: s for s in listed[0]["sources"]}
    assert states["Good notes"]["state"] == "ready"
    assert states["A scan"]["state"] == "stub"
    assert states["A scan"]["stub_reason"]


def test_a_session_can_be_scoped_to_ready_modules_while_others_are_stubs(
    client, ingested, real_notes
):
    notebook_id, module_id, _, _ = _notebook_with_a_graded_visit(
        client, ingested, real_notes, candidate="cand-mix"
    )
    from pdf_fixtures import scanned_pdf

    client.post(
        f"/v1/notebooks/{notebook_id}/files",
        files={"file": ("scan.pdf", scanned_pdf(), "application/pdf")},
        data={"title": "A scan"},
    )
    started = client.post(
        "/v1/sessions",
        json={
            "candidate_id": "cand-mix",
            "module_ids": [module_id],
            "duration_seconds": 600,
        },
    )
    assert started.status_code == 201


# -- delete ------------------------------------------------------------------


def test_deleting_a_notebook_empties_content_and_keeps_every_evidence_row(
    client, ingested, real_notes, engine
):
    from interviewer.confidence.store import ConfidenceStore, EvidenceLedger

    notebook_id, _, session_id, candidate = _notebook_with_a_graded_visit(
        client, ingested, real_notes
    )
    before = EvidenceLedger(engine).for_session(session_id)
    assert before, "no Evidence to protect"
    topic_id = before[0]["topic_id"]
    posterior_before = ConfidenceStore(engine).get(candidate, topic_id)

    assert client.delete(f"/v1/notebooks/{notebook_id}").status_code == 204

    after = EvidenceLedger(engine).for_session(session_id)
    assert [r["evidence_id"] for r in after] == [r["evidence_id"] for r in before]
    posterior_after = ConfidenceStore(engine).get(candidate, topic_id)
    assert (posterior_after.alpha, posterior_after.beta) == (
        posterior_before.alpha,
        posterior_before.beta,
    )


def test_a_retired_topic_is_gone_from_the_picker_and_refused_by_a_session(
    client, ingested, real_notes
):
    notebook_id, module_id, _, candidate = _notebook_with_a_graded_visit(
        client, ingested, real_notes, candidate="cand-retire"
    )
    client.delete(f"/v1/notebooks/{notebook_id}")

    listed = client.get(
        "/v1/corpus/modules", params={"candidate_id": candidate}
    ).json()
    assert module_id not in {m["module_id"] for m in listed}

    refused = client.post(
        "/v1/sessions",
        json={
            "candidate_id": candidate,
            "module_ids": [module_id],
            "duration_seconds": 600,
        },
    )
    assert refused.status_code == 422


def test_the_record_still_reads_after_the_material_is_gone(client, ingested, real_notes):
    notebook_id, _, session_id, candidate = _notebook_with_a_graded_visit(
        client, ingested, real_notes, candidate="cand-record"
    )
    before = client.get(f"/v1/sessions/{session_id}/summary").json()
    assert before["per_topic"]

    client.delete(f"/v1/notebooks/{notebook_id}")

    after = client.get(f"/v1/sessions/{session_id}/summary").json()
    assert len(after["per_topic"]) == len(before["per_topic"])
    for was, now in zip(before["per_topic"], after["per_topic"]):
        assert now["title"] == was["title"]
        assert now["module_title"] == was["module_title"]
        assert now["citations"] == was["citations"]
        assert now["citations"], "a citation vanished with the notebook"


def test_a_retired_topic_keeps_its_coverage_and_its_reading(
    client, ingested, real_notes, engine
):
    notebook_id, _, session_id, candidate = _notebook_with_a_graded_visit(
        client, ingested, real_notes, candidate="cand-cov"
    )
    # The readings are the signed-in Candidate's, and the fixtures run as the
    # default one — so ask as them rather than naming an id nothing accepts.
    before = client.get("/v1/candidates/me/confidence").json()
    client.delete(f"/v1/notebooks/{notebook_id}")
    after = client.get("/v1/candidates/me/confidence").json()

    assert after["coverage"]["topics_examined"] == before["coverage"]["topics_examined"]
    assert after["topics"], "the Candidate's readings vanished with their files"
    assert [t["topic_id"] for t in after["topics"]] == [
        t["topic_id"] for t in before["topics"]
    ]


def test_deleting_one_source_retires_only_that_modules_topics(
    client, ingested, real_notes
):
    created = client.post(
        "/v1/notebooks", json={"candidate_id": "cand-one", "title": "Two files"}
    ).json()
    notebook_id = created["notebook_id"]
    first = client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "File one", "text": real_notes},
    ).json()
    second = client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={
            "title": "File two",
            "text": real_notes.replace("Revison", "Second file") + "\n\nExtra.\n",
        },
    ).json()
    ingested(client, notebook_id)

    deleted = client.delete(
        f"/v1/notebooks/{notebook_id}/sources/{first['source_id']}"
    )
    assert deleted.status_code == 204

    listed = {
        m["module_id"]
        for m in client.get(
            "/v1/corpus/modules", params={"candidate_id": "cand-one"}
        ).json()
    }
    assert first["module_id"] not in listed
    assert second["module_id"] in listed


def test_deleting_a_notebook_mid_session_ends_it_after_the_current_visit(
    client, ingested, real_notes, engine
):
    """The soft deadline already built for duration, reused for deletion."""
    from interviewer.confidence.store import EvidenceLedger

    created = client.post(
        "/v1/notebooks", json={"candidate_id": "cand-mid", "title": "Notes"}
    ).json()
    notebook_id = created["notebook_id"]
    module_id = client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "AIML notes", "text": real_notes},
    ).json()["module_id"]
    ingested(client, notebook_id)
    started = client.post(
        "/v1/sessions",
        json={
            "candidate_id": "cand-mid",
            "module_ids": [module_id],
            "duration_seconds": 600,
        },
    ).json()
    session_id = started["session_id"]

    client.delete(f"/v1/notebooks/{notebook_id}")

    # The Visit in flight still finishes and still writes its Evidence.
    for _ in range(6):
        result = client.post(
            f"/v1/sessions/{session_id}/turns",
            json={"answer": "Bagging attacks variance."},
        )
        assert result.status_code == 200, result.text
        payload = result.json().get("payload", {})
        if payload.get("kind") in {"visit_closed", "session_ended"}:
            break

    rows = EvidenceLedger(engine).for_session(session_id)
    assert rows, "the Visit in flight wrote nothing"
    session = client.get(f"/v1/sessions/{session_id}").json()
    assert session["state"] == "ended"
