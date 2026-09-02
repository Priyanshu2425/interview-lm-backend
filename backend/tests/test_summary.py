"""ISSUE-0004/0005 — the Session summary a Candidate reads at the end."""

from conftest import grade_session

from interviewer.service.graph.runner_service import SessionRunner
from interviewer.service.graph.sessions import SessionConfig

CAND = "cand_summary"


def _svc(deps, corpus):
    from interviewer.service.confidence.reading_service import SessionReadingService

    return SessionReadingService(
        sessions=deps.sessions, visits=deps.visits, evidence=deps.evidence,
        plans=None, loader=deps.loader, confidence=deps.confidence,
        corpus=corpus,
    )


def _readings(corpus, deps):
    """The Candidate-level readings — not about one Session, and not read
    through the Session reading."""
    from interviewer.service.confidence.summary_service import CandidateReadings

    return CandidateReadings(corpus, deps.confidence)


def _run(deps, n_answers=3, n_modules=1):
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:n_modules]
    cfg = SessionConfig(scope_module_ids=tuple(mods), duration_seconds=3600)
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CAND, cfg=cfg)
    for _ in range(n_answers):
        if out.kind == "session_ended":
            break
        out = r.submit(sid, "an answer")
    return sid


def test_the_summary_reports_coverage_and_mastery_separately(deps, corpus):
    sid = _run(deps)
    s = _svc(deps, corpus).summary(sid)
    assert "topics_examined" in s.coverage
    assert "looks_solid" in s.mastery
    # nothing merges them
    assert not set(s.coverage) & set(s.mastery)


def test_coverage_counts_against_the_whole_corpus(deps, corpus):
    """Coverage reads posteriors, so it needs a graded Session (ISSUE-0042).

    `topics_examined` on the summary counts questions the Session asked, and it
    is non-zero the moment one is answered. Coverage is a different reading —
    it is derived from Evidence — and until ISSUE-0044 grades a Session at the
    end, a Session that has only run has moved no posterior.
    """
    sid = _run(deps)
    s = _svc(deps, corpus).summary(sid)
    assert s.coverage["topics_total"] == 71
    assert s.topics_examined > 0
    assert s.coverage["topics_examined"] == 0

    grade_session(deps, sid)
    s = _svc(deps, corpus).summary(sid)
    assert 0 < s.coverage["topics_examined"] <= 71


def test_a_topic_examined_once_carries_no_mastery_number(deps, corpus):
    sid = _run(deps, n_answers=1)
    s = _svc(deps, corpus).summary(sid)
    first = s.per_topic[0]
    assert first["band"] in ("untested", "early")
    if first["band"] == "untested":
        assert first["mastery"] is None


def test_the_summary_names_the_topics_never_asked_about(deps, corpus):
    sid = _run(deps, n_answers=2)
    s = _svc(deps, corpus).summary(sid)
    assert s.untested_modules
    total_untested = sum(u["topics_untested"] for u in s.untested_modules)
    assert total_untested == 71 - s.coverage["topics_examined"]


def test_untested_modules_say_whether_they_carry_ground_truth(deps, corpus):
    sid = _run(deps, n_answers=1)
    s = _svc(deps, corpus).summary(sid)
    genai = next(u for u in s.untested_modules if u["title"].startswith("Basics of GenAI"))
    assert genai["has_ground_truth"] is False
    assert genai["topics_untested"] == 9


def test_the_summary_records_which_modes_did_the_grading(deps, corpus):
    sid = _run(deps, n_answers=3)
    s = _svc(deps, corpus).summary(sid)
    assert (s.ground_truth_visits + s.text_grounded_visits
            + s.model_judgment_visits) == s.topics_examined


def test_the_summary_records_the_chosen_duration_for_comparability(deps, corpus):
    sid = _run(deps)
    s = _svc(deps, corpus).summary(sid)
    assert s.duration_seconds == 3600


def test_candidate_readings_return_two_readings_and_no_combined_score(deps, corpus):
    _run(deps, n_answers=2)
    out = _readings(corpus, deps).candidate_readings(CAND)
    assert set(out) == {"coverage", "mastery", "topics"}
    flat = str(out).lower()
    assert "overall" not in flat and "percent" not in flat


def test_a_topic_below_the_floor_reports_none_never_zero(deps, corpus):
    _run(deps, n_answers=1)
    out = _readings(corpus, deps).candidate_readings(CAND)
    for t in out["topics"]:
        if t["band"] == "untested":
            assert t["mastery"] is None
