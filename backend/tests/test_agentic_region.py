"""ISSUE-0006 — probe, hint, close.

A Visit may contain many Answer Turns and yields exactly one score. These assert
that, and the explicit handling we refuse to leave to the model.
"""

import sqlalchemy as sa

from interviewer.db import schema as S
from interviewer.graph.runner import SessionRunner
from interviewer.graph.sessions import SessionConfig
from interviewer.judge.interviewer import Interviewer
from interviewer.graph.ports import ScriptedModel

CANDIDATE = "cand_region"


def _cfg(deps, n=1, seconds=3600):
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:n]
    return SessionConfig(scope_module_ids=tuple(mods), duration_seconds=seconds)


def _script(deps, moves: list[str]):
    deps.ports.model.replies["interviewer"] = moves


def test_a_visit_with_four_answer_turns_produces_exactly_one_evidence_row(
    deps, clean_db
):
    _script(deps, [
        "ACTION: probe\nTEXT: Why does that follow?",
        "ACTION: probe\nTEXT: And what happens to the gradient?",
        "ACTION: hint\nTEXT: Think about the softmax tails.",
        "ACTION: close",
    ])
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    vid = out.payload["topic_visit_id"]

    for answer in ("first", "second", "third", "fourth"):
        out = r.submit(sid, answer)

    with clean_db.connect() as c:
        n = c.execute(
            sa.select(sa.func.count()).select_from(S.evidence)
            .where(S.evidence.c.topic_visit_id == vid)
        ).scalar()
    assert n == 1

    row = deps.visits.get(vid)
    assert row["turn_count"] == 4
    assert row["state"] == "graded"


def test_follow_ups_and_hints_are_all_recorded_in_the_stored_exchange(deps):
    _script(deps, [
        "ACTION: probe\nTEXT: Say more about the scaling.",
        "ACTION: hint\nTEXT: Consider the magnitude of the dot products.",
        "ACTION: close",
    ])
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    vid = out.payload["topic_visit_id"]
    for a in ("a1", "a2", "a3"):
        out = r.submit(sid, a)

    turns = deps.visits.get(vid)["exchange"]["turns"]
    kinds = [t.get("kind") for t in turns]
    assert "probe" in kinds and "hint" in kinds
    assert [t["text"] for t in turns if t["role"] == "candidate"] == ["a1", "a2", "a3"]


def test_a_vague_answer_draws_a_follow_up_rather_than_being_marked_down(deps):
    _script(deps, ["ACTION: probe\nTEXT: That is the wrong reason — try again.",
                   "ACTION: close"])
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    nxt = r.submit(sid, "it normalises the weights")
    assert nxt.kind == "probe"
    assert "wrong reason" in nxt.payload["question"]


def test_asking_for_a_hint_gets_a_hint_whatever_the_model_chose(deps):
    """A Candidate who asks for help gets help. Not left to the model."""
    _script(deps, ["ACTION: probe\nTEXT: What happens next?", "ACTION: close"])
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    nxt = r.submit(sid, "I'm stuck, can I get a hint?")
    assert nxt.kind == "hint"


def test_a_candidate_who_says_they_do_not_know_is_taken_at_their_word(deps):
    """One blank Topic must not consume the Session."""
    _script(deps, ["ACTION: probe\nTEXT: should never be reached"])
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    nxt = r.submit(sid, "I don't know this one")
    # closed and graded, then moved on to the next Topic
    assert nxt.kind in ("question", "session_ended")
    assert nxt.payload["last_visit"]["kind"] == "visit_closed"
    assert not [c for c in deps.ports.model.calls if c["role"] == "interviewer"
                and "never be reached" in c.get("user", "")]


def test_a_visit_that_hits_the_turn_bound_closes_and_grades(deps):
    """A single evasive exchange cannot run forever."""
    _script(deps, ["ACTION: probe\nTEXT: go on"] * 20)
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    vid = out.payload["topic_visit_id"]

    for i in range(10):
        out = r.submit(sid, f"evasive {i}")
        if out.payload.get("last_visit"):
            break

    row = deps.visits.get(vid)
    assert row["state"] == "graded"
    assert row["turn_count"] <= deps.interviewer.max_turns


def test_the_candidate_is_asked_one_thing_at_a_time(deps):
    _script(deps, ["ACTION: probe\nTEXT: One question only.", "ACTION: close"])
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    nxt = r.submit(sid, "answer")
    assert isinstance(nxt.payload["question"], str)
    assert nxt.payload["question"].count("?") <= 1


def test_the_judge_still_sees_only_the_answers_after_a_long_exchange(deps):
    """Hints and probes shaped the answer; they are not evidence about it."""
    _script(deps, [
        "ACTION: hint\nTEXT: SECRETHINT think about saturation",
        "ACTION: close",
    ])
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    r.submit(sid, "unsure")
    r.submit(sid, "now I see, gradients vanish")

    judge_call = next(c for c in deps.ports.model.calls if c["role"] == "judge")
    assert "SECRETHINT" not in judge_call["user"]
    assert "now I see, gradients vanish" in judge_call["user"]


def test_a_model_that_returns_nothing_useful_closes_rather_than_looping():
    m = ScriptedModel(default="I am not sure what to do")
    move = Interviewer().next_move(
        question="q", exchange=[{"role": "candidate", "text": "a"}],
        dossier=_dossier(), turn_count=1, topic_visit_id="v", model=m,
    )
    assert move.action == "close"


def _dossier():
    from interviewer.corpus.contract import GradingMode
    from interviewer.corpus.loader import Dossier

    return Dossier(
        topic_id="t", topic_title="T", module_id="m", module_title="M",
        module_order=1, topic_order=1, content=(), ground_truth_pairs=(),
        syllabus=(), grading_mode_ceiling=GradingMode.MODEL_JUDGMENT,
    )
