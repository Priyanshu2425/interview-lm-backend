"""ISSUE-0002 — the walking skeleton, tested through a scripted Session.

These assert what happened to the Session and what was written. They do not
assert which node ran in which order, how many model calls happened, or what a
prompt contained — that is exactly what ADR-0001 chose a graph in order to make
testable.
"""

import sqlalchemy as sa
import pytest
from sqlalchemy import text

from interviewer.confidence.math import PRIOR
from interviewer.corpus.contract import GradingMode
from interviewer.db import schema as S
from interviewer.graph.runner import SessionRunner
from interviewer.graph.sessions import SessionConfig

CANDIDATE = "cand_test"


def _cfg(deps, n_modules=1, seconds=1800):
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:n_modules]
    return SessionConfig(scope_module_ids=tuple(mods), duration_seconds=seconds)


def test_a_session_asks_a_question_and_one_answer_writes_one_evidence_row(deps, clean_db):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    assert first.kind == "question"
    assert first.payload["question"]
    assert first.payload["topic_visit_id"]

    out = r.submit(sid, "Because the dot products grow with d_k and softmax saturates.")
    assert out.kind == "question"
    closed = out.payload["last_visit"]
    assert closed["kind"] == "visit_closed"
    assert 0.0 <= closed["score"] <= 1.0

    with clean_db.connect() as c:
        n = c.execute(sa.select(sa.func.count()).select_from(S.evidence)).scalar()
    assert n == 1


def test_a_topic_visit_row_exists_before_the_first_model_call(deps, clean_db):
    """SPEC-0005 rejects a call without a topic_visit_id, so the row must precede it."""
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    calls = deps.ports.model.calls
    assert calls, "the question writer should have been called"
    assert all(c["topic_visit_id"] for c in calls)

    row = deps.visits.get(calls[0]["topic_visit_id"])
    assert row is not None and row["state"] == "open"


def test_the_exchange_is_stored_at_the_answer_turn_before_grading(deps):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    vid = first.payload["topic_visit_id"]
    r.submit(sid, "my answer")
    row = deps.visits.get(vid)
    assert row["exchange"]["turns"][-1]["text"] == "my answer"
    assert row["answered_at"] is not None
    assert row["graded_at"] is not None


def test_writing_evidence_twice_for_one_visit_leaves_the_posterior_unchanged(deps):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    vid = first.payload["topic_visit_id"]
    topic_id = first.payload["topic_id"]
    r.submit(sid, "an answer")

    after_first = deps.confidence.get(CANDIDATE, topic_id)
    again = deps.evidence.write(
        topic_visit_id=vid, candidate_id=CANDIDATE, topic_id=topic_id,
        session_id=sid, score=0.1, mode=GradingMode.GROUND_TRUTH,
        grader_kind="server_judge", provider="deepseek", rubric_version="v1",
    )
    assert again.already_existed
    assert deps.confidence.get(CANDIDATE, topic_id) == after_first


def test_a_session_never_visits_a_topic_outside_its_scope(deps):
    r = SessionRunner(deps)
    cfg = _cfg(deps, n_modules=1)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=cfg)
    in_scope = set(deps.corpus.topic_ids_for(list(cfg.scope_module_ids)))

    out = first
    for _ in range(12):
        if out.kind == "session_ended":
            break
        out = r.submit(sid, "answer")
    visited = deps.visits.visited_topic_ids(sid)
    assert visited
    assert visited <= in_scope


def test_no_topic_is_visited_twice_within_one_session(deps):
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    for _ in range(12):
        if out.kind == "session_ended":
            break
        out = r.submit(sid, "answer")
    rows = deps.visits.for_session(sid)
    ids = [x["topic_id"] for x in rows]
    assert len(ids) == len(set(ids))


def test_a_session_ends_when_its_scope_is_exhausted(deps):
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    for _ in range(20):
        if out.kind == "session_ended":
            break
        out = r.submit(sid, "answer")
    assert out.kind == "session_ended"
    assert out.payload["reason"] == "scope_exhausted"
    assert deps.sessions.get(sid)["state"] == "ended"


def test_the_soft_deadline_ends_after_the_current_visit_never_inside_it(deps):
    """A truncated Visit would leave no Evidence or half-examined Evidence."""
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps, seconds=60))
    deps.ports.clock.advance(3600)  # the deadline passes mid-Visit

    out = r.submit(sid, "an answer given after the clock ran out")
    assert out.kind == "session_ended"

    rows = deps.visits.for_session(sid)
    assert len(rows) == 1
    assert rows[0]["state"] == "graded"      # it completed
    assert out.payload["last_visit"]["score"] is not None


def test_an_interrupted_session_writes_no_evidence_for_the_open_visit(deps, clean_db):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    # the Candidate never answers
    with clean_db.connect() as c:
        n = c.execute(sa.select(sa.func.count()).select_from(S.evidence)).scalar()
    assert n == 0
    assert deps.visits.unresolved(sid)["state"] == "open"


def test_an_open_visit_blocks_a_second_one_in_the_same_session(deps):
    """CONTEXT.md's MCP invariant, enforced by a partial unique index."""
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    with pytest.raises(Exception) as e:
        deps.visits.open(
            session_id=sid, candidate_id=CANDIDATE,
            topic_id="some-other-topic", visit_index=99,
        )
    assert "uq_visit_one_open_per_session" in str(e.value)


def test_the_same_topic_cannot_be_opened_twice_in_one_session(deps):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    topic = first.payload["topic_id"]
    r.submit(sid, "answer")   # closes it
    with pytest.raises(Exception) as e:
        deps.visits.open(
            session_id=sid, candidate_id=CANDIDATE, topic_id=topic, visit_index=50
        )
    assert "uq_visit_session_topic" in str(e.value)


def test_session_scope_and_duration_are_immutable_in_the_database(deps, clean_db):
    r = SessionRunner(deps)
    sid, _ = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    for col, val in (("scope_module_ids", ["x"]), ("duration_seconds", 5)):
        with pytest.raises(Exception) as e:
            with clean_db.begin() as c:
                c.execute(
                    sa.update(S.session)
                    .where(S.session.c.session_id == sid)
                    .values(**{col: val})
                )
        assert "immutable" in str(e.value)


def test_evidence_is_append_only_in_the_database(deps, clean_db):
    r = SessionRunner(deps)
    sid, _ = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    r.submit(sid, "answer")
    for stmt in (
        sa.update(S.evidence).values(score=0),
        sa.delete(S.evidence),
    ):
        with pytest.raises(Exception) as e:
            with clean_db.begin() as c:
                c.execute(stmt)
        assert "append-only" in str(e.value)


def test_a_posterior_cannot_be_driven_below_the_prior(deps, clean_db):
    with pytest.raises(Exception) as e:
        with clean_db.begin() as c:
            c.execute(
                sa.insert(S.topic_confidence).values(
                    candidate_id=CANDIDATE, topic_id="t", alpha=0.5, beta=1.0
                )
            )
    assert "ck_confidence_prior_floor" in str(e.value)


def test_an_untested_topic_reads_as_the_prior_not_as_a_missing_row(deps):
    assert deps.confidence.get(CANDIDATE, "never-examined") == PRIOR
