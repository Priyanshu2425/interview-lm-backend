"""ISSUE-0044 — the Session is graded at the end.

Every test here runs a **real** Session and grades the transcript it actually
produced. That is not fastidiousness: the one property that matters most —
that a Topic the Session never reached scores nothing at all — is invisible in
a hand-built fixture, because a fixture is written by someone who reached every
Topic they thought to write down. It shows up only where a plan outran its
clock, so that is what these build.
"""

import sqlalchemy as sa

from conftest import grade_session, signed_in_client, SIGNED_IN_CANDIDATE

from interviewer.db import schema as S
from interviewer.service.graph.planner import PlanStore
from interviewer.service.graph.runner import SessionRunner
from interviewer.service.graph.sessions import SessionConfig
from interviewer.service.graph.transcript import Transcript

CANDIDATE = "cand_graded_at_the_end"


def _cfg(deps, n=1, seconds=1800):
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:n]
    return SessionConfig(scope_module_ids=tuple(mods), duration_seconds=seconds)


def _run_to_the_end(r, sid, out, answer="an answer worth grading", limit=30):
    for _ in range(limit):
        if out.kind == "session_ended":
            break
        out = r.submit(sid, answer)
    return out


def _reached(deps, sid) -> set[str]:
    """Every Topic that appears in any message. The transcript's own reading."""
    return {
        t for m in Transcript(deps.visits._e).of(sid)
        for t in (m["topic_ids"] or ())
    }


# --- one row per reached Topic ---------------------------------------------


def test_a_finished_session_writes_one_evidence_row_per_reached_topic(deps, clean_db):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    _run_to_the_end(r, sid, first)

    rows = deps.evidence.for_session(sid)
    graded = [row["topic_id"] for row in rows]
    assert sorted(graded) == sorted(_reached(deps, sid))
    assert len(graded) == len(set(graded))       # one each, not one per question


def test_every_graded_topic_moved_its_posterior_off_the_prior(deps):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    _run_to_the_end(r, sid, first)

    posteriors = deps.confidence.all_for(CANDIDATE)
    assert set(posteriors) == _reached(deps, sid)
    assert all(p.alpha != 1.0 or p.beta != 1.0 for p in posteriors.values())


# --- planned but never reached is not a zero -------------------------------


def _outran_its_clock(deps, candidate=CANDIDATE):
    """A Session with more plan than clock: one item asked, the rest unreached.

    The clock is advanced *after* the first question is in flight, so the
    Session ends at the boundary the way a real one does, with items still
    `planned` behind it.
    """
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=candidate, cfg=_cfg(deps, seconds=1800))
    deps.ports.clock.advance(3600)
    out = r.submit(sid, "the only answer this Session will get")
    assert out.kind == "session_ended"
    assert out.payload["reason"] == "duration"
    return sid


def test_a_topic_the_session_never_reached_gets_no_evidence_and_no_posterior(
    deps, clean_db
):
    """The property this slice exists to protect. Untested is not zero."""
    sid = _outran_its_clock(deps)

    plan = PlanStore(clean_db).get(sid)
    unreached = {t for i in plan.items if i.state == "unreached" for t in i.topic_ids}
    assert unreached, "this Session was supposed to run out of clock"

    graded = {row["topic_id"] for row in deps.evidence.for_session(sid)}
    assert graded == _reached(deps, sid)
    assert not (graded & unreached)
    # Not a low score, not a zero, not a row at all — and the posterior for an
    # unreached Topic is untouched, which is the Evidence Floor's whole argument.
    assert not (set(deps.confidence.all_for(CANDIDATE)) & unreached)
    with clean_db.connect() as c:
        for topic_id in unreached:
            assert c.execute(
                sa.select(sa.func.count()).select_from(S.evidence)
                .where(S.evidence.c.topic_id == topic_id)
            ).scalar() == 0


