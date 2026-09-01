"""Async dependencies for FastAPI routes."""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .db.engine_async import get_async_db
from .deps import get_corpus, get_corpus_service, get_loader, get_related_topics
from .repository.async_repositories import (
    AsyncSessionStore,
    AsyncVisitLifecycle,
    AsyncEvidenceLedger,
    AsyncConfidenceStore,
    AsyncBindingStore,
    AsyncCreditLedger,
    AsyncPoolLedger,
    AsyncKeyVault,
    AsyncNotebookStore,
    AsyncNotebookService,
    AsyncDossierLoader,
    AsyncCorpusService,
    AsyncRelatedTopics,
    AsyncCorpus,
)


async def get_async_session_store(
    db: AsyncSession = Depends(get_async_db),
) -> AsyncGenerator[AsyncSessionStore, None]:
    yield AsyncSessionStore(db)


async def get_async_visit_lifecycle(
    db: AsyncSession = Depends(get_async_db),
) -> AsyncGenerator[AsyncVisitLifecycle, None]:
    yield AsyncVisitLifecycle(db)


async def get_async_evidence_ledger(
    db: AsyncSession = Depends(get_async_db),
) -> AsyncGenerator[AsyncEvidenceLedger, None]:
    yield AsyncEvidenceLedger(db)


async def get_async_confidence_store(
    db: AsyncSession = Depends(get_async_db),
) -> AsyncGenerator[AsyncConfidenceStore, None]:
    yield AsyncConfidenceStore(db)


async def get_async_binding_store(
    db: AsyncSession = Depends(get_async_db),
) -> AsyncGenerator[AsyncBindingStore, None]:
    yield AsyncBindingStore(db)


async def get_async_credit_ledger(
    db: AsyncSession = Depends(get_async_db),
) -> AsyncGenerator[AsyncCreditLedger, None]:
    yield AsyncCreditLedger(db)


async def get_async_pool_ledger(
    db: AsyncSession = Depends(get_async_db),
) -> AsyncGenerator[AsyncPoolLedger, None]:
    yield AsyncPoolLedger(db)


async def get_async_key_vault(
    db: AsyncSession = Depends(get_async_db),
) -> AsyncGenerator[AsyncKeyVault, None]:
    yield AsyncKeyVault(db)


async def get_async_notebook_store(
    db: AsyncSession = Depends(get_async_db),
) -> AsyncGenerator[AsyncNotebookStore, None]:
    yield AsyncNotebookStore(db)


async def get_async_notebook_service(
    db: AsyncSession = Depends(get_async_db),
) -> AsyncGenerator[AsyncNotebookService, None]:
    yield AsyncNotebookService(db)


async def get_async_dossier_loader() -> AsyncGenerator[AsyncDossierLoader, None]:
    """The composed Corpus, read from the one place that rebuilds it.

    Not `app.state`: a mirror there would have to be restamped by every path
    that can change the Corpus, and the test suite builds an app per client
    without running lifespan, so the mirror would be empty exactly where the
    singleton is correct. `refresh_corpus` clears the cache this reads.
    """
    yield get_loader()


# Alias for backward compatibility
get_async_loader = get_async_dossier_loader


async def get_async_corpus_service() -> AsyncGenerator[AsyncCorpusService, None]:
    yield get_corpus_service()


async def get_async_related_topics() -> AsyncGenerator[AsyncRelatedTopics, None]:
    yield get_related_topics()


async def get_async_corpus() -> AsyncGenerator[AsyncCorpus, None]:
    yield get_corpus()