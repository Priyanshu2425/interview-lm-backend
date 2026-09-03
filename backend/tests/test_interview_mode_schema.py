"""ISSUE-0039 — the plan, the transcript, and where ADR-0004 moved to.

The Session stops being a sequence of independently graded Topic Visits and
becomes a plan executed against a transcript. These tests are about the *store*:
what it refuses. Whether the loop uses any of it is ISSUE-0041 onward.
"""

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from interviewer.db import schema as S
from interviewer.db.schema import CORE


def _ids(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture()
def a_session(clean_db):
    """A Candidate and a Session, which everything in this set hangs off."""
    cand, sess = _ids("cand"), _ids("sess")
    with clean_db.begin() as c:
        c.execute(sa.insert(S.candidate).values(candidate_id=cand))
        c.execute(sa.insert(S.session).values(
            session_id=sess, candidate_id=cand, mode="managed",
            payment_route="credits", scope_module_ids=["mod-1"],
            duration_seconds=1800, rubric_version="v1",
        ))
    return clean_db, cand, sess


# --- the tree exists ------------------------------------------------------

def test_create_core_produces_every_new_table(clean_db):
    got = {
        r[0] for r in clean_db.connect().execute(sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :s"
        ), {"s": CORE})
    }
    assert {"session_plan", "plan_item", "message"} <= got


def test_create_core_produces_every_trigger(clean_db):
    got = {
        r[0] for r in clean_db.connect().execute(sa.text(
            "SELECT t.tgname FROM pg_trigger t "
            "JOIN pg_class cl ON cl.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = cl.relnamespace "
            "WHERE n.nspname = :s AND NOT t.tgisinternal"
        ), {"s": CORE})
    }
    assert {
        "trg_session_immutable", "trg_evidence_append_only",
        "trg_plan_item_fixed", "trg_message_append_only",
    } <= got


# --- the plan is fixed ----------------------------------------------------

def _a_plan_item(engine, session_id, order=0, topics=("t-1",)):
    item = _ids("pi")
    with engine.begin() as c:
        c.execute(sa.insert(S.plan_item).values(
            plan_item_id=item, session_id=session_id, item_order=order,
            topic_ids=list(topics), focus="the derivative",
        ))
    return item


def test_a_plan_items_topics_cannot_be_changed(a_session):
    engine, _, sess = a_session
    item = _a_plan_item(engine, sess)
    with pytest.raises(DBAPIError, match="fixed once planned"):
        with engine.begin() as c:
            c.execute(sa.update(S.plan_item)
                      .where(S.plan_item.c.plan_item_id == item)
                      .values(topic_ids=["t-2"]))


def test_a_plan_items_order_and_focus_cannot_be_changed(a_session):
    engine, _, sess = a_session
    item = _a_plan_item(engine, sess)
    for field, value in (("item_order", 7), ("focus", "something else")):
        with pytest.raises(DBAPIError, match="fixed once planned"):
            with engine.begin() as c:
                c.execute(sa.update(S.plan_item)
                          .where(S.plan_item.c.plan_item_id == item)
                          .values(**{field: value}))


def test_a_plan_item_may_still_record_that_it_was_reached(a_session):
    """Fixedness is about the plan, not about what happened to it."""
    engine, _, sess = a_session
    item = _a_plan_item(engine, sess)
    with engine.begin() as c:
        c.execute(sa.update(S.plan_item)
                  .where(S.plan_item.c.plan_item_id == item)
                  .values(state="unreached"))
    with engine.connect() as c:
        assert c.execute(sa.select(S.plan_item.c.state)
                         .where(S.plan_item.c.plan_item_id == item)).scalar() == "unreached"


def test_a_question_may_span_three_topics_and_no_more(a_session):
    engine, _, sess = a_session
    _a_plan_item(engine, sess, order=0, topics=("t-1", "t-2", "t-3"))
    with pytest.raises(IntegrityError):
        _a_plan_item(engine, sess, order=1, topics=("t-1", "t-2", "t-3", "t-4"))


def test_two_plan_items_cannot_claim_one_position(a_session):
    engine, _, sess = a_session
    _a_plan_item(engine, sess, order=0)
    with pytest.raises(IntegrityError):
        _a_plan_item(engine, sess, order=0)


# --- the transcript is append-only ---------------------------------------

def _a_message(engine, session_id, seq=0):
    mid = _ids("msg")
    with engine.begin() as c:
        c.execute(sa.insert(S.message).values(
            message_id=mid, session_id=session_id, seq=seq,
            role="interviewer", kind="question", text="What is a derivative?",
        ))
    return mid


