"""The stories that needed dedicated work after the thirteen slices landed."""

import pytest
from decimal import Decimal
from fastapi.testclient import TestClient

from interviewer.api import idempotency
from interviewer.api.app import create_app
from interviewer.api.wiring import wiring
from interviewer.confidence.summary import SummaryService
from interviewer.graph.runner import SessionRunner
from interviewer.graph.sessions import SessionConfig
from interviewer.mcp.server import (
    TOOL_DESCRIPTIONS, HOST_TOOLS, SUBAGENT_TOOLS, McpServer,
)
from interviewer.metering.ledger import CreditLedger, PoolLedger
from interviewer.metering.operator import PriceService


@pytest.fixture()
def client(clean_db):
    wiring.cache_clear()
    idempotency.reset()
    return TestClient(create_app())


# -- PRD-0004 ----------------------------------------------------------------

def _mcp(deps, corpus):
    return McpServer(
        loader=deps.loader, corpus=deps.corpus, sessions=deps.sessions,
        visits=deps.visits, evidence=deps.evidence,
        summary=SummaryService(corpus, deps.confidence, deps.visits, deps.evidence),
    )


def test_the_host_can_end_a_session_and_receive_a_summary(deps, corpus):
    m = _mcp(deps, corpus)
    mods = [x.module_id for x in deps.corpus.modules("aiml")][:1]
    s = m.start_session(candidate_id="c_end", module_ids=mods, duration_seconds=900)
    t = m.next_topic(session_id=s["session_id"])
    m.submit_answer(topic_visit_id=t["topic_visit_id"], question="q", answer="a",
                    grading_mode="ground_truth")
    m.record_score(topic_visit_id=t["topic_visit_id"], score=0.8, rationale="ok")

    out = m.end_session(session_id=s["session_id"])
    assert out["ended"] is True
    assert out["summary"]["coverage"]["topics_total"] == 71
    assert out["summary"]["mastery"] is not None


def test_ending_with_an_unresolved_visit_is_refused_softly(deps, corpus):
    m = _mcp(deps, corpus)
    mods = [x.module_id for x in deps.corpus.modules("aiml")][:1]
    s = m.start_session(candidate_id="c_end2", module_ids=mods, duration_seconds=900)
    t = m.next_topic(session_id=s["session_id"])
    out = m.end_session(session_id=s["session_id"])
    assert out["ended"] is False
    assert out["topic_visit_id"] == t["topic_visit_id"]


def test_a_subagent_that_cannot_reach_the_server_is_recorded_not_lost(deps, corpus):
    m = _mcp(deps, corpus)
    mods = [x.module_id for x in deps.corpus.modules("aiml")][:1]
    s = m.start_session(candidate_id="c_unreach", module_ids=mods,
                        duration_seconds=900)
    t = m.next_topic(session_id=s["session_id"])
    m.submit_answer(topic_visit_id=t["topic_visit_id"], question="q", answer="a",
                    grading_mode="ground_truth")

    out = m.record_grading_unreachable(topic_visit_id=t["topic_visit_id"],
                                       detail="subagent had no network")
    assert out["session_state"] == "parked"
    assert deps.evidence.rows_for("c_unreach") == []      # no Evidence written
    assert deps.visits.get(t["topic_visit_id"])["state"] == "answered"


def test_tool_descriptions_state_the_intended_loop(deps):
    for name in HOST_TOOLS | SUBAGENT_TOOLS:
        assert name in TOOL_DESCRIPTIONS, name
        assert len(TOOL_DESCRIPTIONS[name]) > 40
    assert "never enter this conversation" in TOOL_DESCRIPTIONS["submit_answer"]
    assert "SUBAGENT ONLY" in TOOL_DESCRIPTIONS["redeem_grading_material"]


# -- PRD-0005 ----------------------------------------------------------------

def test_provider_prices_are_history_and_say_they_are_not_a_forecast(client):
    body = client.get("/v1/providers/prices").json()
    assert body["session_total_quotable"] is False
    assert "not knowable before it runs" in body["why"]


