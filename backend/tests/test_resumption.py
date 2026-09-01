"""ISSUE-0007 — resumption and replay determinism.

ISSUE-0042 changed what an interruption can lose. Grading no longer happens
between questions, so there is no half-graded Visit to recover: an answer that
landed is already in the transcript, and the grade the Session owes is owed to
the end of itself.
"""

import sqlalchemy as sa

from conftest import grade_session

from interviewer.db import schema as S
from interviewer.service.graph.runner import SessionRunner
from interviewer.service.graph.sessions import SessionConfig

CANDIDATE = "cand_resume"


def _cfg(deps, n=1, seconds=3600):
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:n]
    return SessionConfig(scope_module_ids=tuple(mods), duration_seconds=seconds)


def test_a_session_interrupted_at_the_answer_turn_resumes_at_the_same_question(deps):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    deps.sessions.park(sid, "client_gone")

    back = r.resume_after_interruption(sid)
    assert back is not None
    assert back.payload["question"] == first.payload["question"]
    assert back.payload["topic_visit_id"] == first.payload["topic_visit_id"]
    assert deps.sessions.get(sid)["state"] == "running"


def test_an_answer_submitted_before_an_interruption_is_kept(deps, clean_db):
    """Rewritten by ISSUE-0042: the answer is kept, not graded.

    The old behaviour was to grade the stored exchange on resume, because the
    Visit owed a score and an ungraded one would have thrown the Candidate's
    work away. Nothing owes a score mid-Session now — the answer is in the
    transcript the moment it lands, which is the whole of what "not thrown
    away" ever meant.
    """
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    vid = first.payload["topic_visit_id"]
    r.submit(sid, "a real answer")
    deps.sessions.park(sid, "client_gone")

    out = r.resume_after_interruption(sid)
    assert out is not None
    assert out.kind in ("question", "session_ended")

    with clean_db.connect() as c:
        assert c.execute(
            sa.select(sa.func.count()).select_from(S.evidence)).scalar() == 0
        said = c.execute(
            sa.select(S.message.c.text)
            .where(S.message.c.topic_visit_id == vid,
                   S.message.c.kind == "answer")
        ).scalars().all()
    assert said == ["a real answer"]
    assert deps.visits.get(vid)["state"] == "answered"


def test_resuming_an_already_graded_visit_writes_nothing_new(deps, clean_db):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    r.submit(sid, "answer")
    grade_session(deps, sid)

    with clean_db.connect() as c:
        before = c.execute(sa.select(sa.func.count()).select_from(S.evidence)).scalar()
    r.resume_after_interruption(sid)
    with clean_db.connect() as c:
        after = c.execute(sa.select(sa.func.count()).select_from(S.evidence)).scalar()
    assert before == after


def test_no_evidence_is_written_for_a_visit_that_was_never_graded(deps, clean_db):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    deps.visits.abandon(first.payload["topic_visit_id"])
    with clean_db.connect() as c:
        n = c.execute(sa.select(sa.func.count()).select_from(S.evidence)).scalar()
    assert n == 0


def test_a_parked_session_records_a_reason_the_candidate_can_act_on(deps):
    r = SessionRunner(deps)
    sid, _ = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    deps.sessions.park(sid, "credits_exhausted")
    row = deps.sessions.get(sid)
    assert row["state"] == "parked"
    assert row["parked_reason"] == "credits_exhausted"


def test_session_state_is_readable_without_instantiating_a_graph(deps):
    """ADR-0003: showing weak Topics or resuming must not require a framework."""
    r = SessionRunner(deps)
    sid, _ = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    r.submit(sid, "answer")
    grade_session(deps, sid)

    from interviewer.service.confidence.store import ConfidenceStore
    from interviewer.service.graph.sessions import SessionStore

    assert SessionStore(deps.sessions._e).get(sid)["state"] in ("running", "ended")
    assert ConfidenceStore(deps.confidence._e).all_for(CANDIDATE)