def test_unreached_is_a_state_and_not_the_absence_of_asked(deps, clean_db):
    sid = _outran_its_clock(deps)
    states = [i.state for i in PlanStore(clean_db).get(sid).items]
    assert states[0] == "asked"
    assert set(states[1:]) == {"unreached"}


# --- idempotence ------------------------------------------------------------


def test_grading_the_same_session_twice_writes_nothing_the_second_time(
    deps, clean_db
):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    _run_to_the_end(r, sid, first)

    before = [dict(row) for row in deps.evidence.for_session(sid)]
    assert before
    posterior_before = deps.confidence.all_for(CANDIDATE)

    assert grade_session(deps, sid) == []      # nothing new was written
    after = [dict(row) for row in deps.evidence.for_session(sid)]
    assert [row["evidence_id"] for row in after] == \
           [row["evidence_id"] for row in before]
    assert deps.confidence.all_for(CANDIDATE) == posterior_before


def test_the_unique_constraint_is_what_refuses_the_second_write(deps, clean_db):
    """ADR-0004 is the constraint, not the care taken around it."""
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    _run_to_the_end(r, sid, first)
    row = deps.evidence.for_session(sid)[0]

    import sqlalchemy.exc

    try:
        with clean_db.begin() as c:
            c.execute(sa.insert(S.evidence).values(
                evidence_id="ev_a_second_observation",
                candidate_id=row["candidate_id"],
                topic_id=row["topic_id"],
                session_id=sid,
                score=row["score"],
                grading_mode=row["grading_mode"],
                weight=row["weight"],
                alpha_delta=row["alpha_delta"],
                beta_delta=row["beta_delta"],
                grader_kind=row["grader_kind"],
                rubric_version=row["rubric_version"],
            ))
    except sqlalchemy.exc.IntegrityError as e:
        assert "uq_evidence_session_topic" in str(e)
    else:
        raise AssertionError("a second observation on one Topic was accepted")


# --- spanning questions -----------------------------------------------------


def _spanning_session(deps, clean_db, candidate=CANDIDATE):
    r = SessionRunner(deps)
    # Twelve Topics and fifteen minutes: five questions, so some must group.
    sid, first = r.start(candidate_id=candidate, cfg=_cfg(deps, n=2, seconds=900))
    _run_to_the_end(r, sid, first)
    plan = PlanStore(clean_db).get(sid)
    spanning = [i for i in plan.items if len(i.topic_ids) > 1]
    assert spanning, "a fifteen-minute Session over twelve Topics must group"
    return sid, spanning


def test_a_spanning_question_produces_one_row_per_topic_it_named(deps, clean_db):
    sid, spanning = _spanning_session(deps, clean_db)
    graded = {row["topic_id"] for row in deps.evidence.for_session(sid)}
    for item in spanning:
        assert set(item.topic_ids) <= graded


def test_one_answer_graded_three_times_is_three_observations_not_one(
    deps, clean_db
):
    """The unit moved to the Topic; the count per Topic did not."""
    sid, spanning = _spanning_session(deps, clean_db)
    item = max(spanning, key=lambda i: len(i.topic_ids))
    rows = [row for row in deps.evidence.for_session(sid)
            if row["topic_id"] in item.topic_ids]
    assert len(rows) == len(item.topic_ids)
    assert len({row["topic_id"] for row in rows}) == len(rows)


# --- blindness --------------------------------------------------------------


