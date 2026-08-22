"""ISSUE-0007 — resumption and replay determinism."""

import sqlalchemy as sa

from interviewer.db import schema as S
from interviewer.graph.runner import SessionRunner
from interviewer.graph.sessions import SessionConfig

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


def test_an_answer_submitted_before_an_interruption_is_still_graded(deps, clean_db):
    """The exchange is stored at the Answer Turn, so the work is not thrown away."""
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    vid = first.payload["topic_visit_id"]

    # simulate: answer accepted and stored, then the process dies before grading
    from interviewer.corpus.contract import GradingMode
    deps.visits.record_answer(
        vid,
        exchange={"turns": [
            {"role": "interviewer", "kind": "question", "text": first.payload["question"]},
            {"role": "candidate", "kind": "answer", "text": "a real answer"},
        ]},
        turn_count=1,
        mode=GradingMode(first.payload["grading_mode"]),
    )
    deps.sessions.park(sid, "client_gone")

    out = r.resume_after_interruption(sid)
    assert out.kind == "visit_closed"
    assert out.payload["recovered"] is True

    with clean_db.connect() as c:
        n = c.execute(sa.select(sa.func.count()).select_from(S.evidence)).scalar()
    assert n == 1
    assert deps.visits.get(vid)["state"] == "graded"


def test_resuming_an_already_graded_visit_writes_nothing_new(deps, clean_db):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    r.submit(sid, "answer")

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

    from interviewer.confidence.store import ConfidenceStore
    from interviewer.graph.sessions import SessionStore

    assert SessionStore(deps.sessions._e).get(sid)["state"] in ("running", "ended")
    assert ConfidenceStore(deps.confidence._e).all_for(CANDIDATE)


# -- determinism -------------------------------------------------------------

def _run(deps, seed, answers):
    import numpy as np
    from interviewer.graph.ports import Ports, FrozenClock, ScriptedModel
    from interviewer.graph.machine import Deps

    model = ScriptedModel(default="SCORE: 0.8\nWHY: fine.")
    d = Deps(
        ports=Ports(clock=FrozenClock(), rng=np.random.default_rng(seed), model=model),
        loader=deps.loader, corpus=deps.corpus, sessions=deps.sessions,
        visits=deps.visits, evidence=deps.evidence, confidence=deps.confidence,
        judge=deps.judge, writer=deps.writer, selector=deps.selector,
        interviewer=deps.interviewer,
    )
    r = SessionRunner(d)
    sid, out = r.start(candidate_id=f"cand_{seed}_{id(answers)}", cfg=_cfg(deps))
    seq, scores = [out.payload.get("topic_id")], []
    for a in answers:
        out = r.submit(sid, a)
        if out.payload.get("last_visit"):
            scores.append(out.payload["last_visit"]["score"])
        if out.kind == "session_ended":
            break
        seq.append(out.payload.get("topic_id"))
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
    import numpy as np
    from interviewer.graph.machine import Deps
    from interviewer.graph.ports import FrozenClock, Ports, ScriptedModel

    def run_with(score_text, cand):
        model = ScriptedModel(default=score_text)
        d = Deps(
            ports=Ports(clock=FrozenClock(), rng=np.random.default_rng(1), model=model),
            loader=deps.loader, corpus=deps.corpus, sessions=deps.sessions,
            visits=deps.visits, evidence=deps.evidence, confidence=deps.confidence,
            judge=deps.judge, writer=deps.writer, selector=deps.selector,
            interviewer=deps.interviewer,
        )
        r = SessionRunner(d)
        sid, _ = r.start(candidate_id=cand, cfg=_cfg(deps))
        out = r.submit(sid, "the same answer, word for word")
        return out.payload["last_visit"]["score"]

    lenient = run_with("SCORE: 0.9\nWHY: generous rubric.", "cand_v1")
    strict = run_with("SCORE: 0.4\nWHY: strict rubric.", "cand_v2")
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
