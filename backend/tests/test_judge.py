"""ISSUE-0003 — the Judge contract, tested on what the Judge received."""

import pytest

from interviewer.model.corpus import GradingMode
from interviewer.service.graph.ports import ScriptedModel
from interviewer.service.graph.runner import SessionRunner
from interviewer.service.graph.sessions import SessionConfig
from interviewer.service.judge.judge import Judge

CANDIDATE = "cand_judge"


def _cfg(deps, track="aiml", n=1, seconds=1800):
    mods = [m.module_id for m in deps.corpus.modules(track)][:n]
    return SessionConfig(scope_module_ids=tuple(mods), duration_seconds=seconds)


def _judge_calls(deps):
    return [c for c in deps.ports.model.calls if c["role"] == "judge"]


def test_the_judge_is_never_given_the_conversation(deps):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    r.submit(sid, "my careful answer about broadcasting")

    call = _judge_calls(deps)[0]
    assert "my careful answer about broadcasting" in call["user"]
    # what it must NOT contain: any marker of the exchange around the answer
    for marker in ("PROBING", "HINT", "interviewer", "follow-up", "turn "):
        assert marker.lower() not in call["user"].lower()


def test_a_ground_truth_call_receives_the_answer_key_for_that_assignment_only(
    deps, corpus
):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    assert first.payload["grading_mode"] == "ground_truth"
    r.submit(sid, "answer")

    call = _judge_calls(deps)[0]
    assert "AUTHORITATIVE ANSWER" in call["user"]

    topic = corpus.topic(first.payload["topic_id"])
    this_key = topic.ground_truth_pairs[0][1]
    assert (this_key.text or "")[:200] in call["user"]

    # no other Topic's Answer Key is anywhere near it
    others = [
        gt.text for t in corpus.topics if t.id != topic.id
        for _, gt in t.ground_truth_pairs
    ]
    for other in others[:15]:
        assert (other or "")[:200] not in call["user"]


def test_a_text_grounded_call_receives_material_and_no_answer_key(deps, corpus):
    """The GenAI Module carries no Answer Keys — a real examination at 0.7."""
    genai = next(m for m in deps.corpus.modules("aiml")
                 if m.title.startswith("Basics of GenAI"))
    cfg = SessionConfig(scope_module_ids=(genai.module_id,), duration_seconds=1800)
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=cfg)
    assert first.payload["grading_mode"] == "text_grounded"
    r.submit(sid, "answer")

    call = _judge_calls(deps)[0]
    assert "COURSE MATERIAL" in call["user"]
    assert "AUTHORITATIVE ANSWER" not in call["user"]


def test_a_model_judgment_call_receives_no_grounding():
    """The DSA Track's shape: no text behind the question."""
    from interviewer.model.corpus import Leaf, LeafKind, Topic
    from interviewer.service.corpus.loader import Dossier

    d = Dossier(
        topic_id="t", topic_title="Binary Search", module_id="m",
        module_title="Sorting", module_order=2, topic_order=1,
        content=(), ground_truth_pairs=(), syllabus=("Binary Search",),
        grading_mode_ceiling=GradingMode.MODEL_JUDGMENT,
    )
    model = ScriptedModel(default="TRUTH: 0.5\nWHY: ok")
    Judge().grade(
        question="q", exchange=[{"role": "candidate", "text": "a"}],
        dossier=d, mode=GradingMode.MODEL_JUDGMENT,
        topic_visit_id="v1", model=model,
    )
    call = model.calls[0]
    assert "No source material" in call["user"]
    assert "AUTHORITATIVE ANSWER" not in call["user"]
    assert "COURSE MATERIAL" not in call["user"]


def test_the_same_answer_scored_twice_gives_the_same_score(deps):
    from interviewer.service.corpus.loader import Dossier

    d = Dossier(
        topic_id="t", topic_title="T", module_id="m", module_title="M",
        module_order=1, topic_order=1, content=(), ground_truth_pairs=(),
        syllabus=(), grading_mode_ceiling=GradingMode.MODEL_JUDGMENT,
    )
    j = Judge()
    a = j.grade(question="q", exchange=[{"role": "candidate", "text": "x"}],
                dossier=d, mode=GradingMode.MODEL_JUDGMENT, topic_visit_id="v",
                model=ScriptedModel(default="TRUTH: 0.62\nWHY: r"))
    b = j.grade(question="q", exchange=[{"role": "candidate", "text": "x"}],
                dossier=d, mode=GradingMode.MODEL_JUDGMENT, topic_visit_id="v",
                model=ScriptedModel(default="TRUTH: 0.62\nWHY: r"))
    assert a.score == b.score == 0.62


# -- two dimensions (ISSUE-0043) ---------------------------------------------

def test_a_sub_score_outside_the_unit_interval_is_rejected_not_clamped():
    with pytest.raises(ValueError, match="outside 0..1"):
        Judge._parse("SOURCE: 0.5\nTRUTH: 1.7\nWHY: nope")
    with pytest.raises(ValueError, match="outside 0..1"):
        Judge._parse("SOURCE: 1.7\nTRUTH: 0.5\nWHY: nope")


def test_a_missing_truth_line_raises_rather_than_defaulting():
    """A grade with no TRUTH is a grader that did not answer the question, and
    a default would write a measurement nobody made into a permanent record."""
    with pytest.raises(ValueError, match="TRUTH"):
        Judge._parse("SOURCE: 0.9\nWHY: it explained the material")
    with pytest.raises(ValueError, match="TRUTH"):
        Judge._parse("WHY: nothing numeric here at all", grounded=False)