def test_the_per_topic_prompt_carries_no_probe_no_hint_and_no_other_title(
    deps, clean_db
):
    """Blindness is at risk from the spanning question, not the transcript."""
    sid, spanning = _spanning_session(deps, clean_db)

    said = Transcript(deps.visits._e).of(sid)
    follow_ups = [m["text"] for m in said if m["kind"] in ("probe", "hint")]
    judged = [c for c in deps.ports.model.calls if c["role"] == "judge"]
    assert judged

    prompts = "\n".join(c["user"] for c in judged)
    for text in follow_ups:
        assert text and text not in prompts

    # And no prompt names a Topic other than the one it is grading.
    by_topic = {
        row["topic_id"]: row["topic_title_snapshot"]
        for row in deps.evidence.for_session(sid)
    }
    for item in spanning:
        titles = {t: by_topic[t] for t in item.topic_ids if t in by_topic}
        for topic_id, title in titles.items():
            mine = [c for c in judged if title and title in c["user"]]
            others = [v for t, v in titles.items() if t != topic_id and v != title]
            for call in mine:
                assert not [o for o in others if o in call["user"]], (topic_id, o)


def test_the_judge_is_given_a_question_an_answer_and_a_grounding_and_nothing_else(
    deps, clean_db
):
    """Three sections, always the same three. A fourth is the leak."""
    sid, _ = _spanning_session(deps, clean_db)
    judged = [c for c in deps.ports.model.calls if c["role"] == "judge"]
    assert judged

    said = Transcript(deps.visits._e).of(sid)
    answers = {m["text"] for m in said if m["kind"] == "answer"}
    sections = ("QUESTION", "ANSWER", "AUTHORITATIVE ANSWER", "COURSE MATERIAL",
                "No source material.")
    for call in judged:
        assert call["user"].startswith("QUESTION\n")
        assert "\n\nANSWER\n" in call["user"]
        named = [line for line in call["user"].splitlines() if line in sections]
        assert named == ["QUESTION", "ANSWER"] or (
            named[:2] == ["QUESTION", "ANSWER"] and len(named) == 3
        )
        # The Candidate's words are there; nothing says how many turns it took
        # to get them, and no turn is numbered.
        assert any(a in call["user"] for a in answers)


# --- the three callers reach the same rows ----------------------------------


def test_ending_a_session_by_hand_grades_it(deps, clean_db):
    """`/end`'s service call, exercised where the runner cannot reach."""
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    r.submit(sid, "one answer, then the Candidate stops")
    deps.sessions.end(sid, "candidate_ended")

    assert not deps.evidence.for_session(sid)
    written = deps.grader.grade(sid)
    assert written
    assert {w.evidence_id for w in written} == \
           {row["evidence_id"] for row in deps.evidence.for_session(sid)}


def _same_world(deps, seed=7):
    """The same Session twice, differing only in how it was ended.

    Selection is stochastic, so two Sessions run back to back plan differently
    and would be incomparable. A fresh generator on the same seed makes the
    second one the first one again.
    """
    import dataclasses

    import numpy as np

    from interviewer.service.graph.ports import FrozenClock, Ports

    twin = dataclasses.replace(deps, ports=Ports(
        clock=FrozenClock(), rng=np.random.default_rng(seed), model=deps.ports.model,
    ))
    twin.grader = deps.grader
    return twin


def test_a_session_ended_by_the_clock_and_one_ended_by_hand_agree(deps, clean_db):
    """Both reach the same rows, because both call the same service."""
    by_clock = _same_world(deps)
    r = SessionRunner(by_clock)
    clock_sid, _ = r.start(candidate_id="cand_by_clock",
                           cfg=_cfg(deps, seconds=1800))
    by_clock.ports.clock.advance(3600)
    out = r.submit(clock_sid, "the only answer this Session will get")
    assert out.payload["reason"] == "duration"

    by_hand = _same_world(deps)
    r2 = SessionRunner(by_hand)
    hand_sid, _ = r2.start(candidate_id="cand_by_hand", cfg=_cfg(deps, seconds=1800))
    r2.submit(hand_sid, "the only answer this Session will get")
    by_hand.sessions.end(hand_sid, "candidate_ended")
    by_hand.grader.grade(hand_sid)

    clock_rows = [row["topic_id"] for row in deps.evidence.for_session(clock_sid)]
    hand_rows = [row["topic_id"] for row in deps.evidence.for_session(hand_sid)]
    assert clock_rows and clock_rows == hand_rows
    # And both plans say what was never asked, rather than leaving it `planned`.
    # The two are not identical: the Session ended by hand had already opened
    # its next question, and an item that was asked is not an item nobody
    # reached.
    for ended in (clock_sid, hand_sid):
        states = {i.state for i in PlanStore(clean_db).get(ended).items}
        assert "planned" not in states
        assert "unreached" in states


