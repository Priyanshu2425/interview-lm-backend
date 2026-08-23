"""ISSUE-0036 — where you stand on a Topic, and what that must never become.

The reading is mechanical; the danger is what it turns into. A rank shown beside
a score reads as *"study these next"*, which is Topic recommendation — deferred
for want of calibration data, and a claim about a person this measurement cannot
support. So the tests here are as much about the figures that are **not**
available as about the one that is.
"""

from __future__ import annotations

import pytest
from conftest import signed_in_client
from fastapi.testclient import TestClient

from interviewer.confidence.comparison import (
    COHORT_FLOOR, CoverageStanding, Standing, coverage_percentile,
    rank_within_topic,
)
from interviewer.confidence.math import Posterior

TOPIC = "aiml-attention"


def firm(mastery: float, weight: float = 60.0) -> Posterior:
    """A posterior tight enough to read above the Evidence Floor."""
    return Posterior(1.0 + mastery * weight, 1.0 + (1 - mastery) * weight)


def cohort(**overrides: Posterior) -> dict[str, Posterior]:
    people = {f"c{i}": firm(0.5 + i * 0.01) for i in range(COHORT_FLOOR)}
    people.update(overrides)
    return people


# -- the rank ----------------------------------------------------------------

def test_a_rank_is_returned_for_a_topic_the_candidate_was_examined_on():
    people = cohort(me=firm(0.95))
    standing = rank_within_topic(TOPIC, candidate_id="me", posteriors=people)
    assert standing.rank == 1
    assert standing.cohort == len(people)
    assert standing.available is True


def test_a_rank_counts_only_the_candidates_definitely_above():
    """Definitely: their whole credible interval clears yours.

    Anyone merely *probably* above shares the position instead, which is what
    stops the rank claiming a difference the measurement does not have.
    """
    people = cohort(me=firm(0.10), top=firm(0.97), second=firm(0.90))
    standing = rank_within_topic(TOPIC, candidate_id="me", posteriors=people)
    assert standing.rank == standing.cohort
    assert standing.shared is False


def test_overlapping_posteriors_share_a_position():
    """0.82 and 0.81 may be the same measurement twice, and are not separated."""
    people = cohort(me=firm(0.82), twin=firm(0.81))
    standing = rank_within_topic(TOPIC, candidate_id="me", posteriors=people)
    twin = rank_within_topic(TOPIC, candidate_id="twin", posteriors=people)
    assert standing.rank == twin.rank
    assert standing.shared is True and twin.shared is True


def test_candidates_the_maths_can_separate_are_separated():
    people = {f"c{i}": firm(0.5, weight=400) for i in range(COHORT_FLOOR)}
    people["me"] = firm(0.99, weight=400)
    people["far_below"] = firm(0.01, weight=400)
    standing = rank_within_topic(TOPIC, candidate_id="me", posteriors=people)
    assert standing.rank == 1
    assert standing.shared is False


def test_a_rank_is_stated_against_the_cohort_it_was_taken_over():
    people = cohort(me=firm(0.7))
    standing = rank_within_topic(TOPIC, candidate_id="me", posteriors=people)
    assert 1 <= standing.rank <= standing.cohort


# -- who is in the cohort ----------------------------------------------------

def test_candidates_below_the_evidence_floor_are_excluded_not_counted_as_zero():
    """Counting them would drag every reading down in proportion to how many
    people had not got there yet — the fabrication *untested is not zero* exists
    to prevent."""
    people = cohort(me=firm(0.5))
    with_untested = {**people, **{f"u{i}": Posterior(1.0, 1.0) for i in range(50)}}
    tested = rank_within_topic(TOPIC, candidate_id="me", posteriors=people)
    mixed = rank_within_topic(TOPIC, candidate_id="me", posteriors=with_untested)
    assert mixed.rank == tested.rank
    assert mixed.cohort == tested.cohort


