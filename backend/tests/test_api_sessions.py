"""The HTTP contract, including the three rules it must structurally refuse."""

import pytest
from conftest import signed_in_client

#: A grant is made *about* somebody by whatever cleared their payment,
#: never *by* them, so the endpoint is the operator's (ADR-0026).
OPERATOR = {"x-operator-token": "dev-operator-token"}
from fastapi.testclient import TestClient

from interviewer import idempotency
from interviewer.app import create_app
from interviewer.wiring import wiring


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
            client.get("/v1/skills/modules", params={"track": "aiml"}).json()]


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


def test_a_retried_turn_writes_no_second_answer_to_the_transcript(
    client, module_ids, clean_db
):
    """Rewritten by ISSUE-0042: there is no Evidence row to count any more.

    What idempotency protects is the same fact under a different name — one
    Answer Turn per key — and the transcript is where that fact now lives.
    `message` is append-only, so a duplicate could never be tidied away.
    """
    import sqlalchemy as sa
    from interviewer.db import schema as S

    b = _start(client, module_ids)
    h = {"Idempotency-Key": "k"}
    for _ in range(3):
        client.post(f"/v1/sessions/{b['session_id']}/turns",
                    json={"answer": "one"}, headers=h)
    with clean_db.connect() as c:
        answers = c.execute(
            sa.select(S.message.c.text)
            .where(S.message.c.session_id == b["session_id"],
                   S.message.c.kind == "answer")
        ).scalars().all()
        evidence = c.execute(
            sa.select(sa.func.count()).select_from(S.evidence)).scalar()
    assert answers == ["one"]
    assert evidence == 0


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
        f"/v1/skills/topics/{b['topic_id']}",
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


def test_the_route_defaults_to_the_key_situation(client, module_ids):
    """Omitted means "whatever my key situation implies"."""
    assert _start(client, module_ids)["payment_route"] == "credits"

    byok = signed_in_client("c_default_byok")
    byok.post("/v1/candidates/me/byok",
              json={"openrouter_key": "sk-or-v1-" + "b" * 32})
    assert _start(byok, module_ids,
                  cand="c_default_byok")["payment_route"] == "byok"


def test_a_candidate_with_a_key_may_still_choose_credits(client, module_ids):
    """The choice is obeyed, and it is not a double charge.

    The two routes send different keys: on `credits` the call goes out on ours
    and the cents land on the ledger, and the attached key is left unused.
    """
    cand = "c_chose_credits"
    byok = signed_in_client(cand)
    byok.post("/v1/candidates/me/byok",
              json={"openrouter_key": "sk-or-v1-" + "c" * 32})
    body = _start(byok, module_ids, cand=cand, payment_route="credits")
    assert body["payment_route"] == "credits"


def test_choosing_own_key_without_one_is_refused(client, module_ids):
    r = client.post("/v1/sessions", json={
        "module_ids": module_ids[:1], "duration_seconds": 600,
        "payment_route": "byok"})
    assert r.status_code == 409
    assert "no active key" in r.json()["detail"]


def test_the_mcp_route_is_not_a_candidates_to_pick(client, module_ids):
    r = client.post("/v1/sessions", json={
        "module_ids": module_ids[:1], "duration_seconds": 600,
        "payment_route": "mcp"})
    assert r.status_code == 422


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


def test_one_session_reports_one_total(client, module_ids):
    """`/spend` and `/summary` bill the same Session the same.

    They used to disagree: `/spend` billed the planning call and every Visit,
    `/summary` billed neither the planning call nor a Visit short of
    `answered`. The Candidate saw the smaller figure beside their result.
    """
    b = _start(client, module_ids)
    sid = b["session_id"]
    client.post(f"/v1/sessions/{sid}/turns", json={"answer": "a"})

    spend = client.get(f"/v1/sessions/{sid}/spend").json()
    summary = client.get(f"/v1/sessions/{sid}/summary").json()["spend"]

    assert spend["credits"] == summary["credits"]
    assert spend["planning"] == summary["planning"]
    assert spend["balance"] == summary["balance"]


def test_the_planning_call_is_billed_and_carried_on_its_own_line(client, module_ids):
    """Planning is a charge belonging to no Visit (ISSUE-0041)."""
    b = _start(client, module_ids)
    sid = b["session_id"]
    client.post(f"/v1/sessions/{sid}/turns", json={"answer": "a"})

    spend = client.get(f"/v1/sessions/{sid}/spend").json()
    visits_total = sum(v["credits"] for v in spend["per_visit"])
    assert spend["planning"] is not None
    assert spend["credits"] == spend["planning"] + visits_total


# -- the Sessions a Candidate has sat ----------------------------------------
#
# The list the Session screen is a rendering of. What it must say is what
# happened; what it must never say is how it went, because a Session has no
# reading — Coverage and Mastery are two readings of one Topic, and a Session
# is not a Topic.


def test_a_candidate_sees_the_sessions_they_have_sat(client, module_ids):
    started = _start(client, module_ids)
    listed = client.get("/v1/sessions").json()["sessions"]

    assert [s["session_id"] for s in listed] == [started["session_id"]]
    row = listed[0]
    assert row["state"] == "running"
    assert row["started_at"]
    assert row["module_ids"] == module_ids[:1]
    assert row["duration_seconds"] == 1800


def test_the_listing_carries_no_reading_of_any_kind(client, module_ids):
    """The refusal, enforced as an absent field rather than as care at the
    call site: there is nothing here a score could be read out of."""
    _start(client, module_ids)
    row = client.get("/v1/sessions").json()["sessions"][0]

    for absent in ("score", "mastery", "coverage", "band", "grade", "result"):
        assert absent not in row


def test_a_session_says_how_far_into_its_plan_it_got(client, module_ids):
    """`questions_asked` against `budget_questions` is a position, not a
    performance. A Session that asked two of five has not failed three."""
    _start(client, module_ids)
    row = client.get("/v1/sessions").json()["sessions"][0]

    assert row["questions_asked"] >= 0
    assert row["topics_measured"] == 0, "nothing is measured until a Session ends"
    # Null rather than zero where there is no plan at all.
    assert row["budget_questions"] is None or row["budget_questions"] > 0


def test_topics_measured_counts_evidence_once_the_session_ends(client, module_ids):
    started = _start(client, module_ids, seconds=1800)
    client.post(f"/v1/sessions/{started['session_id']}/turns",
                json={"answer": "Broadcasting aligns shapes from the trailing dimension."})
    client.post(f"/v1/sessions/{started['session_id']}/end")

    row = client.get("/v1/sessions").json()["sessions"][0]
    assert row["state"] in ("ended", "parked")
    if row["state"] == "ended":
        assert row["topics_measured"] >= 1
        assert row["ended_reason"]


def test_newest_first(client, module_ids):
    first = _start(client, module_ids)
    client.post(f"/v1/sessions/{first['session_id']}/end")
    second = _start(client, module_ids)

    listed = client.get("/v1/sessions").json()["sessions"]
    assert [s["session_id"] for s in listed][0] == second["session_id"]


def test_one_candidates_sessions_are_not_anothers(client, module_ids):
    _start(client, module_ids)
    with signed_in_client("cand-a-stranger") as stranger:
        assert stranger.get("/v1/sessions").json()["sessions"] == []


def test_a_candidate_who_has_sat_none_gets_a_list_rather_than_an_error(client):
    assert client.get("/v1/sessions").json() == {"sessions": []}