def test_a_grounded_grade_with_no_source_line_raises_too():
    """Falling back to TRUTH alone would quietly turn a grounded reading into
    an ungrounded one, and the row would not say so."""
    with pytest.raises(ValueError, match="SOURCE"):
        Judge._parse("TRUTH: 0.8\nWHY: right, but from somewhere else")


def test_a_grounded_verdict_combines_the_two_readings_in_equal_halves():
    v = Judge._parse("SOURCE: 0.4\nTRUTH: 0.8\nWHY: r")
    assert v.source_score == 0.4
    assert v.truth_score == 0.8
    assert v.score == pytest.approx(0.6)


def test_an_ungrounded_verdict_has_no_source_and_scores_as_truth_alone():
    """`MODEL_JUDGMENT` has no material to have explained. A null, not a zero:
    the answer did not fail to explain the source, it was never asked to."""
    v = Judge._parse("TRUTH: 0.8\nWHY: r", grounded=False)
    assert v.source_score is None
    assert v.score == v.truth_score == 0.8


def test_the_ungrounded_rubric_never_asks_for_a_source_reading():
    from interviewer.service.corpus.loader import Dossier

    d = Dossier(
        topic_id="t", topic_title="Binary Search", module_id="m",
        module_title="Sorting", module_order=2, topic_order=1,
        content=(), ground_truth_pairs=(), syllabus=("Binary Search",),
        grading_mode_ceiling=GradingMode.MODEL_JUDGMENT,
    )
    model = ScriptedModel(default="TRUTH: 0.5\nWHY: ok")
    Judge().grade(
        question="q", exchange=[{"role": "candidate", "text": "a"}],
        dossier=d, mode=GradingMode.MODEL_JUDGMENT,
        topic_visit_id="v1", model=model,
    )
    assert "SOURCE" not in model.calls[0]["system"]
    assert "TRUTH" in model.calls[0]["system"]


def test_both_sub_scores_reach_the_evidence_row(deps):
    r = SessionRunner(deps)
    sid, _ = r.start(candidate_id="cand_two_dimensions", cfg=_cfg(deps))
    deps.ports.model.replies["judge"] = ["SOURCE: 0.4\nTRUTH: 0.8\nWHY: half of it."]
    r.submit(sid, "an answer that owes little to the material")
    row = deps.evidence.rows_for("cand_two_dimensions")[0]
    assert float(row["source_score"]) == 0.4
    assert float(row["truth_score"]) == 0.8
    # `score` is the combination the posterior consumed — an input to the math,
    # never a third reading standing over the two.
    assert float(row["score"]) == pytest.approx(0.6)


def test_an_ungrounded_row_records_no_source_score(deps):
    """Graded on the model's own knowledge, the column stays null rather than
    zero — and `score` is the truth reading unchanged."""
    cand = deps.sessions.ensure_candidate("cand_ungrounded")
    sid = deps.sessions.create(cand, _cfg(deps))
    topic_id = deps.corpus.topic_ids_for(list(_cfg(deps).scope_module_ids))[0]
    visit = deps.visits.open(
        session_id=sid, candidate_id=cand, topic_id=topic_id, visit_index=0,
    )

    verdict = Judge._parse("TRUTH: 0.75\nWHY: sound.", grounded=False)
    deps.evidence.write(
        topic_visit_id=visit, candidate_id=cand, topic_id=topic_id,
        session_id=sid, score=verdict.score, source_score=verdict.source_score,
        truth_score=verdict.truth_score, mode=GradingMode.MODEL_JUDGMENT,
        grader_kind="server_judge", provider="deepseek",
        rubric_version=verdict.rubric_version, rationale=verdict.rationale,
    )
    row = deps.evidence.rows_for(cand)[0]
    assert row["source_score"] is None
    assert float(row["truth_score"]) == 0.75
    assert float(row["score"]) == 0.75


def test_every_evidence_row_carries_provenance_and_rubric_version(deps):
    r = SessionRunner(deps)
    sid, _ = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    r.submit(sid, "answer")
    row = deps.evidence.rows_for(CANDIDATE)[0]
    assert row["grader_kind"] == "server_judge"
    assert row["provider"] == "deepseek"
    assert row["rubric_version"] == "v2"
    assert row["rationale"]


def test_the_grading_mode_recorded_matches_the_grounding_used(deps):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    r.submit(sid, "answer")
    row = deps.evidence.rows_for(CANDIDATE)[0]
    assert row["grading_mode"] == first.payload["grading_mode"]
    assert float(row["weight"]) == GradingMode(row["grading_mode"]).weight


def test_hints_are_expressed_in_the_score_never_in_the_weight(deps):
    """An answer reached after help is a real answer worth roughly half."""
    r = SessionRunner(deps)
    sid, _ = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    deps.ports.model.replies["judge"] = [
        "SOURCE: 0.5\nTRUTH: 0.5\nWHY: reached after a hint."
    ]
    r.submit(sid, "eventually correct")
    row = deps.evidence.rows_for(CANDIDATE)[0]
    assert float(row["score"]) == 0.5
    assert float(row["weight"]) == 1.0     # the mode's weight, undiminished


def test_the_dsa_track_is_examinable_today(deps):
    """31 of its Classes are video with no text; it must still run."""
    cfg = _cfg(deps, track="dsa", n=1)
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id="cand_dsa", cfg=cfg)
    assert first.payload["question"]
    out = r.submit(sid, "binary search halves the range each step")
    assert out.payload["last_visit"]["score"] is not None
    assert out.payload["last_visit"]["weight"] in (0.5, 0.7)
