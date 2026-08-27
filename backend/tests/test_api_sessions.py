"""The HTTP contract, including the three rules it must structurally refuse."""

import pytest
from conftest import signed_in_client

#: A grant is made *about* somebody by whatever cleared their payment,
#: never *by* them, so the endpoint is the operator's (ADR-0026).
OPERATOR = {"x-operator-token": "dev-operator-token"}
from fastapi.testclient import TestClient

from interviewer.api import idempotency
from interviewer.api.app import create_app
from interviewer.api.wiring import wiring


@pytest.fixture()
def client(clean_db, served_corpus):
    """A client serving an imported Corpus.

    ISSUE-0037 removed the disk path, so material reaches the API by being
    imported into Postgres — `served_corpus` is `backend/scripts/import_corpus.py`
    without the command line around it.
    """
    wiring.cache_clear()
    idempotency.reset()
    return signed_in_client()


@pytest.fixture()
def module_ids(client):
    return [m["module_id"] for m in
            client.get("/v1/corpus/modules", params={"track": "aiml"}).json()]


def _start(client, module_ids, cand="c_api", seconds=1800, **kw):
    client.post("/v1/credits/grants", headers=OPERATOR,
                json={"candidate_id": cand, "credits": 90_000,
                      "payment_ref": f"pay_{cand}"})
    body = {"module_ids": module_ids[:1],
            "duration_seconds": seconds, **kw}
    r = client.post("/v1/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_starting_a_session_returns_a_question_and_a_visit_id(client, module_ids):
    b = _start(client, module_ids)
    assert b["kind"] == "question"
    assert b["question"] and b["topic_visit_id"] and b["session_id"]


def test_a_session_cannot_be_started_with_no_scope(client):
    r = client.post("/v1/sessions", json={
        "candidate_id": "c", "module_ids": [], "duration_seconds": 600})
    assert r.status_code == 422


def test_a_session_cannot_be_started_with_a_non_positive_duration(client, module_ids):
    r = client.post("/v1/sessions", json={
        "candidate_id": "c", "module_ids": module_ids[:1], "duration_seconds": 0})
    assert r.status_code == 422


def test_a_turn_returns_when_the_graph_next_parks(client, module_ids):
    b = _start(client, module_ids)
    r = client.post(f"/v1/sessions/{b['session_id']}/turns",
                    json={"answer": "an answer"})
    assert r.status_code == 200
    assert r.json()["kind"] in ("question", "probe", "hint", "visit_closed",
                                "session_ended")


def test_a_retried_turn_with_the_same_key_returns_the_original_result(
    client, module_ids
):
    b = _start(client, module_ids)
    h = {"Idempotency-Key": "same-key"}
    first = client.post(f"/v1/sessions/{b['session_id']}/turns",
                        json={"answer": "one"}, headers=h).json()
    again = client.post(f"/v1/sessions/{b['session_id']}/turns",
                        json={"answer": "one"}, headers=h).json()
    assert first == again


def test_a_retried_turn_writes_no_second_evidence_row(client, module_ids, clean_db):
    import sqlalchemy as sa
    from interviewer.db import schema as S

    b = _start(client, module_ids)
    h = {"Idempotency-Key": "k"}
    for _ in range(3):
        client.post(f"/v1/sessions/{b['session_id']}/turns",
                    json={"answer": "one"}, headers=h)
    with clean_db.connect() as c:
        n = c.execute(sa.select(sa.func.count()).select_from(S.evidence)).scalar()
    assert n == 1


def test_session_state_is_readable_and_lists_its_visits(client, module_ids):
    b = _start(client, module_ids)
    client.post(f"/v1/sessions/{b['session_id']}/turns", json={"answer": "a"})
    s = client.get(f"/v1/sessions/{b['session_id']}").json()
    assert s["state"] in ("running", "ended", "parked")
    assert s["visits"] and s["visits"][0]["topic_id"]
    assert s["duration_seconds"] == 1800


def test_ending_early_completes_the_current_topic_first(client, module_ids):
    b = _start(client, module_ids)
    r = client.post(f"/v1/sessions/{b['session_id']}/end").json()
    assert "finish" in r["note"]
    assert r["topic_visit_id"] == b["topic_visit_id"]


def test_an_unknown_session_is_a_404(client):
    assert client.get("/v1/sessions/nope").status_code == 404
    assert client.post("/v1/sessions/nope/turns", json={"answer": "x"}).status_code == 404


# -- the three structural refusals -------------------------------------------

def test_no_response_fuses_coverage_and_mastery(client, module_ids):
    b = _start(client, module_ids)
    client.post(f"/v1/sessions/{b['session_id']}/turns", json={"answer": "a"})
    for path in (
        f"/v1/sessions/{b['session_id']}/summary",
        "/v1/candidates/me/confidence",
    ):
        body = client.get(path).json()
        assert "coverage" in body and "mastery" in body
        flat = str(body).lower()
        for banned in ("overall_score", "combined", "percent_complete"):
            assert banned not in flat


def test_no_candidate_facing_route_returns_an_answer_key(client, module_ids, corpus):
    b = _start(client, module_ids)
    key_text = None
    for t in corpus.topics:
        if t.ground_truth_pairs:
            key_text = t.ground_truth_pairs[0][1].text
            break
    assert key_text

    for path in (
        f"/v1/sessions/{b['session_id']}",
        f"/v1/corpus/topics/{b['topic_id']}",
        "/v1/candidates/me/confidence",
    ):
        assert key_text[:120] not in client.get(path).text


def test_no_session_response_quotes_a_price_in_advance(client, module_ids):
    b = _start(client, module_ids)
    flat = str(b).lower()
    for banned in ("estimated_cost", "will_cost", "quote", "forecast"):
        assert banned not in flat


def test_a_byok_candidate_sees_no_credit_balance(client, module_ids):
    byok = signed_in_client("c_byok")
    byok.post("/v1/candidates/me/byok",
              json={"openrouter_key": "sk-or-v1-" + "a" * 32})
    body = byok.get("/v1/candidates/me/credits").json()
    assert body["route"] == "byok"
    assert body["balance"] is None          # not 0
    assert body["byok"]["credits_spent"] is None
    assert body["byok"]["fingerprint"]


def test_a_raw_vendor_key_is_refused_by_the_api(client):
    r = client.post("/v1/candidates/me/byok",
                    json={"openrouter_key": "sk-ant-api03-secret"})
    assert r.status_code == 400
    assert "OpenRouter" in r.json()["detail"]


def test_the_grant_endpoint_is_idempotent_on_the_payment_reference(client):
    a = client.post("/v1/credits/grants", headers=OPERATOR, json={
        "candidate_id": "c3", "credits": 100, "payment_ref": "same"}).json()
    b = client.post("/v1/credits/grants", headers=OPERATOR, json={
        "candidate_id": "c3", "credits": 100, "payment_ref": "same"}).json()
    assert b["already_granted"] is True
    assert signed_in_client("c3").get(
        "/v1/candidates/me/credits").json()["balance"] == 100


def test_the_summary_reports_spend_and_provenance(client, module_ids):
    b = _start(client, module_ids)
    client.post(f"/v1/sessions/{b['session_id']}/turns", json={"answer": "a"})
    s = client.get(f"/v1/sessions/{b['session_id']}/summary").json()
    assert s["spend"]["credits"] is not None
    assert s["provider"] == "deepseek"
    assert s["duration_seconds"] == 1800