def test_a_message_cannot_be_edited_after_the_fact(a_session):
    engine, _, sess = a_session
    mid = _a_message(engine, sess)
    with pytest.raises(DBAPIError, match="append-only"):
        with engine.begin() as c:
            c.execute(sa.update(S.message)
                      .where(S.message.c.message_id == mid)
                      .values(text="something the candidate never said"))


def test_a_message_cannot_be_deleted(a_session):
    engine, _, sess = a_session
    mid = _a_message(engine, sess)
    with pytest.raises(DBAPIError, match="append-only"):
        with engine.begin() as c:
            c.execute(sa.delete(S.message).where(S.message.c.message_id == mid))


def test_the_transcript_has_one_row_per_position(a_session):
    engine, _, sess = a_session
    _a_message(engine, sess, seq=0)
    with pytest.raises(IntegrityError):
        _a_message(engine, sess, seq=0)


# --- ADR-0004, restated ---------------------------------------------------

def _an_evidence(engine, cand, sess, topic_id, visit_id=None):
    ev = _ids("ev")
    with engine.begin() as c:
        c.execute(sa.insert(S.evidence).values(
            evidence_id=ev, topic_visit_id=visit_id, candidate_id=cand,
            topic_id=topic_id, session_id=sess, score=0.5,
            grading_mode="model_judgment", weight=0.5,
            alpha_delta=0.25, beta_delta=0.25,
            grader_kind="server_judge", rubric_version="v2",
        ))
    return ev


def test_one_beta_observation_per_topic_per_session(a_session):
    """The constraint *is* ADR-0004 — same guarantee, new key."""
    engine, cand, sess = a_session
    _an_evidence(engine, cand, sess, "topic-a")
    with pytest.raises(IntegrityError):
        _an_evidence(engine, cand, sess, "topic-a")


def test_the_same_topic_in_a_different_session_is_a_second_observation(clean_db):
    cand = _ids("cand")
    with clean_db.begin() as c:
        c.execute(sa.insert(S.candidate).values(candidate_id=cand))
    for _ in range(2):
        sess = _ids("sess")
        with clean_db.begin() as c:
            c.execute(sa.insert(S.session).values(
                session_id=sess, candidate_id=cand, mode="managed",
                payment_route="credits", scope_module_ids=["mod-1"],
                duration_seconds=1800, rubric_version="v1",
            ))
        _an_evidence(clean_db, cand, sess, "topic-a")


def test_evidence_no_longer_descends_from_exactly_one_question(a_session):
    """Nullable and non-unique: grading happens against a transcript now."""
    engine, cand, sess = a_session
    _an_evidence(engine, cand, sess, "topic-a", visit_id=None)
    _an_evidence(engine, cand, sess, "topic-b", visit_id=None)


def test_evidence_is_still_append_only(a_session):
    engine, cand, sess = a_session
    ev = _an_evidence(engine, cand, sess, "topic-a")
    with pytest.raises(DBAPIError, match="append-only"):
        with engine.begin() as c:
            c.execute(sa.update(S.evidence)
                      .where(S.evidence.c.evidence_id == ev).values(score=1.0))


def test_the_two_dimensions_have_somewhere_to_land(a_session):
    """ISSUE-0043 writes these; ISSUE-0039 is why the columns exist."""
    engine, cand, sess = a_session
    ev = _ids("ev")
    with engine.begin() as c:
        c.execute(sa.insert(S.evidence).values(
            evidence_id=ev, candidate_id=cand, topic_id="topic-a",
            session_id=sess, score=0.6, source_score=0.4, truth_score=0.8,
            question_count=3, grading_mode="text_grounded", weight=0.7,
            alpha_delta=0.42, beta_delta=0.28,
            grader_kind="server_judge", rubric_version="v2",
        ))
    with engine.connect() as c:
        row = c.execute(sa.select(
            S.evidence.c.source_score, S.evidence.c.truth_score,
            S.evidence.c.question_count,
        ).where(S.evidence.c.evidence_id == ev)).one()
    assert (float(row[0]), float(row[1]), row[2]) == (0.4, 0.8, 3)


def test_a_sub_score_outside_the_unit_interval_is_refused(a_session):
    engine, cand, sess = a_session
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(sa.insert(S.evidence).values(
                evidence_id=_ids("ev"), candidate_id=cand, topic_id="topic-a",
                session_id=sess, score=0.6, truth_score=1.5,
                grading_mode="model_judgment", weight=0.5,
                alpha_delta=0.25, beta_delta=0.25,
                grader_kind="server_judge", rubric_version="v2",
            ))


