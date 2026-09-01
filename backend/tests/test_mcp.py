"""ISSUE-0012 — MCP Mode.

The host is a ReAct agent we do not control, so these tests act like a
misbehaving one: skipping grading, grading twice, asking out of scope, and
trying to read the Answer Key.
"""

import pytest
import sqlalchemy as sa

from interviewer.db import schema as S
from interviewer.service.mcp.server import (
    HOST_TOOLS, McpServer, RedemptionRefused, ScopeViolation, VisitUnresolved,
)

CAND = "cand_mcp"


@pytest.fixture()
def mcp(deps, corpus):
    return McpServer(
        loader=deps.loader, corpus=deps.corpus, sessions=deps.sessions,
        visits=deps.visits, evidence=deps.evidence,
    )


@pytest.fixture()
def started(mcp, deps):
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:1]
    s = mcp.start_session(candidate_id=CAND, module_ids=mods, duration_seconds=1800)
    return s["session_id"]


def _answer_key_text(corpus, topic_id):
    t = corpus.topic(topic_id)
    return t.ground_truth_pairs[0][1].text if t.ground_truth_pairs else None


def test_the_host_never_receives_an_answer_key(mcp, started, corpus):
    topic = mcp.next_topic(session_id=started)
    key = _answer_key_text(corpus, topic["topic_id"])
    assert key, "this fixture needs a Ground Truth Topic"
    assert key[:150] not in topic["material"]

    also = mcp.load_topic(session_id=started, topic_id=topic["topic_id"])
    assert key[:150] not in also["material"]

    sub = mcp.submit_answer(
        topic_visit_id=topic["topic_visit_id"], question="q", answer="a",
        grading_mode="ground_truth",
    )
    assert key[:150] not in str(sub)


def test_no_tool_available_to_the_host_returns_grading_material(mcp):
    """The blast radius of a leaked ticket is what makes this survivable."""
    assert "redeem_grading_material" not in HOST_TOOLS


def test_the_judge_subagent_redeems_the_material_itself(mcp, started, corpus):
    topic = mcp.next_topic(session_id=started)
    key = _answer_key_text(corpus, topic["topic_id"])
    sub = mcp.submit_answer(
        topic_visit_id=topic["topic_visit_id"], question="q",
        answer="my answer", grading_mode="ground_truth",
    )
    material = mcp.redeem_grading_material(grading_ticket=sub["grading_ticket"])
    assert key[:150] in material["grounding"]
    assert material["answer"] == "my answer"
    assert material["rubric_version"]


def test_a_grading_ticket_is_single_use(mcp, started):
    topic = mcp.next_topic(session_id=started)
    sub = mcp.submit_answer(topic_visit_id=topic["topic_visit_id"],
                            question="q", answer="a", grading_mode="ground_truth")
    mcp.redeem_grading_material(grading_ticket=sub["grading_ticket"])
    with pytest.raises(RedemptionRefused):
        mcp.redeem_grading_material(grading_ticket=sub["grading_ticket"])


def test_an_unknown_ticket_is_refused(mcp):
    with pytest.raises(RedemptionRefused):
        mcp.redeem_grading_material(grading_ticket="tkt_invented")


def test_a_host_that_skips_grading_cannot_advance_the_session(mcp, started):
    mcp.next_topic(session_id=started)
    with pytest.raises(VisitUnresolved):
        mcp.next_topic(session_id=started)


def test_a_host_that_grades_twice_writes_once(mcp, started, clean_db):
    topic = mcp.next_topic(session_id=started)
    sub = mcp.submit_answer(topic_visit_id=topic["topic_visit_id"],
                            question="q", answer="a", grading_mode="ground_truth")
    first = mcp.record_score(topic_visit_id=topic["topic_visit_id"],
                             score=0.9, rationale="good")
    second = mcp.record_score(topic_visit_id=topic["topic_visit_id"],
                              score=0.1, rationale="trying again")
    assert first["recorded"] is True
    assert second["recorded"] is False

    with clean_db.connect() as c:
        n = c.execute(sa.select(sa.func.count()).select_from(S.evidence)).scalar()
    assert n == 1
    assert first["coverage"] == second["coverage"]


