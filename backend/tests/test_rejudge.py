"""PRD-0002 §29 — re-judging a batch with a reference grader."""

from interviewer.graph.ports import ScriptedModel
from interviewer.graph.runner import SessionRunner
from interviewer.graph.sessions import SessionConfig
from interviewer.judge.rejudge import ReJudge

CAND = "cand_rejudge"


def _session(deps, answers=3):
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:1]
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CAND,
                       cfg=SessionConfig(scope_module_ids=tuple(mods),
                                         duration_seconds=3600))
    for _ in range(answers):
        if out.kind == "session_ended":
            break
        out = r.submit(sid, "an answer worth grading")
    return sid


def test_every_evidence_row_carries_enough_to_be_rescored(deps):
    _session(deps, 2)
    rows = deps.evidence.rejudgeable()
    assert rows
    for r in rows:
        assert r["exchange_snapshot"]["turns"]
        assert r["grading_mode"] and r["rubric_version"]
        assert r["grader_kind"]


def test_a_reference_grader_can_rescore_a_batch_without_writing(deps, clean_db):
    import sqlalchemy as sa
    from interviewer.db import schema as S

    _session(deps, 2)
    rows = deps.evidence.rejudgeable()
    with clean_db.connect() as c:
        before = c.execute(sa.select(S.evidence.c.score)).scalars().all()

    result = ReJudge(deps.loader).run(
        rows, reference=ScriptedModel(default="SCORE: 0.3\nWHY: stricter.")
    )
    assert len(result.compared) == len(rows)

    with clean_db.connect() as c:
        after = c.execute(sa.select(S.evidence.c.score)).scalars().all()
    # Evidence is permanent: a re-judgement measures the grader, not the record.
    assert before == after


def test_the_comparison_reports_the_delta_per_row(deps):
    _session(deps, 1)
    rows = deps.evidence.rejudgeable()
    result = ReJudge(deps.loader).run(
        rows, reference=ScriptedModel(default="SCORE: 0.5\nWHY: r")
    )
    c = result.compared[0]
    assert c.reference_score == 0.5
    assert c.delta == round(0.5 - c.original_score, 4)


def test_deltas_group_by_provider_which_is_what_a_normaliser_would_need(deps):
    _session(deps, 2)
    result = ReJudge(deps.loader).run(
        deps.evidence.rejudgeable(),
        reference=ScriptedModel(default="SCORE: 0.6\nWHY: r"),
    )
    by = result.by_provider()
    assert "deepseek" in by
    assert isinstance(result.mean_delta, float)


def test_rejudging_can_be_filtered_to_one_grading_mode(deps):
    _session(deps, 3)
    gt = deps.evidence.rejudgeable(mode="ground_truth")
    assert all(r["grading_mode"] == "ground_truth" for r in gt)


def test_no_normaliser_is_applied_anywhere(deps):
    """The measurement exists; the constant deliberately does not."""
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "interviewer"
    for f in src.rglob("*.py"):
        text = f.read_text().lower()
        assert "provider_normaliser" not in text
        assert "normalise_score" not in text
