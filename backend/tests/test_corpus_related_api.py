"""Related Topics over the wire, and the three ways it says nothing.

An empty list means one of three things — no index, an index that no longer
matches the Corpus, or a Topic that genuinely has no neighbours. They look
identical from outside on purpose: the surface renders nothing in all three
cases, and nothing is the honest answer in all three.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from interviewer.corpus.adapters.notebook import HashingEmbedder
from interviewer.corpus.index import build
from interviewer.corpus.related import save


@pytest.fixture()
def app_with_index(tmp_path, corpus, monkeypatch):
    """An API wired to a freshly built index for the Corpus it serves."""
    from interviewer.api import deps

    path = tmp_path / "corpus-index.json"
    save(build(corpus, HashingEmbedder()), path)
    monkeypatch.setenv("CORPUS_INDEX_PATH", str(path))
    for cache in (deps.get_related_topics, deps.get_embedder):
        cache.cache_clear()
    yield deps
    for cache in (deps.get_related_topics, deps.get_embedder):
        cache.cache_clear()


@pytest.fixture()
def client(app_with_index):
    from interviewer.api.app import create_app

    return TestClient(create_app())


def topic_id(client) -> str:
    return client.get("/v1/corpus/tracks").json() and _first_topic()


def _first_topic() -> str:
    from interviewer.api.deps import get_corpus

    return sorted(t.id for t in get_corpus().topics)[0]


def test_a_topic_returns_its_neighbours(client):
    response = client.get(f"/v1/corpus/topics/{_first_topic()}/related")
    assert response.status_code == 200
    body = response.json()
    assert 1 <= len(body) <= 5
    assert set(body[0]) == {
        "topic_id", "title", "module_id", "same_module", "score"
    }


def test_neighbours_arrive_ranked_and_the_surface_reorders_nothing(client):
    """ADR-0009: the client draws what the server decided."""
    body = client.get(f"/v1/corpus/topics/{_first_topic()}/related").json()
    scores = [row["score"] for row in body]
    assert scores == sorted(scores, reverse=True)


def test_a_topic_is_never_returned_as_its_own_neighbour(client):
    wanted = _first_topic()
    body = client.get(f"/v1/corpus/topics/{wanted}/related").json()
    assert wanted not in {row["topic_id"] for row in body}


def test_an_unknown_topic_is_a_404(client):
    assert client.get("/v1/corpus/topics/nope/related").status_code == 404


def test_no_index_still_serves_the_route(tmp_path, monkeypatch):
    """A deployment without the artifact behaves like Topics with no neighbours."""
    from interviewer.api import deps
    from interviewer.api.app import create_app

    monkeypatch.setenv("CORPUS_INDEX_PATH", str(tmp_path / "absent.json"))
    deps.get_related_topics.cache_clear()
    try:
        client = TestClient(create_app())
        response = client.get(f"/v1/corpus/topics/{_first_topic()}/related")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        deps.get_related_topics.cache_clear()


def test_a_stale_index_serves_nothing_rather_than_something_wrong(
    tmp_path, corpus, monkeypatch
):
    from dataclasses import replace

    from interviewer.api import deps
    from interviewer.api.app import create_app

    path = tmp_path / "corpus-index.json"
    save(replace(build(corpus, HashingEmbedder()), fingerprint="moved on"), path)
    monkeypatch.setenv("CORPUS_INDEX_PATH", str(path))
    deps.get_related_topics.cache_clear()
    try:
        client = TestClient(create_app())
        response = client.get(f"/v1/corpus/topics/{_first_topic()}/related")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        deps.get_related_topics.cache_clear()


def test_a_notebook_topic_has_no_neighbours_and_does_not_make_the_index_stale(
    client, notebooks, real_notes
):
    """Adding a notebook is not a change to what shipped."""
    from interviewer.api.deps import get_related_topics

    assert get_related_topics().available is True
    notebooks.create("nb-1", "cand-1", "Notes")
    notebooks.add_source("nb-1", source_id="s1", title="N", text=real_notes)
    # The index is checked against the base Corpus, so it stays fresh.
    assert get_related_topics().available is True
    assert get_related_topics().for_topic("nbt_whatever") == []


def test_the_route_embeds_nothing(client, monkeypatch):
    """ADR-0005 holds: no query is embedded at request time.

    The neighbours were decided when the index was built. If anything here
    reached an embedder, this would fail.
    """
    from interviewer.corpus.adapters.notebook.embedding import HashingEmbedder

    def forbidden(*a, **kw):
        raise AssertionError("the related route must not embed anything")

    monkeypatch.setattr(HashingEmbedder, "embed", forbidden)
    monkeypatch.setattr(HashingEmbedder, "embed_query", forbidden)
    assert client.get(f"/v1/corpus/topics/{_first_topic()}/related").status_code == 200