def test_a_session_killed_mid_flight_is_graded_once_when_it_is_resumed(
    deps, clean_db
):
    """Kill the process, resume, end — the grade still lands, and once."""
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps, seconds=1800))
    r.submit(sid, "an answer that landed before the lights went out")
    deps.sessions.park(sid, "client_gone")
    assert not deps.evidence.for_session(sid)

    out = r.resume_after_interruption(sid)
    assert out is not None
    _run_to_the_end(r, sid, out)

    rows = deps.evidence.for_session(sid)
    assert rows
    assert len({row["topic_id"] for row in rows}) == len(rows)
    assert deps.grader.grade(sid) == []


def test_a_session_whose_graph_finished_without_evidence_is_graded_on_resume(
    deps, clean_db
):
    """The one gap a node on the edge to END cannot close by itself."""
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    _run_to_the_end(r, sid, first)

    with clean_db.begin() as c:
        c.execute(sa.text(
            f"ALTER TABLE {S.CORE}.evidence DISABLE TRIGGER trg_evidence_append_only"
        ))
        c.execute(sa.delete(S.evidence).where(S.evidence.c.session_id == sid))
        c.execute(sa.text(
            f"ALTER TABLE {S.CORE}.evidence ENABLE TRIGGER trg_evidence_append_only"
        ))
    assert not deps.evidence.for_session(sid)

    assert SessionRunner(deps).resume_after_interruption(sid) is None
    assert deps.evidence.for_session(sid)


# --- what a row carries -----------------------------------------------------


def test_a_row_records_how_many_questions_the_observation_took(deps, clean_db):
    """Reporting only. It is never a Beta count."""
    sid, _ = _spanning_session(deps, clean_db)
    rows = deps.evidence.for_session(sid)
    assert all(row["question_count"] >= 1 for row in rows)
    assert all(float(row["alpha_delta"]) + float(row["beta_delta"]) <= 1.0
               for row in rows)


def test_a_row_keeps_both_of_the_judge_s_readings(deps, clean_db):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    _run_to_the_end(r, sid, first)
    for row in deps.evidence.for_session(sid):
        assert row["truth_score"] is not None
        assert row["exchange_snapshot"]["turns"]
        assert row["rubric_version"]


def test_the_endpoint_ends_and_grades_in_one_call(clean_db, loader):
    """`POST /v1/sessions/{id}/end`, all the way through."""
    with signed_in_client() as client:
        from interviewer.wiring import wiring

        mods = [m.module_id for m in wiring().deps.corpus.modules("aiml")][:1]
        started = client.post("/v1/sessions", json={
            "module_ids": mods, "duration_seconds": 1800,
        })
        assert started.status_code == 201
        sid = started.json()["session_id"]
        client.post(f"/v1/sessions/{sid}/turns", json={"answer": "an answer"})

        ended = client.post(f"/v1/sessions/{sid}/end")
        assert ended.status_code == 200, ended.text
        assert ended.json()["state"] == "ended"
        assert ended.json()["graded"] >= 1

        rows = wiring().deps.evidence.for_session(sid)
        assert rows
        assert all(row["candidate_id"] == SIGNED_IN_CANDIDATE for row in rows)
        # Called twice, the same rows come back and no new ones are written.
        again = client.post(f"/v1/sessions/{sid}/end")
        assert again.json()["graded"] == 0
        assert len(wiring().deps.evidence.for_session(sid)) == len(rows)