def test_a_topic_the_candidate_has_not_been_examined_on_yields_no_rank():
    people = cohort(me=Posterior(1.0, 1.0))
    standing = rank_within_topic(TOPIC, candidate_id="me", posteriors=people)
    assert standing.rank is None
    assert standing.available is False
    assert "Untested" in standing.reason


def test_an_unknown_candidate_is_not_ranked_last():
    standing = rank_within_topic(TOPIC, candidate_id="nobody", posteriors=cohort())
    assert standing.rank is None


# -- the Cohort Floor --------------------------------------------------------

def test_fewer_than_the_cohort_floor_yields_no_rank_and_a_stated_reason():
    """`#1 of 2` discloses the other Candidate completely."""
    people = {"me": firm(0.9), "you": firm(0.5)}
    standing = rank_within_topic(TOPIC, candidate_id="me", posteriors=people)
    assert standing.rank is None
    assert standing.cohort == 2
    assert "not enough Candidates yet" in standing.reason


def test_the_cohort_floor_is_one_named_constant_documented_as_provisional():
    """One constant, labelled a guess. Unlike the Evidence Floor it is derived
    from nothing — it is a privacy judgement, and it says so where it is set."""
    from interviewer.confidence import comparison

    assert COHORT_FLOOR == 10
    source = __import__("inspect").getsource(comparison)
    assert "Provisional" in source and "privacy judgement" in source
    # Set once. A second literal 10 in the ranking code is a second floor.
    assert source.count("COHORT_FLOOR = 10") == 1


def test_the_floor_is_a_parameter_so_a_deployment_can_state_its_own():
    people = {"me": firm(0.9), "you": firm(0.5)}
    standing = rank_within_topic(
        TOPIC, candidate_id="me", posteriors=people, cohort_floor=2
    )
    assert standing.rank == 1


# -- Coverage is compared as Coverage ---------------------------------------

def test_coverage_is_a_separate_reading_of_its_own_shape():
    standing = coverage_percentile(
        candidate_id="me",
        examined={"me": 45, **{f"c{i}": i for i in range(COHORT_FLOOR)}},
        topics_available=71,
    )
    assert isinstance(standing, CoverageStanding)
    assert standing.topics_examined == 45
    assert standing.topics_available == 71
    assert standing.percentile == 100


def test_no_function_takes_both_a_rank_and_a_coverage():
    """The refusal, enforced by the absence of a call rather than by review."""
    import inspect

    from interviewer.confidence import comparison

    for _, fn in inspect.getmembers(comparison, inspect.isfunction):
        params = inspect.signature(fn).parameters
        assert not ({"rank", "standing"} & set(params) and "coverage" in params)
    assert not hasattr(comparison, "overall_position")
    assert not hasattr(comparison, "score")


def test_a_candidate_with_no_tested_topic_gets_no_coverage_percentile():
    standing = coverage_percentile(
        candidate_id="me",
        examined={"me": 0, **{f"c{i}": 5 for i in range(COHORT_FLOOR)}},
        topics_available=71,
    )
    assert standing.percentile is None
    assert standing.reason


def test_coverage_below_the_cohort_floor_says_so():
    standing = coverage_percentile(
        candidate_id="me", examined={"me": 5, "you": 3}, topics_available=71
    )
    assert standing.percentile is None
    assert "not enough Candidates yet" in standing.reason


# -- over the wire -----------------------------------------------------------

HDR = {"x-operator-token": "dev-operator-token"}


@pytest.fixture()
def client(content_db, clean_db):
    from interviewer.api.app import create_app
    from interviewer.api.deps import refresh_corpus

    refresh_corpus()
    with signed_in_client() as c:
        yield c
    refresh_corpus()


