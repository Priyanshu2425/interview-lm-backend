"""ISSUE-0029 — the shipped Corpus, embedded, without moving anything.

The dangerous half of this slice is not the embedding. It is that the Notebook
Adapter's pipeline *mints* `topic_id`s by clustering, and the shipped Corpus
arrives with 71 of them that are the join key for every row of Evidence and
Topic Confidence. A build that clustered would orphan the lot, quietly, and the
symptom would be months of Mastery attached to ids nothing references.

So the first tests here are about what the build refuses to do.
"""

from __future__ import annotations

import json
import math

import pytest

from interviewer.corpus.adapters.notebook import HashingEmbedder
from interviewer.corpus.index import (
    FORMAT_VERSION, MIN_SCORE, build, centre, fingerprint,
)
from interviewer.corpus.related import RelatedTopics, load, save


@pytest.fixture(scope="module")
def index(corpus):
    return build(corpus, HashingEmbedder())


# -- what the build must not do ---------------------------------------------

def test_every_topic_id_survives_exactly(corpus, index):
    """The load-bearing assertion of the whole slice."""
    assert set(index.centroids) == {topic.id for topic in corpus.topics}
    assert len(index.centroids) == 71


def test_the_build_never_reaches_the_clusterer_or_mints_an_id(corpus, monkeypatch):
    """Verified by call count, not by reading the code.

    Structure is given here, never derived: the Corpus already says what its
    Topics are, and anything that recomputed them would be answering a question
    nobody asked with an answer nothing could join to.
    """
    from interviewer.corpus.adapters import notebook

    def forbidden(*a, **kw):
        raise AssertionError("the Corpus build must not derive structure")

    monkeypatch.setattr(notebook.adapter, "topic_id_for", forbidden)
    monkeypatch.setattr(notebook.adapter, "cluster_chunks", forbidden)
    monkeypatch.setattr(notebook.clustering, "cluster_chunks", forbidden)
    build(corpus, HashingEmbedder())


def test_the_build_writes_no_corpus(corpus, index):
    """It produces vectors beside the Corpus, never a new one."""
    assert not hasattr(index, "corpus")
    assert set(index.related) <= set(index.centroids)


# -- the vectors -------------------------------------------------------------

def test_centroids_are_unit_vectors_of_the_deployment_width(index):
    from interviewer.corpus.adapters.notebook.embedding import DIM

    for vector in index.centroids.values():
        assert len(vector) == DIM
        assert sum(x * x for x in vector) == pytest.approx(1.0, abs=1e-6)


def test_the_mean_travels_with_the_index(index):
    """Centroids without the origin they were compared from are unusable."""
    assert len(index.mean) == len(next(iter(index.centroids.values())))


def test_centring_spreads_a_collapsed_space(index):
    """The measurement that made centring non-optional (see index.centre)."""
    ids = sorted(index.centroids)[:40]
    raw = [
        _cos(index.centroids[a], index.centroids[b])
        for i, a in enumerate(ids) for b in ids[i + 1:]
    ]
    centred = [
        _cos(centre(index.centroids[a], index.mean), centre(index.centroids[b], index.mean))
        for i, a in enumerate(ids) for b in ids[i + 1:]
    ]
    assert (max(centred) - min(centred)) > (max(raw) - min(raw))


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))


# -- the edges ---------------------------------------------------------------

def test_a_topic_is_never_its_own_neighbour(index):
    for topic_id, neighbours in index.related.items():
        assert topic_id not in {n.topic_id for n in neighbours}


def test_neighbours_are_capped_ranked_and_above_the_floor(index):
    for neighbours in index.related.values():
        assert len(neighbours) <= 5
        scores = [n.score for n in neighbours]
        assert scores == sorted(scores, reverse=True)
        assert all(score >= MIN_SCORE for score in scores)


def test_every_neighbour_carries_its_module_and_whether_it_is_the_same_one(
    corpus, index
):
    """Reported, never filtered: which to show is the surface's decision."""
    module_of = {t.id: m.id for m in corpus.modules for t in m.topics}
    for topic_id, neighbours in index.related.items():
        for n in neighbours:
            assert n.module_id == module_of[n.topic_id]
            assert n.same_module == (module_of[n.topic_id] == module_of[topic_id])


def test_a_topic_carrying_no_text_gets_no_centroid_rather_than_a_zero_vector(corpus):
    """Untested is not zero here either — absent is the honest answer."""
    from interviewer.corpus.contract import Corpus, Leaf, LeafKind, Module, Topic, Track

    # The contract requires a Topic to hold at least one leaf, so "no text"
    # means a leaf carrying none — a Topic of pure references, which the shipped
    # Corpus really does contain.
    empty = Topic(
        id="t-empty", order=1, title="Nothing",
        leaves=(
            Leaf(id="l-empty", order=1, title="A link", kind=LeafKind.REFERENCE,
                 text=None, source_ref="https://example.test/x"),
        ),
    )
    stripped = Corpus(
        provenance=corpus.provenance,
        tracks=(Track(key="k", title="T", modules=(
            Module(id="m", order=1, title="M", description="", topics=(empty,)),
        )),),
    )
    built = build(stripped, HashingEmbedder())
    assert built.centroids == {}
    assert built.related == {}


# -- determinism and the fingerprint ----------------------------------------

def test_two_builds_of_one_corpus_are_identical(corpus, tmp_path):
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    save(build(corpus, HashingEmbedder()), first)
    save(build(corpus, HashingEmbedder()), second)
    assert first.read_bytes() == second.read_bytes()


