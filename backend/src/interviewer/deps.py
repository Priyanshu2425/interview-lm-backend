"""Process-wide singletons.

Every Corpus is somebody's and lives in the `content` schema (SPEC-0006). There
is no Corpus loaded from disk any more and no base to compose onto: what the API
serves is every shared Library plus the Libraries each Candidate uploaded, read
back out of Postgres. `CORPUS_PATH` is an import source for
`backend/scripts/import_corpus.py` and is not read here (ISSUE-0037).
"""

from __future__ import annotations

import logging
from functools import lru_cache

from interviewer.model.corpus_models import Corpus
from interviewer.service.corpus.loader_service import DossierLoader
from interviewer.service.corpus import CorpusService


log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_embedder():
    """The embedder this deployment runs. Chosen by flag, never by inference.

    Constructed but not warmed: loading weights is the lifespan's job, so that
    a process which never ingests never pays for them, and a process which does
    pays once, at boot, rather than inside a Candidate's first upload.
    """
    from interviewer.service.embeddings import make_embedder

    return make_embedder()


@lru_cache(maxsize=1)
def get_object_store():
    """Where figure bytes live. S3 where configured, local disk otherwise."""
    from interviewer.adapters.s3 import object_store

    return object_store()


@lru_cache(maxsize=1)
def get_probe_engine():
    """One connection, kept only to ask whether Postgres is answering.

    Deliberately not `wiring()` or `get_notebook_service()`: both apply DDL on
    first use, and a health check that can change the database it describes is
    not a health check. Deliberately not a fresh Engine per call either — that
    is a new connection to a suspended Neon every time somebody asks, which is
    the cost the question was supposed to avoid.

    `make_engine` already sets `pool_pre_ping` and a short `pool_recycle`, so a
    socket left dead by an autosuspend is retried here rather than reported as
    a database that has gone away.
    """
    from interviewer.db.engine import make_engine

    return make_engine(pool_size=1, max_overflow=0)


@lru_cache(maxsize=1)
def get_notebook_service():
    """Ingest is metered on the same ledger a Session is (ISSUE-0026)."""
    from interviewer.db.engine import create_content, create_core, make_engine
    from interviewer.service.embeddings import images_enabled
    from interviewer.service.metering.ledger import CreditLedger
    from interviewer.service.notebooks import NotebookService

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
    """Everything examinable: every Library this deployment stores.

    Empty where nothing has been imported or uploaded yet, which is a real
    deployment rather than a broken one — the first upload composes onto nothing
    exactly as the second composes onto something.
    """
    return get_notebook_service().served_corpus()


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
    from .wiring import built, wiring

    retain: set[str] = set()
    if built():
        w = wiring()
        retain = w.deps.visits.open_topic_ids()
        w.readings.rebind(corpus)
        w.reading.rebind(corpus)
    get_loader().rebind(corpus, retain=retain)
    get_corpus_service().rebind(corpus)
    # Neighbours are read from the same rows the Corpus was rebuilt from, so
    # they are re-read for the same reason and at the same moment.
    get_related_topics().clear()


@lru_cache(maxsize=1)
def get_related_topics():
    """Related Topics, answered from the centroids stored at ingest.

    No artifact, no fingerprint and no staleness: the vectors were written with
    the Topics they describe, so they cannot disagree with them. ADR-0018 built
    a precomputed file because the Corpus was a file; ADR-0021 records why that
    reason went away.
    """
    from interviewer.service.corpus.related_service import RelatedTopics

    return RelatedTopics(get_notebook_service().store)


@lru_cache(maxsize=1)
def get_loader() -> DossierLoader:
    return DossierLoader(get_corpus())


@lru_cache(maxsize=1)
def get_corpus_service() -> CorpusService:
    return CorpusService(get_corpus())
