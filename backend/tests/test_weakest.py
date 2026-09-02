"""PRD-0002 §6 — seeing which Topics look weakest."""

import sqlalchemy as sa

from interviewer.service.confidence.summary_service import CandidateReadings
from interviewer.db import schema as S

CAND = "cand_weak"


def _seed(engine, rows):
    with engine.begin() as c:
        for tid, a, b in rows:
            c.execute(sa.insert(S.topic_confidence).values(
                candidate_id=CAND, topic_id=tid, alpha=a, beta=b))


def test_weakest_topics_are_ordered_by_mastery(clean_db, corpus, deps):
    ids = [t.id for t in corpus.topics[:4]]
    _seed(clean_db, [
        (ids[0], 8.2, 3.2),     # solid
        (ids[1], 3.6, 7.4),     # weak
        (ids[2], 6.9, 3.9),     # solid-ish
    ])
    svc = CandidateReadings(corpus, deps.confidence)
    weak = svc.weakest(CAND)
    assert weak[0]["topic_id"] == ids[1]
    assert weak[0]["band"] == "firm_weak"
    assert weak[0]["title"]


def test_untested_topics_are_excluded_not_sorted_to_the_bottom(clean_db, corpus, deps):
    """They are not weak. They are unknown, and conflating the two is the whole
    failure the model exists to prevent."""
    ids = [t.id for t in corpus.topics[:3]]
    _seed(clean_db, [
        (ids[0], 3.6, 7.4),     # weak
        (ids[1], 1.0, 1.0),     # the prior
    ])
    svc = CandidateReadings(corpus, deps.confidence)
    weak = svc.weakest(CAND)
    assert [w["topic_id"] for w in weak] == [ids[0]]


def test_every_weakest_reading_carries_a_number_because_it_cleared_the_floor(
    clean_db, corpus, deps
):
    ids = [t.id for t in corpus.topics[:2]]
    _seed(clean_db, [(ids[0], 3.6, 7.4), (ids[1], 8.2, 3.2)])
    svc = CandidateReadings(corpus, deps.confidence)
    for w in svc.weakest(CAND):
        assert w["mastery"] is not None
        assert w["interval"] is not None
