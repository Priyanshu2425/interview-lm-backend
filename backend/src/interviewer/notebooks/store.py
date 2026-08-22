"""Persistence for notebook material. Everything here lives in `content`.

One rule shapes the module: nothing it writes is permanent. Deleting a notebook
must be able to empty every table this store touches without reaching a single
row of Evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from interviewer.corpus.adapters.notebook import (
    Chunk, FrozenTopic, Ingested, Notebook, Source,
)
from interviewer.db.content import (
    notebook as notebook_t, notebook_chunk, notebook_source, notebook_topic,
)
from interviewer.db.schema import corpus_version


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    module_id: str
    title: str
    order: int
    state: str
    stub_reason: str | None
    media_type: str = "text/markdown"


@dataclass(frozen=True, slots=True)
class NotebookRecord:
    notebook_id: str
    candidate_id: str
    title: str
    embedding_model: str
    sources: tuple[SourceRecord, ...]


class NotebookStore:
    """Reads and writes notebook material. Owns no interview state."""

    __slots__ = ("_engine",)

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- notebooks -----------------------------------------------------------

    def create(
        self, notebook_id: str, candidate_id: str, title: str, embedding_model: str
    ) -> NotebookRecord:
        with self._engine.begin() as c:
            c.execute(
                sa.insert(notebook_t).values(
                    notebook_id=notebook_id,
                    candidate_id=candidate_id,
                    title=title,
                    embedding_model=embedding_model,
                )
            )
        return NotebookRecord(notebook_id, candidate_id, title, embedding_model, ())

    def get(self, notebook_id: str) -> NotebookRecord | None:
        with self._engine.begin() as c:
            row = c.execute(
                sa.select(notebook_t).where(notebook_t.c.notebook_id == notebook_id)
            ).mappings().first()
            if row is None:
                return None
            return NotebookRecord(
                notebook_id=row["notebook_id"],
                candidate_id=row["candidate_id"],
                title=row["title"],
                embedding_model=row["embedding_model"],
                sources=self._sources(c, notebook_id),
            )

    def for_candidate(self, candidate_id: str) -> list[NotebookRecord]:
        with self._engine.begin() as c:
            rows = c.execute(
                sa.select(notebook_t)
                .where(notebook_t.c.candidate_id == candidate_id)
                .order_by(notebook_t.c.created_at, notebook_t.c.notebook_id)
            ).mappings().all()
            return [
                NotebookRecord(
                    notebook_id=r["notebook_id"],
                    candidate_id=r["candidate_id"],
                    title=r["title"],
                    embedding_model=r["embedding_model"],
                    sources=self._sources(c, r["notebook_id"]),
                )
                for r in rows
            ]

    def all_notebook_ids(self) -> list[str]:
        with self._engine.begin() as c:
            return [
                r[0] for r in c.execute(
                    sa.select(notebook_t.c.notebook_id).order_by(
                        notebook_t.c.created_at, notebook_t.c.notebook_id
                    )
                )
            ]

    def owner_of(self, notebook_id: str) -> str | None:
        with self._engine.begin() as c:
            return c.execute(
                sa.select(notebook_t.c.candidate_id).where(
                    notebook_t.c.notebook_id == notebook_id
                )
            ).scalar_one_or_none()

    @staticmethod
    def _sources(c, notebook_id: str) -> tuple[SourceRecord, ...]:
        rows = c.execute(
            sa.select(notebook_source)
            .where(notebook_source.c.notebook_id == notebook_id)
            .order_by(notebook_source.c.source_order)
        ).mappings().all()
        return tuple(
            SourceRecord(
                source_id=r["source_id"],
                module_id=r["module_id"],
                title=r["title"],
                order=r["source_order"],
                state=r["state"],
                stub_reason=r["stub_reason"],
                media_type=r["media_type"],
            )
            for r in rows
        )

    # -- sources -------------------------------------------------------------

    def source_by_hash(self, notebook_id: str, content_hash: str) -> str | None:
        """Deduplication. The same file uploaded twice is not a second Module."""
        with self._engine.begin() as c:
            return c.execute(
                sa.select(notebook_source.c.source_id).where(
                    notebook_source.c.notebook_id == notebook_id,
                    notebook_source.c.content_hash == content_hash,
                )
            ).scalar_one_or_none()

    def next_source_order(self, notebook_id: str) -> int:
        with self._engine.begin() as c:
            highest = c.execute(
                sa.select(sa.func.max(notebook_source.c.source_order)).where(
                    notebook_source.c.notebook_id == notebook_id
                )
            ).scalar()
        return (highest or 0) + 1

    def sources_of(self, notebook_id: str) -> list[Source]:
        """The Sources as the Adapter takes them, in upload order."""
        with self._engine.begin() as c:
            rows = c.execute(
                sa.select(notebook_source)
                .where(notebook_source.c.notebook_id == notebook_id)
                .order_by(notebook_source.c.source_order)
            ).mappings().all()
        return [
            Source(
                source_id=r["source_id"],
                title=r["title"],
                text=r["text"],
                media_type=r["media_type"],
                stub_reason=r["stub_reason"],
            )
            for r in rows
        ]

    def notebook_for_adapter(self, notebook_id: str) -> Notebook | None:
        record = self.get(notebook_id)
        if record is None:
            return None
        return Notebook(
            notebook_id=notebook_id,
            title=record.title,
            sources=tuple(self.sources_of(notebook_id)),
        )

    # -- one ingest, written whole ------------------------------------------

    def save_source_ingest(
        self,
        *,
        notebook_id: str,
        source: Source,
        module_id: str,
        order: int,
        content_hash: str,
        chunks: list[Chunk],
        frozen: dict[str, FrozenTopic],
        topic_orders: dict[str, int],
        topic_tokens: dict[str, int],
        embedding_model: str = "",
    ) -> None:
        """Atomic per Source (ISSUE-0026): a Module appears whole or not at all."""
        with self._engine.begin() as c:
            c.execute(
                sa.insert(notebook_source).values(
                    source_id=source.source_id,
                    notebook_id=notebook_id,
                    module_id=module_id,
                    title=source.title,
                    media_type=source.media_type,
                    source_order=order,
                    text=source.text,
                    content_hash=content_hash,
                    state="stub" if source.is_stub else "ready",
                    stub_reason=source.stub_reason,
                )
            )
            if frozen:
                c.execute(
                    sa.insert(notebook_topic),
                    [
                        {
                            "topic_id": t.topic_id,
                            "notebook_id": notebook_id,
                            "source_id": t.source_id,
                            "module_id": t.module_id,
                            "title": t.title,
                            "topic_order": topic_orders[t.topic_id],
                            "centroid": list(t.centroid),
                            "chunk_hashes": list(t.chunk_hashes),
                            "dossier_tokens": topic_tokens.get(t.topic_id, 0),
                        }
                        for t in frozen.values()
                    ],
                )
            if chunks:
                c.execute(
                    sa.insert(notebook_chunk),
                    [
                        {
                            "chunk_id": ch.chunk_id,
                            "notebook_id": notebook_id,
                            "source_id": ch.source_id,
                            "topic_id": ch.topic_id,
                            "page": ch.page,
                            "char_start": ch.char_start,
                            "char_end": ch.char_end,
                            "anchor": ch.anchor,
                            "text": ch.text,
                            "content_hash": ch.content_hash,
                            "embedding": list(ch.embedding),
                            "embedding_model": embedding_model or "",
                            "modality": ch.modality,
                            "object_key": ch.object_key,
                            "leaf_kind": ch.leaf_kind,
                            "answers_chunk_id": ch.answers_chunk_id,
                        }
                        for ch in chunks
                    ],
                )

    def frozen_topics(self, notebook_id: str) -> dict[str, FrozenTopic]:
        with self._engine.begin() as c:
            rows = c.execute(
                sa.select(notebook_topic).where(
                    notebook_topic.c.notebook_id == notebook_id
                ).order_by(notebook_topic.c.topic_order)
            ).mappings().all()
        return {
            r["topic_id"]: FrozenTopic(
                topic_id=r["topic_id"],
                module_id=r["module_id"],
                source_id=r["source_id"],
                title=r["title"],
                centroid=tuple(r["centroid"]),
                chunk_hashes=tuple(r["chunk_hashes"]),
            )
            for r in rows
        }

    def chunks_of(
        self, notebook_id: str, *, modality: str | None = None
    ) -> list[dict]:
        """Stored chunks, in locator order.

        `modality` matters more than it looks: everything that rebuilds prose —
        a dossier, a Leaf, a token budget — must ask for text, because a figure
        row carries no characters and would silently corrupt a concatenation
        that is required to be byte-identical to the source (ADR-0017).
        """
        query = (
            sa.select(notebook_chunk)
            .where(notebook_chunk.c.notebook_id == notebook_id)
            .order_by(notebook_chunk.c.source_id, notebook_chunk.c.char_start)
        )
        if modality is not None:
            query = query.where(notebook_chunk.c.modality == modality)
        with self._engine.begin() as c:
            return [dict(r) for r in c.execute(query).mappings()]

    def embeddings_by_hash(
        self, notebook_id: str, *, embedding_model: str | None = None
    ) -> dict[str, tuple[float, ...]]:
        """What has already been embedded, so it is never embedded again.

        Keyed by content hash **and** by the model that produced it. Content
        alone was enough while there was one embedder; with a swappable one it
        is a defect — change the model, add a source, and every chunk the
        notebook had seen before comes back as a vector from a space it has
        since left, mixing two geometries inside one notebook with nothing
        anywhere reporting a problem. Filtering means a model change simply
        re-embeds, which is what a resumed ingest should do anyway.
        """
        query = sa.select(
            notebook_chunk.c.content_hash, notebook_chunk.c.embedding
        ).where(notebook_chunk.c.notebook_id == notebook_id)
        if embedding_model is not None:
            query = query.where(notebook_chunk.c.embedding_model == embedding_model)
        with self._engine.begin() as c:
            rows = c.execute(query).all()
        return {h: tuple(v) for h, v in rows}

    def figures_of(self, notebook_id: str) -> list[dict]:
        """The image chunks, for re-embedding and for citation."""
        return self.chunks_of(notebook_id, modality="image")

    def object_keys_of(self, notebook_id: str) -> list[str]:
        with self._engine.begin() as c:
            return [
                r[0] for r in c.execute(
                    sa.select(notebook_chunk.c.object_key).where(
                        notebook_chunk.c.notebook_id == notebook_id,
                        notebook_chunk.c.object_key.is_not(None),
                    )
                )
            ]

    def chunk_hashes(self, notebook_id: str) -> set[str]:
        with self._engine.begin() as c:
            return {
                r[0] for r in c.execute(
                    sa.select(notebook_chunk.c.content_hash).where(
                        notebook_chunk.c.notebook_id == notebook_id
                    )
                )
            }

    # -- re-ingest -----------------------------------------------------------

    def replace_source_material(
        self,
        *,
        notebook_id: str,
        source_id: str,
        text: str,
        content_hash: str,
        chunks: list[Chunk],
        frozen: dict[str, FrozenTopic],
        topic_orders: dict[str, int],
        topic_tokens: dict[str, int],
        embedding_model: str | None = None,
    ) -> None:
        """Swap a Source's material for a newer version, in one transaction.

        Frozen Topics are rewritten in place — same id, same centroid — so a
        Topic that survived a re-ingest is the same Topic to everything keyed on
        it. Only membership and dossier size move.
        """
        with self._engine.begin() as c:
            c.execute(
                sa.delete(notebook_chunk).where(
                    notebook_chunk.c.source_id == source_id
                )
            )
            c.execute(
                sa.delete(notebook_topic).where(
                    notebook_topic.c.source_id == source_id
                )
            )
            c.execute(
                sa.update(notebook_source)
                .where(notebook_source.c.source_id == source_id)
                .values(text=text, content_hash=content_hash)
            )
            if embedding_model is not None:
                c.execute(
                    sa.update(notebook_t)
                    .where(notebook_t.c.notebook_id == notebook_id)
                    .values(embedding_model=embedding_model)
                )
            if frozen:
                c.execute(
                    sa.insert(notebook_topic),
                    [
                        {
                            "topic_id": t.topic_id,
                            "notebook_id": notebook_id,
                            "source_id": t.source_id,
                            "module_id": t.module_id,
                            "title": t.title,
                            "topic_order": topic_orders[t.topic_id],
                            "centroid": list(t.centroid),
                            "chunk_hashes": list(t.chunk_hashes),
                            "dossier_tokens": topic_tokens.get(t.topic_id, 0),
                        }
                        for t in frozen.values()
                    ],
                )
            if chunks:
                c.execute(
                    sa.insert(notebook_chunk),
                    [
                        {
                            "chunk_id": ch.chunk_id,
                            "notebook_id": notebook_id,
                            "source_id": ch.source_id,
                            "topic_id": ch.topic_id,
                            "page": ch.page,
                            "char_start": ch.char_start,
                            "char_end": ch.char_end,
                            "anchor": ch.anchor,
                            "text": ch.text,
                            "content_hash": ch.content_hash,
                            "embedding": list(ch.embedding),
                            "embedding_model": embedding_model or "",
                            "modality": ch.modality,
                            "object_key": ch.object_key,
                            "leaf_kind": ch.leaf_kind,
                            "answers_chunk_id": ch.answers_chunk_id,
                        }
                        for ch in chunks
                    ],
                )

    # -- the permanent record of a change ------------------------------------

    def record_version(
        self,
        *,
        notebook_id: str,
        source_id: str,
        reason: str,
        surviving: list[str],
        new: list[str],
        vanished: list[str],
        note: str = "",
    ) -> None:
        """Written to `core`, not `content`. It outlives the notebook."""
        with self._engine.begin() as c:
            c.execute(
                sa.insert(corpus_version).values(
                    notebook_id=notebook_id,
                    source_id=source_id,
                    reason=reason,
                    surviving_topic_ids=surviving,
                    new_topic_ids=new,
                    vanished_topic_ids=vanished,
                    note=note,
                )
            )

    def versions(self, notebook_id: str) -> list[dict]:
        with self._engine.begin() as c:
            return [
                dict(r) for r in c.execute(
                    sa.select(corpus_version)
                    .where(corpus_version.c.notebook_id == notebook_id)
                    .order_by(corpus_version.c.event_id)
                ).mappings()
            ]

    def re_embed(
        self,
        *,
        notebook_id: str,
        chunk_vectors: dict[str, tuple[float, ...]],
        centroids: dict[str, tuple[float, ...]],
        embedding_model: str,
    ) -> None:
        """New vectors, same memberships. Nothing here moves a chunk."""
        with self._engine.begin() as c:
            for chunk_id, vector in chunk_vectors.items():
                c.execute(
                    sa.update(notebook_chunk)
                    .where(notebook_chunk.c.chunk_id == chunk_id)
                    .values(embedding=list(vector))
                )
            for topic_id, centroid in centroids.items():
                c.execute(
                    sa.update(notebook_topic)
                    .where(notebook_topic.c.topic_id == topic_id)
                    .values(centroid=list(centroid))
                )
            c.execute(
                sa.update(notebook_t)
                .where(notebook_t.c.notebook_id == notebook_id)
                .values(embedding_model=embedding_model)
            )

    def delete_source(self, source_id: str) -> None:
        with self._engine.begin() as c:
            c.execute(
                sa.delete(notebook_chunk).where(
                    notebook_chunk.c.source_id == source_id
                )
            )
            c.execute(
                sa.delete(notebook_topic).where(
                    notebook_topic.c.source_id == source_id
                )
            )
            c.execute(
                sa.delete(notebook_source).where(
                    notebook_source.c.source_id == source_id
                )
            )

    def delete_notebook(self, notebook_id: str, *, objects=None) -> None:
        """Content only. Nothing here can reach `core`.

        The rows go first and the objects after, because the ordering decides
        what a crash leaves behind: rows without objects would be citations
        pointing at nothing, while objects without rows are unreferenced bytes
        that a reconciliation sweep can find and remove. One is a broken
        product, the other is a bill.
        """
        with self._engine.begin() as c:
            for table in (notebook_chunk, notebook_topic, notebook_source):
                c.execute(sa.delete(table).where(table.c.notebook_id == notebook_id))
            c.execute(
                sa.delete(notebook_t).where(notebook_t.c.notebook_id == notebook_id)
            )
        if objects is not None:
            # CASCADE empties the schema; it has never heard of the bucket.
            objects.delete_prefix(notebook_id)
