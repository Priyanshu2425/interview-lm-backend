"""ISSUE-0030 — a stale Corpus index is visible, not silent.

ISSUE-0029 made a stale index *harmless*: the neighbours stop appearing rather
than turning into wrong ones. That leaves an operator with a feature that went
away and nothing to read about it, which is the state this slice closes.

Two properties are load-bearing here and are easy to break in opposite
directions. Visibility must not re-enable serving — a reading that reports
"stale" beside neighbours that are still being served is worse than either
alone. And a stale index must stay a *state*: no route fails, no Session is
affected, the Corpus is fully examinable without a single neighbour.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from interviewer.corpus.adapters.notebook import HashingEmbedder
from interviewer.corpus.index import build
from interviewer.corpus.related import RelatedTopics, load, save

STAMP = "2026-08-22T09:00:00+00:00"


@pytest.fixture(scope="module")
def index(corpus):
    return build(corpus, HashingEmbedder(), built_at=STAMP)


# -- the artifact says what it was built from --------------------------------

def test_the_artifact_records_what_it_was_built_from(index, tmp_path):
    """Readable without running anything, because that is when it is needed."""
    path = tmp_path / "corpus-index.json"
    save(index, path)
    body = json.loads(path.read_text())
    assert body["fingerprint"] == index.fingerprint
    assert body["embedding_model"] == index.embedding_model
    assert body["built_at"] == STAMP
    assert body["topic_count"] == 71


def test_the_build_time_round_trips(index, tmp_path):
    path = tmp_path / "corpus-index.json"
    save(index, path)
    assert load(path).built_at == STAMP


def test_the_clock_is_injected_rather_than_read(corpus):
    """`build` reads no clock, which is what keeps the artifact diffable.

    The stamp is a fact about the *run*, so it arrives at the edge — from the
    script — rather than from inside a function whose whole value is that the
    same inputs produce the same bytes.
    """
    assert build(corpus, HashingEmbedder()).built_at == ""


def test_deleting_the_artifact_and_rebuilding_it_reproduces_it(corpus, tmp_path):
    """Byte-for-byte, apart from the one field that records when it was built.

    That field is the only permitted difference and is excluded deliberately:
    everything describing the *content* must be identical, or the artifact stops
    being reviewable in a diff.
    """
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    save(build(corpus, HashingEmbedder(), built_at="2026-01-01T00:00:00+00:00"), first)
    save(build(corpus, HashingEmbedder(), built_at="2026-08-22T09:00:00+00:00"), second)

    def without_stamp(text: str) -> str:
        body = json.loads(text)
        body.pop("built_at")
        return json.dumps(body, indent=1, sort_keys=True)

    assert first.read_bytes() != second.read_bytes()
    assert without_stamp(first.read_text()) == without_stamp(second.read_text())


# -- the reading -------------------------------------------------------------

def test_a_fresh_index_reads_fresh(corpus, index):
    reading = RelatedTopics(
        index, corpus, embedding_model=index.embedding_model
    ).staleness.reading()
    assert reading["state"] == "fresh"
    assert reading["changed"] == []
    assert reading["serving"] is True
    assert reading["built_at"] == STAMP
    assert reading["topic_count"] == 71


def test_the_reading_names_a_changed_corpus(corpus, index):
    """Not a boolean: a re-scrape and a model swap need different fixes."""
    stale = replace(index, fingerprint="something else entirely")
    reading = RelatedTopics(
        stale, corpus, embedding_model=index.embedding_model
    ).staleness.reading()
    assert reading["state"] == "stale"
    assert reading["changed"] == ["corpus"]
    assert reading["serving"] is False
    assert reading["index_fingerprint"] != reading["corpus_fingerprint"]


def test_the_reading_names_a_changed_model(corpus, index):
    reading = RelatedTopics(
        index, corpus, embedding_model="siglip:other@768"
    ).staleness.reading()
    assert reading["state"] == "stale"
    assert reading["changed"] == ["model"]
    # Edges still serve: nothing embeds at request time, so they describe the
    # Corpus as the build-time model saw it and stay internally consistent.
    assert reading["serving"] is True
    assert reading["running_model"] == "siglip:other@768"
    assert reading["index_model"] == index.embedding_model


def test_the_reading_names_both_when_both_moved(corpus, index):
    stale = replace(index, fingerprint="something else entirely")
    reading = RelatedTopics(
        stale, corpus, embedding_model="siglip:other@768"
    ).staleness.reading()
    assert reading["changed"] == ["corpus", "model"]


def test_an_absent_index_reads_absent_rather_than_stale(corpus):
    """Never built and gone out of date are different problems."""
    reading = RelatedTopics(None, corpus).staleness.reading()
    assert reading["state"] == "absent"
    assert reading["serving"] is False
    assert reading["built_at"] == ""


def test_a_changed_corpus_is_detected_by_content_not_by_timestamp(corpus, index, tmp_path):
    """Touching the file changes nothing; editing it changes everything."""
    path = tmp_path / "corpus-index.json"
    save(index, path)
    path.touch()
    assert RelatedTopics(load(path), corpus).staleness.state == "fresh"


# -- visibility must not re-enable serving -----------------------------------

def test_a_stale_index_still_serves_no_neighbours(corpus, index):
    """The two behaviours have to agree, or the reading is a lie about serving."""
    stale = replace(index, fingerprint="something else entirely")
    related = RelatedTopics(stale, corpus)
    assert related.staleness.reading()["serving"] is False
    assert related.available is False
    assert related.for_topic(sorted(index.related)[0]) == []


# -- on the console ----------------------------------------------------------

HDR = {"x-operator-token": "dev-operator-token"}


@pytest.fixture()
def console(tmp_path, corpus, monkeypatch):
    """An operator client wired to an index this test controls."""
    from fastapi.testclient import TestClient

    from interviewer.api import deps
    from interviewer.api.app import create_app

    path = tmp_path / "corpus-index.json"
    monkeypatch.setenv("CORPUS_INDEX_PATH", str(path))

    def wired(index=None):
        if index is not None:
            save(index, path)
        elif path.exists():
            path.unlink()
        deps.get_related_topics.cache_clear()
        return TestClient(create_app())

    yield wired
    deps.get_related_topics.cache_clear()


def test_the_console_reads_index_freshness(console, corpus):
    client = console(build(corpus, HashingEmbedder(), built_at=STAMP))
    body = client.get("/v1/operator/corpus-index", headers=HDR).json()
    assert body["state"] == "fresh"
    assert body["built_at"] == STAMP
    assert body["topic_count"] == 71
    assert body["rebuild_with"]


def test_the_console_names_what_changed(console, corpus):
    client = console(
        replace(build(corpus, HashingEmbedder()), fingerprint="moved on")
    )
    body = client.get("/v1/operator/corpus-index", headers=HDR).json()
    assert body["state"] == "stale"
    assert body["changed"] == ["corpus"]
    assert body["serving"] is False


def test_the_reading_is_authenticated_like_every_other_operator_reading(console, corpus):
    client = console(build(corpus, HashingEmbedder()))
    assert client.get("/v1/operator/corpus-index").status_code == 401
    assert client.get("/v1/operator/corpus-index", headers=HDR).status_code == 200


def test_a_stale_index_is_a_state_and_never_a_failure(console, corpus):
    """No route 500s and the Corpus stays fully examinable without neighbours."""
    client = console(
        replace(build(corpus, HashingEmbedder()), fingerprint="moved on")
    )
    assert client.get("/v1/operator/corpus-index", headers=HDR).status_code == 200
    assert client.get("/v1/corpus/tracks").status_code == 200
    assert client.get("/v1/corpus/modules").status_code == 200
    topic = sorted(t.id for t in corpus.topics)[0]
    related = client.get(f"/v1/corpus/topics/{topic}/related")
    assert related.status_code == 200
    assert related.json() == []


def test_an_absent_index_reads_absent_on_the_console(console):
    client = console(None)
    body = client.get("/v1/operator/corpus-index", headers=HDR).json()
    assert body["state"] == "absent"
    assert body["serving"] is False
