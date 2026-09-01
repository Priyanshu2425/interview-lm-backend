"""ISSUE-0031 — Related Topics, at the placement ADR-0023 chose.

The picker, and the reason is the whole slice: it is the one place a claim about
the *material* cannot be misread as a claim about the *person*. Nothing has been
measured when a Candidate is choosing scope, so there is no score for a list of
Modules to sit beside and nothing for it to read as remediation.

So the tests are mostly about what this reading refuses to carry.
"""

from __future__ import annotations

import pytest
from conftest import signed_in_client
from fastapi.testclient import TestClient

from interviewer.service.corpus.related import modules_touched


@pytest.fixture()
def client(content_db, clean_db, served_corpus):
    from interviewer.app import create_app

    return signed_in_client()


def _modules(client, track="aiml"):
    return client.get("/v1/skills/modules", params={"track": track}).json()


# -- the reading -------------------------------------------------------------

def test_a_scope_reports_the_modules_it_touches(client):
    chosen = _modules(client)[0]["module_id"]
    body = client.get("/v1/skills/scope/related",
                      params=[("module_id", chosen)]).json()
    assert body
    assert set(body[0]) == {
        "module_id", "title", "track_key", "in_scope", "edges", "score",
        "selectable",
    }


def test_the_server_orders_it_and_the_surface_reorders_nothing(client):
    """ADR-0009: the client draws what the server decided."""
    chosen = _modules(client)[0]["module_id"]
    body = client.get("/v1/skills/scope/related",
                      params=[("module_id", chosen)]).json()
    scores = [row["score"] for row in body]
    assert scores == sorted(scores, reverse=True)


def test_a_module_in_the_chosen_scope_is_marked_as_such(client):
    """This is where same-Module and cross-Module become distinguishable.

    At this placement the distinction has a plain meaning: a neighbour inside
    the scope is material already covered, one outside it is the sideways
    connection the whole line of work was for.
    """
    chosen = _modules(client)[0]["module_id"]
    body = client.get("/v1/skills/scope/related",
                      params=[("module_id", chosen)]).json()
    assert any(row["in_scope"] for row in body)
    assert any(not row["in_scope"] for row in body)


def test_an_empty_scope_touches_nothing_rather_than_everything(client):
    assert client.get("/v1/skills/scope/related").json() == []


def test_an_unknown_module_yields_nothing_rather_than_a_partial_answer(client):
    assert client.get("/v1/skills/scope/related",
                      params=[("module_id", "nope")]).json() == []


def test_a_deployment_with_no_neighbours_returns_an_empty_list(
    client, ingested, real_notes
):
    """A Library too small to have neighbours renders as nothing at all."""
    notebook_id = client.post(
        "/v1/notebooks", json={"candidate_id": "cand-small", "title": "Notes"}
    ).json()["notebook_id"]
    module_id = client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "AIML notes", "text": real_notes},
    ).json()["module_id"]
    ingested(client, notebook_id)
    from interviewer.deps import refresh_corpus

    refresh_corpus()
    assert client.get("/v1/skills/scope/related",
                      params=[("module_id", module_id)]).json() == []


# -- what it refuses to carry ------------------------------------------------

def test_the_reading_carries_no_figure_about_the_candidate(client):
    """No Coverage, no Mastery, and nothing that could be combined into one."""
    chosen = _modules(client)[0]["module_id"]
    raw = client.get("/v1/skills/scope/related",
                     params=[("module_id", chosen)]).text.lower()
    for forbidden in ("mastery", "coverage", "band", "score_percent", "percent"):
        assert forbidden not in raw
    assert "difficult" not in raw


def test_the_reading_needs_no_candidate_and_takes_none(client):
    """It is a statement about the material, so it cannot be about a person."""
    import inspect

    from interviewer.routes.v1 import skills as routes_corpus

    params = inspect.signature(routes_corpus.scope_related).parameters
    assert "candidate_id" not in params


# -- the aggregation ---------------------------------------------------------

def test_edges_are_counted_and_the_closest_one_decides_the_order():
    def neighbours(topic_id):
        return {
            "t1": [
                {"topic_id": "x", "module_id": "far", "score": 0.9},
                {"topic_id": "y", "module_id": "near", "score": 0.2},
            ],
            "t2": [
                {"topic_id": "z", "module_id": "near", "score": 0.95},
            ],
        }[topic_id]

    touched = modules_touched(
        ["t1", "t2"],
        neighbours_of=neighbours,
        module_of={},
        titles={"near": "Near", "far": "Far"},
        in_scope=set(),
    )
    assert [t.module_id for t in touched] == ["near", "far"]
    assert touched[0].edges == 2
    assert touched[0].score == 0.95


def test_two_modules_at_the_same_distance_do_not_swap_between_reads():
    def neighbours(topic_id):
        return [
            {"topic_id": "x", "module_id": "b", "score": 0.5},
            {"topic_id": "y", "module_id": "a", "score": 0.5},
        ]

    args = dict(
        neighbours_of=neighbours, module_of={}, titles={}, in_scope=set()
    )
    first = [t.module_id for t in modules_touched(["t"], **args)]
    again = [t.module_id for t in modules_touched(["t"], **args)]
    assert first == again == ["a", "b"]