def _shared_topic(client, real_notes) -> str:
    notebook_id = client.post(
        "/v1/operator/corpora", json={"title": "InterviewLM"}, headers=HDR
    ).json()["notebook_id"]
    client.post(
        f"/v1/operator/corpora/{notebook_id}/sources",
        json={"title": "AIML", "text": real_notes}, headers=HDR,
    )
    from interviewer.api.deps import get_notebook_service

    return sorted(get_notebook_service().store.frozen_topics(notebook_id))[0]


def _personal_topic(client, real_notes, ingested) -> str:
    notebook_id = client.post(
        "/v1/notebooks", json={"candidate_id": "cand-p", "title": "Mine"}
    ).json()["notebook_id"]
    client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "AIML", "text": real_notes},
    )
    ingested(client, notebook_id)
    from interviewer.api.deps import get_notebook_service

    return sorted(get_notebook_service().store.frozen_topics(notebook_id))[0]


def _seed(engine, topic_id: str, people: dict[str, Posterior]) -> None:
    import sqlalchemy as sa

    from interviewer.db import schema as S

    with engine.begin() as c:
        for candidate_id, posterior in people.items():
            c.execute(sa.insert(S.topic_confidence).values(
                candidate_id=candidate_id, topic_id=topic_id,
                alpha=posterior.alpha, beta=posterior.beta,
            ))


def test_the_route_returns_a_rank_for_a_shared_topic(client, clean_db, real_notes):
    topic_id = _shared_topic(client, real_notes)
    _seed(clean_db, topic_id, cohort(me=firm(0.95)))
    body = signed_in_client("me").get(
        f"/v1/candidates/me/topics/{topic_id}/standing").json()
    assert body["rank"] == 1
    assert body["cohort"] >= COHORT_FLOOR


def test_a_personal_corpus_never_yields_a_rank(
    client, clean_db, real_notes, ingested
):
    """Their cohort is one by construction, and the route says exactly that."""
    topic_id = _personal_topic(client, real_notes, ingested)
    _seed(clean_db, topic_id, cohort(me=firm(0.95)))
    body = signed_in_client("me").get(
        f"/v1/candidates/me/topics/{topic_id}/standing").json()
    assert body["rank"] is None
    assert "nobody to compare you to" in body["reason"]


def test_the_route_never_returns_an_overall_position(client):
    """No endpoint anywhere returns a Candidate's position across Topics."""
    paths = client.get("/v1/openapi.json").json()["paths"]
    ranked = [p for p in paths if "standing" in p]
    assert ranked == [
        "/v1/candidates/me/topics/{topic_id}/standing",
        "/v1/candidates/me/coverage-standing",
    ]
    for path in paths:
        assert "leaderboard" not in path and "rank" not in path


def test_coverage_standing_is_its_own_route_returning_its_own_shape(client):
    body = client.get("/v1/candidates/me/coverage-standing").json()
    assert set(body) == {
        "topics_examined", "topics_available", "cohort", "percentile", "reason"
    }
    assert "rank" not in body


# -- the placement, held by the API's shape (ADR-0022) -----------------------

def test_a_standing_is_asked_for_one_topic_at_a_time(client):
    """No route takes a list of Topics, so no caller can build a column.

    The placement carries a constraint the data cannot — one Topic, on request —
    and it only holds if the API cannot answer the other question. It cannot.
    """
    paths = client.get("/v1/openapi.json").json()["paths"]
    standing = paths["/v1/candidates/me/topics/{topic_id}/standing"]
    params = {p["name"] for p in standing["get"].get("parameters", [])}
    # One Topic, and no Candidate: whose standing it is comes from the token
    # (ADR-0026), so the only thing a caller may name is the Topic.
    assert params == {"topic_id"}
    assert not any(
        "standings" in path or path.endswith("/standing/all") for path in paths
    )


def test_the_two_comparisons_are_never_returned_together(client):
    """Coverage is compared as Coverage, in its own response and nowhere else."""
    topic = client.get("/v1/corpus/modules").json()
    body = client.get("/v1/candidates/me/coverage-standing").json()
    assert "rank" not in body and "shared" not in body
    assert topic is not None
