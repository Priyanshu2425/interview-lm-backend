"""Async Notebook Service — high-level notebook operations."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .store import AsyncNotebookStore


class AsyncNotebookService:
    """Async version of NotebookService for API services."""

    def __init__(self, session: AsyncSession) -> None:
        self._store = AsyncNotebookStore(session)

    @property
    def store(self) -> AsyncNotebookStore:
        return self._store

    @property
    def model_name(self) -> str:
        """The embedding model a Library created now will be embedded with.

        Read from the deployment's own embedder rather than defaulted here. The
        name is stored on the Library and every chunk vector is read back against
        it; a record claiming a model that did not embed it makes a cosine between
        two spaces, which is a number with no meaning (ADR-0017).
        """
        from ...service.embeddings import make_embedder

        return getattr(make_embedder(), "model_name", "hashing-v1")

    async def create(
        self,
        notebook_id: str,
        candidate_id: str,
        title: str,
        *,
        visibility: str = "personal",
        provenance: dict | None = None,
    ):
        """Create a Library, embedding model included.

        The route calls this rather than reaching through to `store.create`: the
        model name is the service's to know, and a caller that has to remember to
        supply it is a caller that will eventually forget.
        """
        return await self._store.create(
            notebook_id,
            candidate_id,
            title,
            self.model_name,
            visibility=visibility,
            provenance=provenance,
        )

    async def corpus(self, notebook_id: str):
        """Rebuild one Library's Corpus from what was frozen at ingest.

        `corpus_view.corpus_for` is reused rather than reimplemented. It needs
        three readings and no connection, so they are awaited here and handed
        over as a record — the alternative was a second rebuild that would
        drift from this one Topic at a time.
        """
        from ...service.notebooks.corpus_view import corpus_for

        record = await self._store.get(notebook_id)
        if record is None:
            return None
        return corpus_for(await self._readings(notebook_id), record)

    async def all_corpora(self) -> list:
        out = []
        for notebook_id in await self._store.all_notebook_ids():
            corpus = await self.corpus(notebook_id)
            if corpus is not None:
                out.append(corpus)
        return out

    async def served_corpus(self):
        """Everything examinable, as one Corpus. Empty where nothing is stored."""
        from ...service.notebooks.corpus_view import merge

        return merge(await self.all_corpora())

    async def _readings(self, notebook_id: str) -> "_Readings":
        return _Readings(
            frozen=await self._store.frozen_topics(notebook_id),
            chunks=await self._store.chunks_of(notebook_id, modality="text"),
            orders=await self._store.topic_orders(notebook_id),
        )


class _Readings:
    """What `corpus_for` asks a store for, already read.

    Not a store. It answers the three calls a rebuild makes and nothing else,
    which is what lets one rebuild serve both the sync engine and an
    `AsyncSession` without either knowing about the other.
    """

    __slots__ = ("_frozen", "_chunks", "_orders")

    def __init__(self, *, frozen: dict, chunks: list[dict], orders: dict) -> None:
        self._frozen = frozen
        self._chunks = chunks
        self._orders = orders

    def frozen_topics(self, notebook_id: str) -> dict:
        return self._frozen

    def chunks_of(self, notebook_id: str, *, modality: str | None = None) -> list[dict]:
        return self._chunks

    def topic_orders(self, notebook_id: str) -> dict:
        return self._orders