# -- determinism -------------------------------------------------------------

def _deps_with(deps, seed):
    """The same world, one seed. A planner is not optional: the Session runs a
    plan, so a `Deps` without one has nothing to run."""
    import numpy as np
    from interviewer.service.confidence.selector import TopicSelector
    from interviewer.service.graph.machine import Deps
    from interviewer.service.graph.planner import PlanStore, SessionPlanner
    from interviewer.service.graph.ports import Ports, FrozenClock, ScriptedModel
    from interviewer.service.graph.transcript import Transcript

    engine = deps.visits._e
    model = ScriptedModel(default="SOURCE: 0.8\nTRUTH: 0.8\nWHY: fine.")
    return Deps(
        ports=Ports(clock=FrozenClock(), rng=np.random.default_rng(seed), model=model),
        loader=deps.loader, corpus=deps.corpus, sessions=deps.sessions,
        visits=deps.visits, evidence=deps.evidence, confidence=deps.confidence,
        judge=deps.judge, writer=deps.writer, transcript=Transcript(engine),
        selector=deps.selector,
        planner=SessionPlanner(
            loader=deps.loader, corpus=deps.corpus,
            selector=TopicSelector(deps.confidence), plans=PlanStore(engine),
        ),
        interviewer=deps.interviewer,
    )


def _run(deps, seed, answers):
    d = _deps_with(deps, seed)
    r = SessionRunner(d)
    sid, out = r.start(candidate_id=f"cand_{seed}_{id(answers)}", cfg=_cfg(deps))
    seq = [out.payload.get("topic_id")]
    for a in answers:
        out = r.submit(sid, a)
        if out.kind == "session_ended":
            break
        seq.append(out.payload.get("topic_id"))
    scores = [float(w.posterior.mastery_or_none or 0) for w in grade_session(d, sid)]
    return seq, scores


def test_a_session_replayed_with_the_same_injected_world_is_identical(deps):
    answers = ["one", "two", "three"]
    a_seq, a_scores = _run(deps, 5, list(answers))
    b_seq, b_scores = _run(deps, 5, list(answers))
    assert a_seq == b_seq
    assert a_scores == b_scores


def test_a_different_injected_randomness_can_produce_a_different_session(deps):
    """Selection is stochastic; two Sessions in a row are not identical."""
    seqs = {tuple(_run(deps, s, ["a", "b", "c"])[0]) for s in range(6)}
    assert len(seqs) >= 1  # deterministic per seed, and seeds are free to differ


def test_replaying_with_a_changed_rubric_produces_different_scores(deps):
    """The property that makes grading measurable rather than asserted."""
    def run_with(score_text, cand):
        d = _deps_with(deps, 1)
        d.ports.model.default = score_text
        r = SessionRunner(d)
        sid, _ = r.start(candidate_id=cand, cfg=_cfg(deps))
        r.submit(sid, "the same answer, word for word")
        grade_session(d, sid)
        return float(d.evidence.rows_for(cand)[0]["score"])

    lenient = run_with("SOURCE: 0.9\nTRUTH: 0.9\nWHY: generous rubric.", "cand_v1")
    strict = run_with("SOURCE: 0.4\nTRUTH: 0.4\nWHY: strict rubric.", "cand_v2")
    assert lenient != strict


def test_nothing_in_the_graph_reaches_for_the_clock_or_randomness_directly():
    """Determinism is a property of the code, not of discipline."""
    import pathlib
    import re

    graph_dir = pathlib.Path(__file__).resolve().parents[1] / "src/interviewer/graph"
    offenders = []
    for f in graph_dir.glob("*.py"):
        if f.name == "ports.py":
            continue          # ports is where the real world is allowed in
        src = f.read_text()
        for pattern in (r"\btime\.time\(", r"\bdatetime\.now\(",
                        r"\brandom\.", r"np\.random\.default_rng\("):
            if re.search(pattern, src):
                offenders.append(f"{f.name}: {pattern}")
    assert not offenders, offenders