def test_a_host_asking_outside_scope_is_refused_by_the_server(mcp, started, corpus):
    outside = next(
        t.id for t in corpus.topics
        if t.id not in mcp.corpus.topic_ids_for(
            list(mcp.sessions.get(started)["scope_module_ids"]))
    )
    with pytest.raises(ScopeViolation):
        mcp.load_topic(session_id=started, topic_id=outside)


def test_a_host_claiming_ground_truth_where_none_exists_is_downgraded(mcp, deps):
    """Grading Mode is a fact about the grounding, not a setting the host picks."""
    genai = next(m for m in deps.corpus.modules("aiml")
                 if m.title.startswith("Basics of GenAI"))
    s = mcp.start_session(candidate_id="cand_mcp2", module_ids=[genai.module_id],
                          duration_seconds=1800)
    topic = mcp.next_topic(session_id=s["session_id"])
    sub = mcp.submit_answer(topic_visit_id=topic["topic_visit_id"], question="q",
                            answer="a", grading_mode="ground_truth")
    assert sub["grading_mode"] == "text_grounded"


def test_mcp_evidence_is_shaped_like_managed_evidence_and_named_differently(
    mcp, started, deps
):
    topic = mcp.next_topic(session_id=started)
    mcp.submit_answer(topic_visit_id=topic["topic_visit_id"], question="q",
                      answer="a", grading_mode="ground_truth")
    mcp.record_score(topic_visit_id=topic["topic_visit_id"], score=0.8,
                     rationale="fine")
    row = deps.evidence.rows_for(CAND)[0]
    assert row["grader_kind"] == "judge_subagent"
    assert row["provider"] is None          # the host's subscription paid
    assert row["rubric_version"]
    assert row["exchange_snapshot"]["turns"]


def test_an_mcp_session_writes_no_ledger_rows_against_our_key(
    mcp, started, clean_db
):
    topic = mcp.next_topic(session_id=started)
    mcp.submit_answer(topic_visit_id=topic["topic_visit_id"], question="q",
                      answer="a", grading_mode="ground_truth")
    mcp.record_score(topic_visit_id=topic["topic_visit_id"], score=0.7,
                     rationale="ok")
    with clean_db.connect() as c:
        ledger = c.execute(sa.select(sa.func.count()).select_from(S.credit_ledger)).scalar()
        calls = c.execute(sa.select(sa.func.count()).select_from(S.call_record)).scalar()
    assert ledger == 0 and calls == 0


def test_the_mcp_session_is_marked_as_such(mcp, started, deps):
    row = deps.sessions.get(started)
    assert row["mode"] == "mcp"
    assert row["payment_route"] == "mcp"
    assert row["provider_chosen"] is None


def test_weights_are_set_by_grading_mode_alone_with_no_mode_four(mcp, started, deps):
    topic = mcp.next_topic(session_id=started)
    mcp.submit_answer(topic_visit_id=topic["topic_visit_id"], question="q",
                      answer="a", grading_mode="ground_truth")
    mcp.record_score(topic_visit_id=topic["topic_visit_id"], score=1.0, rationale="")
    row = deps.evidence.rows_for(CAND)[0]
    assert float(row["weight"]) in (1.0, 0.7, 0.5)


def test_a_score_outside_the_unit_interval_is_refused(mcp, started):
    topic = mcp.next_topic(session_id=started)
    mcp.submit_answer(topic_visit_id=topic["topic_visit_id"], question="q",
                      answer="a", grading_mode="ground_truth")
    with pytest.raises(ValueError):
        mcp.record_score(topic_visit_id=topic["topic_visit_id"], score=1.5,
                         rationale="")
