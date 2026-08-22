"""Related Topics, answered from rows (ISSUE-0029, rewritten by ISSUE-0037).

An empty list means one of two things — a Topic whose Corpus this deployment
does not hold, and a Topic that genuinely has no neighbour above the floor. They
look identical from outside on purpose: the surface renders nothing in both
cases, and nothing is the honest answer in both.

What this file is really guarding is ADR-0005's central claim, which survived
the move off disk intact: **nothing is embedded at question time.** Every vector
compared here was written when its Topic was.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from interviewer.corpus.related import MIN_SCORE, TOP_K, centre, rank


@pytest.fixture()
def client(content_db, clean_db):
    from interviewer.api.app import create_app
    from interviewer.api.deps import refresh_corpus

    refresh_corpus()
    with TestClient(create_app()) as c:
        yield c
    refresh_corpus()


@pytest.fixture()
def library(served_corpus):
    """The imported Corpus. Enough Topics for a neighbour to mean anything.

    Deliberately not a four-Topic notebook: see
    `test_a_library_of_a_handful_of_topics_has_no_neighbours` for why that is a
    property of the maths rather than a gap in the fixture.
    """
    return served_corpus


def _first_topic(notebook_id: str) -> str:
    from interviewer.api.deps import get_notebook_service

    return sorted(get_notebook_service().store.frozen_topics(notebook_id))[0]


# -- the route ---------------------------------------------------------------

def test_a_topic_returns_its_neighbours(client, library):
    topic_id = _first_topic(library)
    response = client.get(f"/v1/corpus/topics/{topic_id}/related")
    assert response.status_code == 200
    body = response.json()
    assert 1 <= len(body) <= TOP_K
    assert set(body[0]) == {
        "topic_id", "title", "module_id", "same_module", "score"
    }


def test_neighbours_arrive_ranked_and_the_surface_reorders_nothing(client, library):
    """ADR-0009: the client draws what the server decided."""
    body = client.get(
        f"/v1/corpus/topics/{_first_topic(library)}/related"
    ).json()
    scores = [row["score"] for row in body]
    assert scores == sorted(scores, reverse=True)
    assert all(row["score"] >= MIN_SCORE for row in body)


def test_a_topic_is_never_returned_as_its_own_neighbour(client, library):
    wanted = _first_topic(library)
    body = client.get(f"/v1/corpus/topics/{wanted}/related").json()
    assert wanted not in {row["topic_id"] for row in body}


def test_an_unknown_topic_is_a_404(client, library):
    assert client.get("/v1/corpus/topics/nope/related").status_code == 404


def test_a_deployment_holding_no_corpus_still_serves_the_route(client):
    """Nothing stored is a real deployment, not a broken one."""
    assert client.get("/v1/corpus/topics/anything/related").status_code == 404


def test_the_route_embeds_nothing(client, library, monkeypatch):
    """ADR-0005 holds, and holds *after* the artifact went away.

    Every vector this compares was written at ingest. If anything on this path
    reached an embedder, this would fail.
    """
    from interviewer.corpus.adapters.notebook.embedding import HashingEmbedder

    def forbidden(*a, **kw):
        raise AssertionError("the related route must not embed anything")

    monkeypatch.setattr(HashingEmbedder, "embed", forbidden)
    monkeypatch.setattr(HashingEmbedder, "embed_images", forbidden, raising=False)
    assert client.get(
        f"/v1/corpus/topics/{_first_topic(library)}/related"
    ).status_code == 200


def test_a_topic_from_another_library_is_never_a_neighbour(
    client, library, ingested, real_notes
):
    """Two Libraries are two geometries, and a cosine across them means nothing.

    `notebook.embedding_model` is per Corpus, so staying inside one is what
    makes the comparison well founded rather than merely tidy.
    """
    other = client.post(
        "/v1/notebooks", json={"candidate_id": "cand-rel", "title": "Second"}
    ).json()["notebook_id"]
    client.post(
        f"/v1/notebooks/{other}/sources",
        json={"title": "More notes", "text": real_notes + "\n\nAnd more.\n"},
    )
    ingested(client, other)
    from interviewer.api.deps import get_notebook_service

    mine = set(get_notebook_service().store.frozen_topics(library))
    body = client.get(f"/v1/corpus/topics/{_first_topic(library)}/related").json()
    assert {row["topic_id"] for row in body} <= mine


# -- the ranking itself ------------------------------------------------------

def test_ranking_is_deterministic_and_ordered_by_id_on_a_tie():
    """Two Topics at an identical distance must not swap between two reads."""
    centroids = {
        "a": (1.0, 0.0, 0.0),
        "b": (0.0, 1.0, 0.0),
        "c": (0.0, 1.0, 0.0),
    }
    titles = {k: k.upper() for k in centroids}
    modules = dict.fromkeys(centroids, "m1")
    first = rank("a", centroids=centroids, titles=titles, module_of=modules)
    again = rank("a", centroids=centroids, titles=titles, module_of=modules)
    assert [n.topic_id for n in first] == [n.topic_id for n in again]
    assert [n.topic_id for n in first] == sorted(n.topic_id for n in first)


def test_a_corpus_of_one_topic_has_no_neighbours():
    assert rank("a", centroids={"a": (1.0, 0.0)}, titles={}, module_of={}) == ()


def test_centring_is_what_makes_the_ranking_mean_anything():
    """A narrow cone of vectors ranks as noise until it is centred.

    The measured effect on the shipped Corpus was 86% to 94% same-Track
    neighbours; the shape of it is visible on three vectors.
    """
    a, b = (0.99, 0.10, 0.0), (0.99, 0.0, 0.10)
    mean = (0.99, 0.05, 0.05)
    raw = sum(x * y for x, y in zip(a, b))
    centred = sum(
        x * y for x, y in zip(centre(a, mean), centre(b, mean))
    )
    assert raw > 0.9
    assert centred < raw


def test_same_module_is_reported_rather_than_filtered():
    """Which to show is the surface's decision, so both are returned."""
    centroids = {"a": (1.0, 0.0, 0.0), "b": (0.95, 0.31, 0.0), "c": (0.0, 0.0, 1.0)}
    for i in range(8):
        centroids[f"x{i}"] = (0.05 * i, 1.0, 0.0)
    modules = {"a": "m1", "b": "m1", **{k: "m2" for k in centroids if k > "b"}}
    neighbours = rank(
        "a",
        centroids=centroids,
        titles={k: k for k in centroids},
        module_of=modules,
    )
    by_id = {n.topic_id: n for n in neighbours}
    assert by_id["b"].same_module is True
    assert by_id["c"].same_module is False


def test_a_library_of_a_handful_of_topics_has_no_neighbours(client, ingested, real_notes):
    """Not a gap: a property of measuring from the centre of a small set.

    Centring k Topics on their own mean puts the average pairwise cosine near
    -1/(k-1), so with four Topics every pair scores about -0.33 and none clears
    the floor. That is the honest answer — "related" over four Topics from one
    document is a claim the material cannot support — and it is why the floor is
    left where it is rather than lowered until something appears.
    """
    notebook_id = client.post(
        "/v1/notebooks", json={"candidate_id": "cand-small", "title": "Notes"}
    ).json()["notebook_id"]
    client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "AIML notes", "text": real_notes},
    )
    ingested(client, notebook_id)
    from interviewer.api.deps import get_notebook_service, refresh_corpus

    refresh_corpus()
    topics = sorted(get_notebook_service().store.frozen_topics(notebook_id))
    assert len(topics) < 10
    body = client.get(f"/v1/corpus/topics/{topics[0]}/related").json()
    assert body == []
