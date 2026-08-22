"""Process-wide singletons.

The Cortex Corpus ships with the image (ADR-0005). A notebook Corpus does not —
it belongs to a Candidate, lives in the `content` schema, and is composed onto
the served Corpus at read time so that one picker can show both.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from interviewer.corpus.adapters.cortex import ingest
from interviewer.corpus.compose import compose
from interviewer.corpus.contract import Corpus
from interviewer.corpus.loader import DossierLoader
from interviewer.corpus.service import CorpusService


def corpus_path() -> Path:
    env = os.environ.get("CORPUS_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[4] / "data" / "corpus.json"


@lru_cache(maxsize=1)
def get_base_corpus() -> Corpus:
    """The Corpus that shipped. One scrape, read once, never written."""
    return ingest(corpus_path())


@lru_cache(maxsize=1)
def get_embedder():
    """The embedder this deployment runs. Chosen by flag, never by inference.

    Constructed but not warmed: loading weights is the lifespan's job, so that
    a process which never ingests never pays for them, and a process which does
    pays once, at boot, rather than inside a Candidate's first upload.
    """
    from interviewer.embeddings import make_embedder

    return make_embedder()


@lru_cache(maxsize=1)
def get_object_store():
    """Where figure bytes live. S3 where configured, local disk otherwise."""
    from interviewer.embeddings.artifacts import object_store

    return object_store()


@lru_cache(maxsize=1)
def get_notebook_service():
    """Ingest is metered on the same ledger a Session is (ISSUE-0026)."""
    from interviewer.db.engine import create_content, create_core, make_engine
    from interviewer.embeddings import images_enabled
    from interviewer.metering.ledger import CreditLedger
    from interviewer.notebooks import NotebookService

    engine = make_engine()
    create_core(engine)
    create_content(engine)
    embedder = get_embedder()
    _assert_width_matches(engine, embedder)
    return NotebookService(
        engine,
        embedder=embedder,
        credits=CreditLedger(engine),
        objects=get_object_store(),
        images=images_enabled(),
    )


def _assert_width_matches(engine, embedder) -> None:
    """Refuse to start rather than write a second geometry into one column.

    A mismatch is survivable and fixable — `re_embed` exists for exactly this —
    but only while it is still visible. Written first and noticed later, it is
    a set of Topics whose boundaries nobody can explain.
    """
    import sqlalchemy as sa

    from interviewer.db.content import CONTENT, EMBEDDING_DIM
    from interviewer.db.engine import DimensionMismatch

    width = getattr(embedder, "dim", EMBEDDING_DIM)
    if width == EMBEDDING_DIM:
        return
    raise DimensionMismatch(
        f"{getattr(embedder, 'model_name', embedder)} emits {width} dimensions "
        f"and {CONTENT}.notebook_chunk.embedding is vector({EMBEDDING_DIM}). "
        "Re-embed the notebooks and widen the column together, or select an "
        "embedder of the stored width."
    )


@lru_cache(maxsize=1)
def get_corpus() -> Corpus:
    """Everything examinable: the shipped Corpus plus every notebook."""
    return compose(get_base_corpus(), *get_notebook_service().all_corpora())


def refresh_corpus() -> None:
    """Re-read after an ingest or a deletion.

    The composed Corpus is rebuilt outright rather than patched — a
    partially-updated Corpus is the failure this product least wants — but it is
    then **swapped into** the existing loader and services rather than replacing
    them. Rebuilding the object graph would take the checkpointer with it, and
    every Session parked mid-Visit would lose the state it is parked on.
    """
    get_corpus.cache_clear()
    corpus = get_corpus()
    from .wiring import wiring

    retain: set[str] = set()
    if wiring.cache_info().currsize:
        w = wiring()
        retain = w.deps.visits.open_topic_ids()
        w.summary.rebind(corpus)
    get_loader().rebind(corpus, retain=retain)
    get_corpus_service().rebind(corpus)


def corpus_index_path() -> Path:
    env = os.environ.get("CORPUS_INDEX_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[4] / "data" / "corpus-index.json"


@lru_cache(maxsize=1)
def get_related_topics():
    """Related Topics, or nothing at all.

    Checked against the **base** Corpus rather than the composed one: the
    artifact was built from what shipped, and a Candidate adding a notebook does
    not make it stale. Notebook Topics simply have no neighbours, which is true.
    """
    from interviewer.corpus.related import RelatedTopics, load

    model = None
    try:
        model = get_embedder().model_name
    except Exception:
        # An embedder that cannot even be constructed is a reason to stop
        # serving neighbours, not a reason to fail: this is a reading of the
        # material and the Corpus is fully examinable without it.
        pass
    return RelatedTopics(
        load(corpus_index_path()), get_base_corpus(), embedding_model=model
    )


@lru_cache(maxsize=1)
def get_loader() -> DossierLoader:
    return DossierLoader(get_corpus())


@lru_cache(maxsize=1)
def get_corpus_service() -> CorpusService:
    return CorpusService(get_corpus())