def test_the_fingerprint_follows_content_not_timestamps(corpus):
    """Re-scraping and getting the same material back is not a change."""
    from interviewer.corpus.contract import CorpusProvenance, Corpus

    restamped = Corpus(
        provenance=CorpusProvenance(
            source=corpus.provenance.source,
            extracted_at="2099-01-01T00:00:00Z",
            adapter=corpus.provenance.adapter,
            adapter_version=corpus.provenance.adapter_version,
        ),
        tracks=corpus.tracks,
    )
    assert fingerprint(restamped) == fingerprint(corpus)


def test_changing_a_word_changes_the_fingerprint(corpus):
    from interviewer.corpus.contract import Corpus, Leaf, Module, Topic, Track

    topic = next(t for t in corpus.topics if any(leaf.text for leaf in t.leaves))
    leaf = next(leaf for leaf in topic.leaves if leaf.text)
    edited = Topic(
        id=topic.id, order=topic.order, title=topic.title,
        leaves=tuple(
            Leaf(
                id=x.id, order=x.order, title=x.title, kind=x.kind,
                text=(x.text or "") + " one more sentence." if x.id == leaf.id else x.text,
                source_ref=x.source_ref, answers_leaf_id=x.answers_leaf_id,
            )
            for x in topic.leaves
        ),
    )
    changed = Corpus(
        provenance=corpus.provenance,
        tracks=(Track(key="k", title="T", modules=(
            Module(id="m", order=1, title="M", description="", topics=(edited,)),
        )),),
    )
    assert fingerprint(changed) != fingerprint(corpus)


# -- the artifact round trip -------------------------------------------------

def test_the_artifact_round_trips(index, tmp_path):
    path = tmp_path / "corpus-index.json"
    save(index, path)
    back = load(path)
    assert back.fingerprint == index.fingerprint
    assert back.embedding_model == index.embedding_model
    assert set(back.related) == set(index.related)
    assert back.format_version == FORMAT_VERSION


def test_the_artifact_is_readable_json(index, tmp_path):
    """It ships in the repository and is reviewed in a diff."""
    path = tmp_path / "corpus-index.json"
    save(index, path)
    body = json.loads(path.read_text())
    assert body["topic_count"] == 71
    assert "fingerprint" in body and "embedding_model" in body


# -- fail closed -------------------------------------------------------------

def test_no_index_serves_no_neighbours(corpus):
    related = RelatedTopics(None, corpus)
    assert related.available is False
    assert related.for_topic(next(iter(corpus.topics)).id) == []
    assert related.staleness.reason == "no index has been built"


def test_a_missing_file_is_not_an_error(tmp_path, corpus):
    assert load(tmp_path / "absent.json") is None
    assert RelatedTopics(load(tmp_path / "absent.json"), corpus).for_topic("x") == []


def test_a_corpus_that_has_moved_on_serves_nothing(corpus, index, tmp_path):
    """A wrong neighbour is a claim about the material nobody can trace."""
    from dataclasses import replace

    stale = replace(index, fingerprint="something else entirely")
    related = RelatedTopics(stale, corpus)
    assert related.available is False
    assert related.for_topic(sorted(index.related)[0]) == []
    assert "Corpus has changed" in related.staleness.reason


def test_an_index_from_another_model_still_serves_its_edges(corpus, index):
    """Precomputed edges do not care what the deployment is running.

    Nothing embeds at request time, so the neighbours describe the Corpus as the
    build-time model saw it and stay internally consistent. Gating on the model
    would mean the shipped artifact — built with the real encoder — served
    nothing on a deployment running the lexical stand-in, which is the default.

    The mismatch is still reported, because comparing a *new* vector against
    these centroids does require the same space.
    """
    related = RelatedTopics(index, corpus, embedding_model="siglip:other@768")
    assert related.available is True
    assert related.for_topic(sorted(index.related)[0]) != []
    assert related.staleness.model_changed is True
    assert "embedding model has changed" in related.staleness.reason


def test_a_matching_index_serves(corpus, index):
    related = RelatedTopics(index, corpus, embedding_model=index.embedding_model)
    assert related.available is True
    assert related.staleness.fresh is True
    assert len(related.for_topic(sorted(index.related)[0])) == 5


def test_a_malformed_artifact_reads_as_absent(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ this is not json")
    assert load(path) is None


def test_an_artifact_from_a_future_format_is_refused(index, tmp_path):
    """A reader that cannot parse it must not guess at it."""
    from dataclasses import replace

    path = tmp_path / "future.json"
    save(replace(index, format_version=FORMAT_VERSION + 1), path)
    assert load(path) is None


# -- the shared chunker ------------------------------------------------------

def test_both_corpora_are_cut_by_the_same_chunker():
    from interviewer.corpus import chunking as shared
    from interviewer.corpus.adapters.notebook import chunking as notebook

    assert notebook.Chunk is shared.Chunk
    assert notebook.chunk_source.func is shared.chunk_source


def test_the_ground_truth_rule_is_injected_rather_than_known():
    """ADR-0007: what is source-specific stays in the Adapter that owns it."""
    import ast
    import inspect

    from interviewer.corpus import chunking as shared

    tree = ast.parse(inspect.getsource(shared))
    imported = {
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.Import) for alias in node.names
    }
    # Comments may name the domain freely; an import is the coupling.
    assert not any("mining" in name for name in imported), imported
    assert not any("adapters" in name for name in imported), imported


def test_the_notebook_adapter_still_applies_its_own_boundary():
    from interviewer.corpus.adapters.notebook.chunking import answer_boundary

    assert answer_boundary("## Answer Key\n\nthe worked solution", 0, 40) is True
    assert answer_boundary("ordinary prose about attention", 0, 30) is False