def test_provider_prices_come_from_what_visits_actually_cost(clean_db):
    from interviewer.metering.client import Binding, MeteredModelClient
    from interviewer.metering.transport import ScriptedTransport

    for provider, cost, visit in (
        ("deepseek", Decimal("0.18"), "v1"),
        ("claude", Decimal("0.96"), "v2"),
    ):
        c = MeteredModelClient(clean_db, ScriptedTransport(cost_usd=cost),
                               CreditLedger(clean_db))
        c.bind(Binding(visit, provider, "credits"), session_id="s", candidate_id="c")
        c.complete(topic_visit_id=visit, role="judge", system="s", user="u")

    prices = {p["provider"]: p for p in PriceService(clean_db).per_visit()}
    assert prices["deepseek"]["credits_per_visit"] == 18
    assert prices["claude"]["credits_per_visit"] == 96
    assert "not a forecast" in prices["claude"]["basis"]


def test_a_running_total_is_available_mid_session(client, served_corpus):
    mods = [m["module_id"] for m in
            client.get("/v1/corpus/modules", params={"track": "aiml"}).json()][:1]
    client.post("/v1/credits/grants", json={
        "candidate_id": "c_run", "credits": 50_000, "payment_ref": "p"})
    b = client.post("/v1/sessions", json={
        "candidate_id": "c_run", "module_ids": mods, "duration_seconds": 1800}).json()
    client.post(f"/v1/sessions/{b['session_id']}/turns", json={"answer": "a"})

    spend = client.get(f"/v1/sessions/{b['session_id']}/spend").json()
    assert spend["credits"] > 0
    assert spend["balance"] < 50_000
    assert spend["per_visit"]


def test_a_provider_failure_mid_visit_parks_rather_than_switching(metered_deps):
    d = metered_deps
    d.credits.grant("c_pf", 50_000, "p")
    r = SessionRunner(d)
    mods = [m.module_id for m in d.corpus.modules("aiml")][:1]
    sid, first = r.start(candidate_id="c_pf",
                         cfg=SessionConfig(scope_module_ids=tuple(mods),
                                           duration_seconds=1800))
    vid = first.payload["topic_visit_id"]
    bound = d.bindings.get(vid).provider

    d.transport.fail_with = "provider_unavailable"
    out = r.submit(sid, "an answer")

    assert out.kind == "session_parked"
    assert out.payload["code"] == "PROVIDER_UNAVAILABLE"
    assert d.sessions.get(sid)["parked_reason"] == "provider_failure"
    # no failover: the binding is untouched and no Evidence was written
    assert d.bindings.get(vid).provider == bound
    assert d.evidence.rows_for("c_pf") == []


def test_the_pool_is_prefunded_ahead_of_receipts(clean_db):
    pool = PoolLedger(clean_db)
    assert pool.prefunded_for(10_000) is False
    pool.topup(1_000_000, "bank_transfer_1")
    assert pool.prefunded_for(10_000) is True

    CreditLedger(clean_db).grant("c", 995_000, "p")
    assert pool.prefunded_for(10_000) is False    # would breach the invariant


def test_the_weakest_reading_is_exposed_and_excludes_untested(client, clean_db, corpus):
    import sqlalchemy as sa
    from interviewer.db import schema as S

    ids = [t.id for t in corpus.topics[:2]]
    with clean_db.begin() as c:
        c.execute(sa.insert(S.candidate).values(candidate_id="c_weak"))
        c.execute(sa.insert(S.topic_confidence).values(
            candidate_id="c_weak", topic_id=ids[0], alpha=3.6, beta=7.4))
        c.execute(sa.insert(S.topic_confidence).values(
            candidate_id="c_weak", topic_id=ids[1], alpha=1.0, beta=1.0))
    body = client.get("/v1/candidates/c_weak/weakest").json()
    assert [t["topic_id"] for t in body["topics"]] == [ids[0]]
    assert body["topics"][0]["mastery"] is not None