# --- what the break exists to allow --------------------------------------

def test_a_plan_may_spend_two_questions_on_one_topic(a_session):
    """`uq_visit_session_topic` is gone, and this is why."""
    engine, cand, sess = a_session
    for i in range(2):
        with engine.begin() as c:
            c.execute(sa.insert(S.topic_visit).values(
                topic_visit_id=_ids("tv"), session_id=sess, candidate_id=cand,
                topic_id="topic-a", visit_index=i, state="abandoned",
                topic_ids=["topic-a"],
            ))


# --- the two engines agree ------------------------------------------------

TRIGGERS = (
    ("session", "trg_session_immutable"),
    ("evidence", "trg_evidence_append_only"),
    ("plan_item", "trg_plan_item_fixed"),
    ("message", "trg_message_append_only"),
)


async def test_the_async_engine_applies_the_same_triggers_as_the_sync_one(clean_db):
    """It applied none of them until ISSUE-0039.

    A database built through the async path had every table and not one of the
    invariants — Evidence quietly mutable in the suite meant to prove it was not.
    Dropped here and rebuilt, because presence alone would pass whether the async
    path put them there or `create_core` had.
    """
    from interviewer.db.engine_async import create_async_tables

    with clean_db.begin() as c:
        for table, trigger in TRIGGERS:
            c.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger} ON {CORE}.{table}"))
        remaining = c.execute(sa.text(
            "SELECT count(*) FROM pg_trigger t "
            "JOIN pg_class cl ON cl.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = cl.relnamespace "
            "WHERE n.nspname = :s AND NOT t.tgisinternal"
        ), {"s": CORE}).scalar()
    assert remaining == 0, "the drop is the premise of this test"

    await create_async_tables()

    with clean_db.begin() as c:
        got = {
            r[0] for r in c.execute(sa.text(
                "SELECT t.tgname FROM pg_trigger t "
                "JOIN pg_class cl ON cl.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = cl.relnamespace "
                "WHERE n.nspname = :s AND NOT t.tgisinternal"
            ), {"s": CORE})
        }
    assert got == {t for _, t in TRIGGERS}


# -- ISSUE-0049: how a turn arrived -----------------------------------------

def test_a_turn_is_written_rather_than_spoken_unless_it_says_otherwise(a_session):
    """Every row that existed before voice was typed, so `false` is the fact.

    It is a default in the sense that nobody has to write it, and not in the
    sense of standing in for something unknown.
    """
    engine, _, sess = a_session
    mid = _a_message(engine, sess)
    with engine.connect() as c:
        assert c.execute(
            sa.select(S.message.c.spoken)
            .where(S.message.c.message_id == mid)
        ).scalar() is False


def test_a_spoken_turn_says_so(a_session):
    engine, _, sess = a_session
    mid = _ids("msg")
    with engine.begin() as c:
        c.execute(sa.insert(S.message).values(
            message_id=mid, session_id=sess, seq=0,
            role="candidate", kind="answer", text="You scale by root d k.",
            spoken=True,
        ))
    with engine.connect() as c:
        assert c.execute(
            sa.select(S.message.c.spoken)
            .where(S.message.c.message_id == mid)
        ).scalar() is True


def test_how_a_turn_arrived_cannot_be_corrected_afterwards(a_session):
    """The append-only trigger covers this column like every other one.

    Worth its own test rather than a comment: ISSUE-0049 claims a spoken turn
    is recorded at insert and never corrected, and the only thing that makes
    that a fact rather than a convention is the trigger refusing.
    """
    engine, _, sess = a_session
    mid = _a_message(engine, sess)
    with pytest.raises(DBAPIError, match="append-only"):
        with engine.begin() as c:
            c.execute(sa.update(S.message)
                      .where(S.message.c.message_id == mid)
                      .values(spoken=True))


# -- ISSUE-0050: when the deadline starts running ---------------------------

def test_a_session_has_no_begin_time_until_it_is_begun(a_session):
    """`started_at` is when the row was written; `clock_started_at` is when the
    Candidate said they were ready. A Session created and walked away from has
    the first and not the second, and its deadline never runs."""
    engine, _, sess = a_session
    with engine.connect() as c:
        row = c.execute(
            sa.select(S.session.c.started_at, S.session.c.clock_started_at)
            .where(S.session.c.session_id == sess)
        ).first()
    assert row.started_at is not None
    assert row.clock_started_at is None
