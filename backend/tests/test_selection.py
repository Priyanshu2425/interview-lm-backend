"""ISSUE-0005 — selection, scope and the soft deadline."""

import numpy as np

from interviewer.confidence.math import apply_evidence
from interviewer.confidence.selector import TopicSelector
from interviewer.graph.runner import SessionRunner
from interviewer.graph.sessions import SessionConfig

CANDIDATE = "cand_sel"


def _cfg(deps, n=2, seconds=1800):
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:n]
    return SessionConfig(scope_module_ids=tuple(mods), duration_seconds=seconds)


def test_the_opening_topic_follows_curriculum_order(deps):
    r = SessionRunner(deps)
    cfg = _cfg(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=cfg)
    expected = deps.corpus.topic_ids_for(list(cfg.scope_module_ids))[0]
    assert first.payload["topic_id"] == expected


def test_subsequent_topics_come_from_the_selector(deps):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    second = r.submit(sid, "answer")
    assert second.payload["topic_id"] != first.payload["topic_id"]


def test_the_selector_prefers_the_weakest_looking_topic(deps, clean_db):
    """Thompson sampling over posteriors, with the weakest drawing lowest."""
    store = deps.confidence
    sel = TopicSelector(store)
    ids = ["strong", "weak", "unknown"]

    # seed two posteriors directly
    from sqlalchemy import insert
    from interviewer.db import schema as S
    with clean_db.begin() as c:
        c.execute(insert(S.topic_confidence).values(
            candidate_id=CANDIDATE, topic_id="strong", alpha=30.0, beta=2.0))
        c.execute(insert(S.topic_confidence).values(
            candidate_id=CANDIDATE, topic_id="weak", alpha=2.0, beta=30.0))

    picks = [sel.choose(candidate_id=CANDIDATE, topic_ids=ids,
                        rng=np.random.default_rng(s)) for s in range(40)]
    assert picks.count("strong") == 0
    assert picks.count("weak") > picks.count("unknown")


def test_an_untested_topic_is_explored_without_a_separate_rule(deps, clean_db):
    from sqlalchemy import insert
    from interviewer.db import schema as S
    with clean_db.begin() as c:
        c.execute(insert(S.topic_confidence).values(
            candidate_id=CANDIDATE, topic_id="known", alpha=14.0, beta=6.0))
    sel = TopicSelector(deps.confidence)
    picks = [sel.choose(candidate_id=CANDIDATE, topic_ids=["known", "fresh"],
                        rng=np.random.default_rng(s)) for s in range(40)]
    assert "fresh" in picks


def test_selection_is_reproducible_from_the_same_injected_randomness(deps):
    sel = TopicSelector(deps.confidence)
    ids = [f"t{i}" for i in range(8)]
    a = [sel.choose(candidate_id=CANDIDATE, topic_ids=ids,
                    rng=np.random.default_rng(3)) for _ in range(5)]
    assert len(set(a)) == 1


def test_scope_and_duration_are_recorded_on_the_session(deps):
    r = SessionRunner(deps)
    cfg = _cfg(deps, n=2, seconds=900)
    sid, _ = r.start(candidate_id=CANDIDATE, cfg=cfg)
    row = deps.sessions.get(sid)
    assert tuple(row["scope_module_ids"]) == cfg.scope_module_ids
    assert row["duration_seconds"] == 900


def test_a_session_scoped_to_more_modules_holds_one_topic_at_a_time(deps):
    """Scope and load are different axes."""
    r = SessionRunner(deps)
    cfg = _cfg(deps, n=3)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=cfg)
    in_scope = deps.corpus.topic_ids_for(list(cfg.scope_module_ids))
    assert len(in_scope) > 10
    assert len(deps.visits.for_session(sid)) == 1


def test_a_session_cannot_be_created_with_no_scope():
    import pytest
    with pytest.raises(ValueError, match="at least one Module"):
        SessionConfig(scope_module_ids=(), duration_seconds=600)
    with pytest.raises(ValueError, match="positive duration"):
        SessionConfig(scope_module_ids=("m",), duration_seconds=0)
