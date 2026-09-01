"""Async Services container for graph adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from interviewer.repository.async_repositories import (
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
)


@dataclass
class AsyncServices:
    """Container for all async services used by graph adapters."""

    # Database session (passed per-request or created per-call)
    _session: AsyncSession = field(repr=False, default=None)

    # Repositories (lazy initialized)
    _sessions: AsyncSessionStore | None = field(default=None, repr=False)
    _visits: AsyncVisitLifecycle | None = field(default=None, repr=False)
    _evidence: AsyncEvidenceLedger | None = field(default=None, repr=False)
    _confidence: AsyncConfidenceStore | None = field(default=None, repr=False)
    _bindings: AsyncBindingStore | None = field(default=None, repr=False)
    _credits: AsyncCreditLedger | None = field(default=None, repr=False)
    _pool: AsyncPoolLedger | None = field(default=None, repr=False)
    _keyvault: AsyncKeyVault | None = field(default=None, repr=False)
    _notebooks: AsyncNotebookStore | None = field(default=None, repr=False)
    _notebook_service: AsyncNotebookService | None = field(default=None, repr=False)
    _dossier_loader: AsyncDossierLoader | None = field(default=None, repr=False)
    _corpus: AsyncCorpusService | None = field(default=None, repr=False)
    _related: AsyncRelatedTopics | None = field(default=None, repr=False)

    def bind_session(self, session: AsyncSession) -> None:
        """Bind a database session and initialize all repositories."""
        self._session = session
        self._sessions = AsyncSessionStore(session)
        self._visits = AsyncVisitLifecycle(session)
        self._evidence = AsyncEvidenceLedger(session)
        self._confidence = AsyncConfidenceStore(session)
        self._bindings = AsyncBindingStore(session)
        self._credits = AsyncCreditLedger(session)
        self._pool = AsyncPoolLedger(session)
        self._keyvault = AsyncKeyVault(session)
        self._notebooks = AsyncNotebookStore(session)
        self._notebook_service = AsyncNotebookService(session)
        # These don't need a session - they use the corpus
        # _dossier_loader, _corpus, _related set externally

    @property
    def sessions(self) -> AsyncSessionStore:
        if self._sessions is None:
            raise RuntimeError("Session not bound - call bind_session() first")
        return self._sessions

    @property
    def visits(self) -> AsyncVisitLifecycle:
        if self._visits is None:
            raise RuntimeError("Session not bound - call bind_session() first")
        return self._visits

    @property
    def evidence(self) -> AsyncEvidenceLedger:
        if self._evidence is None:
            raise RuntimeError("Session not bound - call bind_session() first")
        return self._evidence

    @property
    def confidence(self) -> AsyncConfidenceStore:
        if self._confidence is None:
            raise RuntimeError("Session not bound - call bind_session() first")
        return self._confidence

    @property
    def bindings(self) -> AsyncBindingStore:
        if self._bindings is None:
            raise RuntimeError("Session not bound - call bind_session() first")
        return self._bindings

    @property
    def credits(self) -> AsyncCreditLedger:
        if self._credits is None:
            raise RuntimeError("Session not bound - call bind_session() first")
        return self._credits

    @property
    def pool(self) -> AsyncPoolLedger:
        if self._pool is None:
            raise RuntimeError("Session not bound - call bind_session() first")
        return self._pool

    @property
    def keyvault(self) -> AsyncKeyVault:
        if self._keyvault is None:
            raise RuntimeError("Session not bound - call bind_session() first")
        return self._keyvault

    @property
    def notebooks(self) -> AsyncNotebookStore:
        if self._notebooks is None:
            raise RuntimeError("Session not bound - call bind_session() first")
        return self._notebooks

    @property
    def notebook_service(self) -> AsyncNotebookService:
        if self._notebook_service is None:
            raise RuntimeError("Session not bound - call bind_session() first")
        return self._notebook_service

    @property
    def dossier_loader(self) -> AsyncDossierLoader:
        if self._dossier_loader is None:
            raise RuntimeError("Dossier loader not set - call set_corpus() first")
        return self._dossier_loader

    @property
    def corpus(self) -> AsyncCorpusService:
        if self._corpus is None:
            raise RuntimeError("Corpus not set - call set_corpus() first")
        return self._corpus

    @property
    def related(self) -> AsyncRelatedTopics:
        if self._related is None:
            raise RuntimeError("Related topics not set - call set_corpus() first")
        return self._related

    def set_corpus(self, corpus: Any) -> None:
        """Set corpus-dependent services."""
        from ...model.corpus import Corpus
        self._dossier_loader = AsyncDossierLoader(corpus)
        self._corpus = AsyncCorpusService(corpus)
        self._related = AsyncRelatedTopics(self._notebooks)