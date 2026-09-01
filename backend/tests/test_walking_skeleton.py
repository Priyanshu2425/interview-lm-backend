"""ISSUE-0002 — the walking skeleton, tested through a scripted Session.

These assert what happened to the Session and what was written. They do not
assert which node ran in which order, how many model calls happened, or what a
prompt contained — that is exactly what ADR-0001 chose a graph in order to make
testable.

Rewritten in places by ISSUE-0042. A running Session no longer grades anything:
it executes a plan, writes a transcript, and writes no Evidence at all. Where a
test here needs an Evidence row it makes one with `grade_session`, which is
what ISSUE-0044 will do at the end of a Session.
"""

import sqlalchemy as sa
import pytest
from sqlalchemy import text

from conftest import grade_session

from interviewer.service.confidence.math import PRIOR
from interviewer.model.corpus import GradingMode
from interviewer.db import schema as S
from interviewer.service.graph.runner import SessionRunner
from interviewer.service.graph.sessions import SessionConfig

CANDIDATE = "cand_test"


def _cfg(deps, n_modules=1, seconds=1800):
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:n_modules]
    return SessionConfig(scope_module_ids=tuple(mods), duration_seconds=seconds)


def test_a_session_asks_a_question_and_one_answer_writes_a_transcript(deps, clean_db):
    """ISSUE-0042: the answer lands in the record, and nothing is graded.

    This used to assert one Evidence row per answer. It asserts the opposite
    now, because that is the trade the Interview Mode set makes: the plan is
    fixed up front, so nothing in the loop needs a freshly updated posterior,
    so nothing in the loop grades.
    """
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    assert first.kind == "question"
    assert first.payload["question"]
    assert first.payload["topic_visit_id"]

    out = r.submit(sid, "Because the dot products grow with d_k and softmax saturates.")
    assert out.kind == "question"
    # A turn carries the next question and nothing else.
    assert "last_visit" not in out.payload
    assert "score" not in out.payload and "band" not in out.payload

    with clean_db.connect() as c:
        assert c.execute(
            sa.select(sa.func.count()).select_from(S.evidence)).scalar() == 0
        kinds = c.execute(
            sa.select(S.message.c.kind).where(S.message.c.session_id == sid)
            .order_by(S.message.c.seq)
        ).scalars().all()
    assert kinds[:2] == ["question", "answer"]


def test_every_model_call_is_attributed_and_the_visit_row_precedes_its_own(
    deps, clean_db
):
    """SPEC-0005 rejects a call without an attribution, so the row must precede it.

    Rewritten by ISSUE-0041. The *first* model call is no longer the question
    writer's: the Session now plans before it asks anything, and the plan
    belongs to no Topic Visit — it is what decides that Visits there will be.
    It is attributed to `plan_<session_id>`, which is why the rule this test
    holds is stated as two clauses rather than one: every call carries an
    attribution, and every call attributed to a Topic Visit finds that Visit
    already open.
    """
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    calls = deps.ports.model.calls
    assert calls, "the planner and the question writer should have been called"
    assert all(c["topic_visit_id"] for c in calls)

    assert calls[0]["role"] == "session_planner"
    assert calls[0]["topic_visit_id"] == f"plan_{sid}"

    visit_calls = [c for c in calls if c["role"] != "session_planner"]
    assert visit_calls, "the question writer should have been called"
    for c in visit_calls:
        row = deps.visits.get(c["topic_visit_id"])
        assert row is not None and row["state"] == "open"


def test_the_exchange_is_written_to_the_transcript_as_it_happens(deps, clean_db):
    """ISSUE-0042 moved the record out of `topic_visit.exchange`.

    The blob belonged to one question and was written for one grader. The
    transcript is the Session's own record, in order, append-only, and it is
    what the end-of-Session grade will read.
    """
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    vid = first.payload["topic_visit_id"]
    r.submit(sid, "my answer")

    with clean_db.connect() as c:
        rows = c.execute(
            sa.select(S.message).where(S.message.c.topic_visit_id == vid)
            .order_by(S.message.c.seq)
        ).all()
    said = [dict(x._mapping) for x in rows]
    assert said[-1]["text"] == "my answer"
    assert said[-1]["kind"] == "answer"
    # Labelled from the plan, deterministically — nothing asked a model.
    assert said[-1]["topic_ids"] == [first.payload["topic_id"]]
    assert said[-1]["plan_item_id"]

    row = deps.visits.get(vid)
    assert row["answered_at"] is not None
    assert row["graded_at"] is None      # a grade arrives once, at the end


def test_writing_evidence_twice_for_one_visit_leaves_the_posterior_unchanged(deps):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    vid = first.payload["topic_visit_id"]
    topic_id = first.payload["topic_id"]
    r.submit(sid, "an answer")
    grade_session(deps, sid)

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


def test_a_session_ends_when_its_plan_is_exhausted(deps):
    """Scope exhaustion became plan exhaustion (ISSUE-0042).

    The Session no longer walks the scope looking for an unvisited Topic; it
    walks the plan, and it is over when the plan is.
    """
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    for _ in range(20):
        if out.kind == "session_ended":
            break
        out = r.submit(sid, "answer")
    assert out.kind == "session_ended"
    assert out.payload["reason"] == "plan_exhausted"
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
    # `graded` rather than `answered` since ISSUE-0044: the Visit completed,
    # and reaching the end of the Session graded the Session it belongs to. It
    # was not truncated, which is what this test is about.
    assert rows[0]["state"] == "graded"
    assert rows[0]["turn_count"] == 1
    # No score travels on the turn either way. The grade is a row in `evidence`
    # written at the end, never something a turn carries back (ISSUE-0042).
    assert "last_visit" not in out.payload


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


def test_a_topic_may_be_asked_about_twice_in_one_session(deps, clean_db):
    """ISSUE-0039 removed `uq_visit_session_topic`, and this is the difference.

    The store used to refuse a second question on a Topic. It no longer does,
    because a plan may deliberately spend two on one — how many questions a Topic
    is worth is the plan's decision, not the store's. What the store still
    refuses is two *observations*: `uq_evidence_session_topic` is where ADR-0004
    lives now, and `test_interview_mode_schema.py` proves it.
    """
    import sqlalchemy as sa

    from interviewer.db import schema as S

    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    topic = first.payload["topic_id"]
    r.submit(sid, "answer")

    # Resolve the open one — the Session still will not advance while a Visit is
    # unresolved, which is a different invariant and untouched by ISSUE-0039.
    with clean_db.begin() as c:
        c.execute(sa.update(S.topic_visit)
                  .where(S.topic_visit.c.session_id == sid)
                  .values(state="abandoned"))

    second = deps.visits.open(
        session_id=sid, candidate_id=CANDIDATE, topic_id=topic, visit_index=50
    )
    assert second is not None

    with clean_db.connect() as c:
        asked = c.execute(
            sa.select(sa.func.count())
            .select_from(S.topic_visit)
            .where(S.topic_visit.c.session_id == sid)
            .where(S.topic_visit.c.topic_id == topic)
        ).scalar()
    assert asked == 2


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
    grade_session(deps, sid)
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
