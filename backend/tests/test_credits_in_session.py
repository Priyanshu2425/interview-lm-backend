"""ISSUE-0009 — credits inside a running Session.

The decision this file exists to prove: a Visit runs to completion on an
exhausted balance, and the Session stops at the boundary instead.
"""

import sqlalchemy as sa

from interviewer.db import schema as S
from interviewer.service.graph.runner_service import SessionRunner
from interviewer.service.graph.sessions import SessionConfig
from interviewer.model.credits_models import HEADROOM_CREDITS

CAND = "cand_credit_session"


def _cfg(d, n=1, seconds=3600, route="credits"):
    mods = [m.module_id for m in d.corpus.modules("aiml")][:n]
    return SessionConfig(scope_module_ids=tuple(mods), duration_seconds=seconds,
                         payment_route=route)


def test_a_session_spends_credits_attributable_to_each_topic_visit(metered_deps):
    d = metered_deps
    d.credits.grant(CAND, 10_000, "pay_1")
    r = SessionRunner(d)
    sid, first = r.start(candidate_id=CAND, cfg=_cfg(d))
    vid = first.payload["topic_visit_id"]
    r.submit(sid, "an answer")

    assert d.credits.visit_cost(vid) > 0
    assert d.credits.balance(CAND) < 10_000
    rows = [x for x in d.credits.rows(CAND) if x["entry_type"] == "debit"]
    assert rows and all(x["topic_visit_id"] for x in rows)


def test_every_call_in_a_visit_shares_that_visits_binding(metered_deps, clean_db):
    d = metered_deps
    d.credits.grant(CAND, 10_000, "p")
    r = SessionRunner(d)
    sid, first = r.start(candidate_id=CAND, cfg=_cfg(d))
    vid = first.payload["topic_visit_id"]
    r.submit(sid, "answer")

    with clean_db.connect() as c:
        providers = {
            row[0] for row in c.execute(
                sa.select(S.call_record.c.provider)
                .where(S.call_record.c.topic_visit_id == vid)
            ).all()
        }
    assert providers == {d.bindings.get(vid).provider}


def test_the_session_parks_at_the_boundary_when_the_balance_is_short(metered_deps):
    d = metered_deps
    d.credits.grant(CAND, HEADROOM_CREDITS + 20, "p")
    r = SessionRunner(d)
    sid, out = r.start(candidate_id=CAND, cfg=_cfg(d))
    for _ in range(10):
        out = r.submit(sid, "answer")
        if out.kind == "session_ended":
            break
    assert out.payload["reason"].startswith("credits_exhausted")
    assert d.sessions.get(sid)["state"] == "parked"


def test_a_visit_already_open_completes_even_when_the_balance_runs_out(metered_deps):
    """The decision the design settles in the Evidence model's favour."""
    d = metered_deps
    d.credits.grant(CAND, 10, "p")            # far below headroom
    r = SessionRunner(d)
    sid, first = r.start(candidate_id=CAND, cfg=_cfg(d))
    vid = first.payload["topic_visit_id"]

    out = r.submit(sid, "an answer given while broke")

    row = d.visits.get(vid)
    assert row["state"] == "answered"         # it finished
    assert d.credits.balance(CAND) < 0        # and went negative doing so
    assert out.payload["reason"] == "credits_exhausted_mid_visit"


def test_no_partial_visit_is_written_when_the_session_parks(metered_deps, clean_db):
    d = metered_deps
    d.credits.grant(CAND, HEADROOM_CREDITS + 5, "p")
    r = SessionRunner(d)
    sid, out = r.start(candidate_id=CAND, cfg=_cfg(d))
    for _ in range(10):
        out = r.submit(sid, "answer")
        if out.kind == "session_ended":
            break
    rows = d.visits.for_session(sid)
    # Answered rather than graded since ISSUE-0042: a question the Session
    # finished asking is complete, and the grade arrives once, at the end.
    assert all(x["state"] == "answered" for x in rows)


def test_topping_up_resumes_the_same_session(metered_deps):
    d = metered_deps
    d.credits.grant(CAND, HEADROOM_CREDITS + 10, "p1")
    r = SessionRunner(d)
    sid, out = r.start(candidate_id=CAND, cfg=_cfg(d))
    for _ in range(10):
        out = r.submit(sid, "answer")
        if out.kind == "session_ended":
            break
    assert d.sessions.get(sid)["state"] == "parked"

    d.credits.grant(CAND, 20_000, "p2")
    back = r.resume_after_interruption(sid)
    assert back is not None
    assert d.sessions.get(sid)["state"] == "running"


def test_an_ungraded_visit_still_cost_money(metered_deps):
    """Spend and Evidence are independent facts."""
    d = metered_deps
    d.credits.grant(CAND, 10_000, "p")
    r = SessionRunner(d)
    sid, first = r.start(candidate_id=CAND, cfg=_cfg(d))
    vid = first.payload["topic_visit_id"]
    # never answered: the question writer already spent
    assert d.credits.visit_cost(vid) > 0
    assert d.evidence.rows_for(CAND) == []


def test_a_refund_for_our_failure_returns_that_visits_spend(metered_deps):
    d = metered_deps
    d.credits.grant(CAND, 10_000, "p")
    r = SessionRunner(d)
    sid, first = r.start(candidate_id=CAND, cfg=_cfg(d))
    vid = first.payload["topic_visit_id"]
    spent_before = d.credits.balance(CAND)
    cost = d.credits.visit_cost(vid)

    d.credits.refund_visit(vid, "our failure")
    assert d.credits.balance(CAND) == spent_before + cost


def test_a_byok_session_runs_and_spends_no_credits(metered_deps):
    d = metered_deps
    r = SessionRunner(d)
    sid, first = r.start(candidate_id=CAND, cfg=_cfg(d, route="byok"))
    out = r.submit(sid, "an answer")

    assert d.credits.balance(CAND) == 0
    assert [x for x in d.credits.rows(CAND)] == []
    assert out.kind in ("question", "session_ended")
    assert d.visits.get(first.payload["topic_visit_id"])["state"] == "answered"
    assert d.transport.sent[0]["api_key"] == "sk-or-candidate"


def test_a_byok_session_is_never_gated_on_a_balance(metered_deps):
    """They spend no Credits, so there is nothing to gate on."""
    d = metered_deps
    r = SessionRunner(d)
    sid, out = r.start(candidate_id=CAND, cfg=_cfg(d, route="byok"))
    for _ in range(6):
        out = r.submit(sid, "answer")
        if out.kind == "session_ended":
            break
    assert not str(out.payload.get("reason", "")).startswith("credits")


def test_the_spend_gate_has_exactly_one_call_site():
    import pathlib
    import re

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "interviewer"
    hits = [
        f"{f.relative_to(src)}:{i}"
        for f in src.rglob("*.py")
        for i, line in enumerate(f.read_text().splitlines(), 1)
        if re.search(r"\.clears_headroom\(", line) and "def " not in line
    ]
    assert len(hits) == 1, hits
    assert "machine_service.py" in hits[0]
