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
    Chunk,
    FrozenTopic,
    Ingested,
    Notebook,
    Source,
)
from interviewer.db.content import (
    PERSONAL,
    SHARED,
    notebook as notebook_t,
    notebook_chunk,
    notebook_source,
    notebook_topic,
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
    #: Where the bytes that arrived still are, or None for a Source ingested
    #: before they were kept (ISSUE-0033).
    object_key: str | None = None
    byte_length: int = 0
    #: derived | given. Which branch of the pipeline made this Source's Topics.
    structure: str = "derived"
    #: The Track this Module belongs to, or empty for the notebook's own.
    track_key: str = ""
    track_title: str = ""
    #: Sections embedded of sections found. Work done against work found, never
    #: an indeterminate state (ISSUE-0035).
    progress_done: int = 0
    progress_total: int = 0
    #: Locators, as extraction found them. Carried on the row because nothing
    #: carries a `Page` across a process boundary (ISSUE-0035).
    pages: tuple = ()
    started_at: object | None = None
    progress_at: object | None = None
    #: How long the current ingest has been running, and how long since it last
    #: moved — measured by the same clock that wrote the timestamps. A worker
    #: that stalls inside a live process cannot be detected by a deadline
    #: anybody invented, so both are reported and neither is judged.
    elapsed_seconds: float | None = None
    since_progress_seconds: float | None = None

    @property
    def ingesting(self) -> bool:
        return self.state == "ingesting"

    @property
    def selectable(self) -> bool:
        """Whether a Session may be scoped to this Source's Module.

        Only `ready`. Everything else — uploaded, ingesting, failed, stub — is
        listed and not selectable, and says why.
        """
        return self.state == "ready"


@dataclass(frozen=True, slots=True)
class NotebookRecord:
    notebook_id: str
    candidate_id: str
    title: str
    embedding_model: str
    sources: tuple[SourceRecord, ...]
    #: personal | shared. Defaulted rather than required, so every existing
    #: caller keeps meaning what it meant.
    visibility: str = PERSONAL
    #: Which extract this Library is, where it was imported from one.
    provenance: dict | None = None

    @property
    def shared(self) -> bool:
        return self.visibility == SHARED


class NotebookStore:
    """Reads and writes notebook material. Owns no interview state."""

    __slots__ = ("_engine",)

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- notebooks -----------------------------------------------------------

    def create(
        self,
        notebook_id: str,
        candidate_id: str,
        title: str,
        embedding_model: str,
        *,
        visibility: str = PERSONAL,
        provenance: dict | None = None,
    ) -> NotebookRecord:
        import json

        with self._engine.begin() as c:
            c.execute(
                sa.insert(notebook_t).values(
                    notebook_id=notebook_id,
                    candidate_id=candidate_id,
                    title=title,
                    embedding_model=embedding_model,
                    visibility=visibility,
                    provenance=json.dumps(provenance or {}),
                )
            )
        return NotebookRecord(
            notebook_id,
            candidate_id,
            title,
            embedding_model,
            (),
            visibility=visibility,
            provenance=provenance,
        )

    def get(self, notebook_id: str) -> NotebookRecord | None:
        with self._engine.begin() as c:
            row = (
                c.execute(
                    sa.select(notebook_t).where(notebook_t.c.notebook_id == notebook_id)
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return NotebookRecord(
                notebook_id=row["notebook_id"],
                candidate_id=row["candidate_id"],
                title=row["title"],
                embedding_model=row["embedding_model"],
                sources=self._sources(c, notebook_id),
                visibility=row["visibility"],
                provenance=_provenance_from(row["provenance"]),
            )

    def for_candidate(self, candidate_id: str) -> list[NotebookRecord]:
        """What this Candidate owns. Shared Corpora are not theirs and are not here.

        Kept strictly to ownership because two different questions are asked of
        this store — *who may write to it* and *what may they be examined on* —
        and answering both from one method is how a shared Corpus ends up
        writable by whoever listed it. `visible_to` answers the second.
        """
        return self._records(notebook_t.c.candidate_id == candidate_id)

    def visible_to(self, candidate_id: str) -> list[NotebookRecord]:
        """Everything this Candidate may be examined on: their own, plus shared.

        Read-only for the shared half. Visibility is not permission to write,
        and the guard for that reads `visibility` rather than this list.
        """
        return self._records(
            sa.or_(
                notebook_t.c.candidate_id == candidate_id,
                notebook_t.c.visibility == SHARED,
            )
        )

    def _records(self, where) -> list[NotebookRecord]:
        with self._engine.begin() as c:
            rows = (
                c.execute(
                    sa.select(notebook_t)
                    .where(where)
                    .order_by(notebook_t.c.created_at, notebook_t.c.notebook_id)
                )
                .mappings()
                .all()
            )
            return [
                NotebookRecord(
                    notebook_id=r["notebook_id"],
                    candidate_id=r["candidate_id"],
                    title=r["title"],
                    embedding_model=r["embedding_model"],
                    sources=self._sources(c, r["notebook_id"]),
                    visibility=r["visibility"],
                    provenance=_provenance_from(r["provenance"]),
                )
                for r in rows
            ]

    def all_notebook_ids(self) -> list[str]:
        with self._engine.begin() as c:
            return [
                r[0]
                for r in c.execute(
                    sa.select(notebook_t.c.notebook_id).order_by(
                        notebook_t.c.created_at, notebook_t.c.notebook_id
                    )
                )
            ]

    def visibility_of(self, notebook_id: str) -> str | None:
        with self._engine.begin() as c:
            return c.execute(
                sa.select(notebook_t.c.visibility).where(
                    notebook_t.c.notebook_id == notebook_id
                )
            ).scalar_one_or_none()

    def notebook_of_topic(self, topic_id: str) -> str | None:
        with self._engine.begin() as c:
            return c.execute(
                sa.select(notebook_topic.c.notebook_id).where(
                    notebook_topic.c.topic_id == topic_id
                )
            ).scalar_one_or_none()

    def deletable(self, notebook_id: str) -> bool:
        """Whether this Corpus may be retired by the Candidate who holds it.

        Reads `visibility` and nothing else. Keying it on the owner id would
        make a Candidate who happened to be called `platform` undeletable, and a
        shared Corpus imported under an operator's own id deletable.
        """
        return self.visibility_of(notebook_id) != SHARED

    def owner_of(self, notebook_id: str) -> str | None:
        with self._engine.begin() as c:
            return c.execute(
                sa.select(notebook_t.c.candidate_id).where(
                    notebook_t.c.notebook_id == notebook_id
                )
            ).scalar_one_or_none()

    @staticmethod
    def _sources(c, notebook_id: str) -> tuple[SourceRecord, ...]:
        rows = (
            c.execute(
                sa.select(
                    notebook_source,
                    # Read from Postgres rather than from this process: the
                    # timestamps were written by that clock, and two clocks
                    # subtracted from each other is a duration nobody can defend.
                    sa.extract(
                        "epoch", sa.func.now() - notebook_source.c.started_at
                    ).label("elapsed"),
                    sa.extract(
                        "epoch", sa.func.now() - notebook_source.c.progress_at
                    ).label("since_progress"),
                )
                .where(notebook_source.c.notebook_id == notebook_id)
                .order_by(notebook_source.c.source_order)
            )
            .mappings()
            .all()
        )
        return tuple(
            SourceRecord(
                source_id=r["source_id"],
                module_id=r["module_id"],
                title=r["title"],
                order=r["source_order"],
                state=r["state"],
                stub_reason=r["stub_reason"],
                media_type=r["media_type"],
                object_key=r["object_key"],
                byte_length=int(r["byte_length"] or 0),
                structure=r["structure"],
                track_key=r["track_key"],
                track_title=r["track_title"],
                pages=_pages_from(r["pages"]),
                progress_done=int(r["progress_done"] or 0),
                progress_total=int(r["progress_total"] or 0),
                started_at=r["started_at"],
                progress_at=r["progress_at"],
                elapsed_seconds=_seconds(r["elapsed"]),
                since_progress_seconds=_seconds(r["since_progress"]),
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
            rows = (
                c.execute(
                    sa.select(notebook_source)
                    .where(notebook_source.c.notebook_id == notebook_id)
                    .order_by(notebook_source.c.source_order)
                )
                .mappings()
                .all()
            )
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

    # -- the ingest lifecycle (ISSUE-0035) -----------------------------------

    def create_source(
        self,
        *,
        notebook_id: str,
        source_id: str,
        module_id: str,
        title: str,
        text: str,
        media_type: str,
        order: int,
        content_hash: str,
        state: str,
        stub_reason: str | None = None,
        object_key: str | None = None,
        byte_length: int = 0,
        structure: str = "derived",
        progress_total: int = 0,
        pages: tuple = (),
        track_key: str = "",
        track_title: str = "",
    ) -> None:
        """The Source row, written the moment its bytes are durable.

        A document is in the Library before it is ingested, which is the whole
        point of ISSUE-0035: a forty-second embed that dies leaves a document
        somebody can retry rather than an upload that never happened.
        """
        with self._engine.begin() as c:
            c.execute(
                sa.insert(notebook_source).values(
                    source_id=source_id,
                    notebook_id=notebook_id,
                    module_id=module_id,
                    title=title,
                    media_type=media_type,
                    source_order=order,
                    text=text,
                    content_hash=content_hash,
                    state=state,
                    stub_reason=stub_reason,
                    object_key=object_key,
                    byte_length=byte_length,
                    structure=structure,
                    progress_total=progress_total,
                    pages=_pages_to(pages),
                    track_key=track_key,
                    track_title=track_title,
                )
            )

    def begin_ingest(self, source_id: str) -> bool:
        """Claim a Source for ingestion. False when somebody else already has.

        A conditional UPDATE rather than a read-then-write, so two tabs pressing
        the same button race in the database and exactly one of them wins.
        Deliberately not reachable from `ready`: a completed ingest is not
        retried, which is what stops a retry billing twice for one document.
        """
        with self._engine.begin() as c:
            result = c.execute(
                sa.update(notebook_source)
                .where(
                    notebook_source.c.source_id == source_id,
                    notebook_source.c.state.in_(("uploaded", "failed")),
                )
                .values(
                    state="ingesting",
                    stub_reason=None,
                    progress_done=0,
                    started_at=sa.func.now(),
                    progress_at=sa.func.now(),
                )
            )
        return result.rowcount == 1

    def record_progress(self, source_id: str, *, done: int, total: int) -> None:
        with self._engine.begin() as c:
            c.execute(
                sa.update(notebook_source)
                .where(notebook_source.c.source_id == source_id)
                .values(
                    progress_done=done,
                    progress_total=total,
                    progress_at=sa.func.now(),
                )
            )

    def fail_ingest(self, source_id: str, reason: str) -> None:
        """A failure is a state on the document, not a lost upload."""
        with self._engine.begin() as c:
            c.execute(
                sa.update(notebook_source)
                .where(notebook_source.c.source_id == source_id)
                .values(state="failed", stub_reason=reason)
            )

    def reset_stale_ingests(self, reason: str) -> int:
        """Anything still `ingesting` at startup, marked failed.

        No timeout is needed and none is invented. The worker runs in-process,
        so no worker survives a restart: a row in that state when the process
        starts is stale by definition rather than by a guess about how long is
        too long.
        """
        with self._engine.begin() as c:
            result = c.execute(
                sa.update(notebook_source)
                .where(notebook_source.c.state == "ingesting")
                .values(state="failed", stub_reason=reason)
            )
        return result.rowcount

    def finish_ingest(
        self,
        *,
        notebook_id: str,
        source_id: str,
        chunks: list[Chunk],
        frozen: dict[str, FrozenTopic],
        topic_orders: dict[str, int],
        topic_tokens: dict[str, int],
        embedding_model: str = "",
    ) -> None:
        """Topics, chunks and `ready`, in one transaction.

        The Source row already exists; this is what makes it a Module. Written
        whole or not at all, so a killed run leaves no orphan Topic and no chunk
        belonging to nothing — ISSUE-0026's atomicity, unchanged.
        """
        with self._engine.begin() as c:
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
            c.execute(
                sa.update(notebook_source)
                .where(notebook_source.c.source_id == source_id)
                .values(
                    stub_reason=None,
                    progress_done=sa.func.greatest(
                        notebook_source.c.progress_total, len(chunks)
                    ),
                    progress_total=sa.func.greatest(
                        notebook_source.c.progress_total, len(chunks)
                    ),
                    progress_at=sa.func.now(),
                )
            )

    def mark_ready(self, source_id: str) -> None:
        """The last write of an ingest, and deliberately its own step.

        `ready` is what the surface reads to mean *examinable*, so it must not
        be true before the served Corpus contains the Module — otherwise a
        Candidate who starts a Session the moment the progress bar fills is told
        their Module holds no examinable Topic. Material first, then whatever
        the caller has to rebuild, then this.
        """
        with self._engine.begin() as c:
            c.execute(
                sa.update(notebook_source)
                .where(notebook_source.c.source_id == source_id)
                .values(state="ready", stub_reason=None)
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
        object_key: str | None = None,
        byte_length: int = 0,
        structure: str = "derived",
        track_key: str = "",
        track_title: str = "",
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
                    object_key=object_key,
                    byte_length=byte_length,
                    structure=structure,
                    track_key=track_key,
                    track_title=track_title,
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
            rows = (
                c.execute(
                    sa.select(notebook_topic)
                    .where(notebook_topic.c.notebook_id == notebook_id)
                    .order_by(notebook_topic.c.topic_order)
                )
                .mappings()
                .all()
            )
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

    def chunks_of(self, notebook_id: str, *, modality: str | None = None) -> list[dict]:
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
                r[0]
                for r in c.execute(
                    sa.select(notebook_chunk.c.object_key).where(
                        notebook_chunk.c.notebook_id == notebook_id,
                        notebook_chunk.c.object_key.is_not(None),
                    )
                )
            ]

    def chunk_hashes(self, notebook_id: str) -> set[str]:
        with self._engine.begin() as c:
            return {
                r[0]
                for r in c.execute(
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
                sa.delete(notebook_chunk).where(notebook_chunk.c.source_id == source_id)
            )
            c.execute(
                sa.delete(notebook_topic).where(notebook_topic.c.source_id == source_id)
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
                dict(r)
                for r in c.execute(
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
                    .values(embedding=list(vector), embedding_model=embedding_model)
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
                sa.delete(notebook_chunk).where(notebook_chunk.c.source_id == source_id)
            )
            c.execute(
                sa.delete(notebook_topic).where(notebook_topic.c.source_id == source_id)
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


def _provenance_from(raw: str | None) -> dict | None:
    import json

    try:
        return json.loads(raw or "{}") or None
    except Exception:
        return None


def _seconds(value) -> float | None:
    return None if value is None else round(float(value), 1)


def _pages_to(pages) -> str:
    """Locators as JSON. A plain text column rather than a dialect's own type:
    nothing queries inside this, it is read whole and turned back into `Page`s."""
    import json

    return json.dumps([[p.number, p.char_start, p.char_end, p.anchor] for p in pages])


def _pages_from(raw: str | None) -> tuple:
    import json

    from interviewer.corpus.adapters.notebook.extract import Page

    try:
        return tuple(
            Page(number=n, char_start=a, char_end=b, anchor=anchor)
            for n, a, b, anchor in json.loads(raw or "[]")
        )
    except Exception:
        # A malformed locator set costs page numbers, never an ingest.
        return ()
