"""Async Notebook Store — reads and writes notebook material in content schema."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.content import (
    notebook as notebook_t,
    notebook_chunk,
    notebook_source,
    notebook_topic,
)
from ...db.schema import corpus_version
from ..notebooks import (
    NotebookRecord,
    SourceRecord,
    _pages_from,
    _provenance_from,
    _seconds,
)
from ...service.corpus.sources.notebook.documents import (
    Chunk,
    FrozenTopic,
    Notebook,
    Source,
)


#: Distinguishes "not mentioned" from an explicit `objects=None`, which is
#: a deployment that deliberately keeps no documents.
_DEPLOYMENT_STORE = object()


class AsyncNotebookStore:
    """Async version of NotebookStore for API services."""

    __slots__ = ("_s",)

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def commit(self) -> None:
        """Make this session's writes visible to every other connection.

        `get_async_db()` commits once, after the whole request returns — too
        late for a route that reads its own write through a *different*
        connection before then: `refresh_corpus()` (sync engine) and
        `ingest_worker.start()`'s background thread (also sync) both do
        exactly that. Call this the moment a write needs to be seen outside
        this session, not at the end of the route.
        """
        await self._s.commit()

    async def create(
        self,
        notebook_id: str,
        candidate_id: str,
        title: str,
        embedding_model: str,
        *,
        visibility: str = "personal",
        provenance: dict | None = None,
    ) -> NotebookRecord:
        import json

        await self._s.execute(
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

    async def get(self, notebook_id: str) -> NotebookRecord | None:
        result = await self._s.execute(
            sa.select(notebook_t).where(notebook_t.c.notebook_id == notebook_id)
        )
        row = result.mappings().first()
        if row is None:
            return None
        return NotebookRecord(
            notebook_id=row["notebook_id"],
            candidate_id=row["candidate_id"],
            title=row["title"],
            embedding_model=row["embedding_model"],
            sources=await self._sources(notebook_id),
            visibility=row["visibility"],
            provenance=_provenance_from(row["provenance"]),
            active=bool(row["active"]),
            created_at=row["created_at"],
        )

    async def _sources(self, notebook_id: str) -> tuple[SourceRecord, ...]:
        result = await self._s.execute(
            sa.select(
                # Named rather than `notebook_source` whole: the table carries
                # the document's entire extracted text, and a listing that
                # selects it drags every byte of every document through this
                # process on every poll to build records that have no text
                # field. `source_text()` is how one document's text is read.
                notebook_source.c.source_id,
                notebook_source.c.module_id,
                notebook_source.c.title,
                notebook_source.c.source_order,
                notebook_source.c.state,
                notebook_source.c.stub_reason,
                notebook_source.c.media_type,
                notebook_source.c.object_key,
                notebook_source.c.byte_length,
                notebook_source.c.structure,
                notebook_source.c.track_key,
                notebook_source.c.track_title,
                notebook_source.c.pages,
                notebook_source.c.progress_done,
                notebook_source.c.progress_total,
                notebook_source.c.started_at,
                notebook_source.c.progress_at,
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
        rows = result.mappings().all()
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

    async def for_candidate(self, candidate_id: str) -> list[NotebookRecord]:
        from ...db.content import PERSONAL
        result = await self._s.execute(
            sa.select(notebook_t)
            .where(notebook_t.c.candidate_id == candidate_id)
            .order_by(notebook_t.c.created_at, notebook_t.c.notebook_id)
        )
        rows = result.mappings().all()
        return [
            NotebookRecord(
                notebook_id=r["notebook_id"],
                candidate_id=r["candidate_id"],
                title=r["title"],
                embedding_model=r["embedding_model"],
                sources=await self._sources(r["notebook_id"]),
                visibility=r["visibility"],
                provenance=_provenance_from(r["provenance"]),
                active=bool(r["active"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def visible_to(self, candidate_id: str) -> list[NotebookRecord]:
        from ...db.content import PERSONAL, SHARED
        result = await self._s.execute(
            sa.select(notebook_t)
            .where(
                sa.or_(
                    notebook_t.c.candidate_id == candidate_id,
                    sa.and_(
                        notebook_t.c.visibility == SHARED,
                        notebook_t.c.active.is_(True),
                    ),
                )
            )
            .order_by(notebook_t.c.created_at, notebook_t.c.notebook_id)
        )
        rows = result.mappings().all()
        return [
            NotebookRecord(
                notebook_id=r["notebook_id"],
                candidate_id=r["candidate_id"],
                title=r["title"],
                embedding_model=r["embedding_model"],
                sources=await self._sources(r["notebook_id"]),
                visibility=r["visibility"],
                provenance=_provenance_from(r["provenance"]),
                active=bool(r["active"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def all_notebook_ids(self) -> list[str]:
        result = await self._s.execute(
            sa.select(notebook_t.c.notebook_id).order_by(
                notebook_t.c.created_at, notebook_t.c.notebook_id
            )
        )
        return [r[0] for r in result.all()]

    async def visibility_of(self, notebook_id: str) -> str | None:
        result = await self._s.execute(
            sa.select(notebook_t.c.visibility).where(
                notebook_t.c.notebook_id == notebook_id
            )
        )
        return result.scalar_one_or_none()

    async def comparable(self, notebook_id: str) -> bool:
        """Whether a comparison may be drawn across this Corpus at all.

        Shared only. A personal Corpus mints `topic_id`s nobody else holds, so
        its cohort is one by construction — no rule is needed to stop a
        comparison, and this says so rather than leaving the absence of a rule
        to be noticed. ISSUE-0036 reads this before it reads any posterior.
        """
        from ...db.content import SHARED

        return await self.visibility_of(notebook_id) == SHARED

    async def comparable_topic(self, topic_id: str) -> bool:
        """Whether this Topic is one two Candidates can be compared on.

        A Topic this deployment has never stored is not comparable either,
        because nothing can say whose it was.
        """
        notebook_id = await self.notebook_of_topic(topic_id)
        return notebook_id is not None and await self.comparable(notebook_id)

    async def notebook_of_topic(self, topic_id: str) -> str | None:
        result = await self._s.execute(
            sa.select(notebook_topic.c.notebook_id).where(
                notebook_topic.c.topic_id == topic_id
            )
        )
        return result.scalar_one_or_none()

    async def source_by_hash(self, notebook_id: str, content_hash: str) -> str | None:
        result = await self._s.execute(
            sa.select(notebook_source.c.source_id).where(
                notebook_source.c.notebook_id == notebook_id,
                notebook_source.c.content_hash == content_hash,
            )
        )
        return result.scalar_one_or_none()

    async def next_source_order(self, notebook_id: str) -> int:
        result = await self._s.execute(
            sa.select(sa.func.max(notebook_source.c.source_order)).where(
                notebook_source.c.notebook_id == notebook_id
            )
        )
        return (result.scalar() or 0) + 1

    async def create_source(
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
        import json

        await self._s.execute(
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
                pages=json.dumps([[p.number, p.char_start, p.char_end, p.anchor] for p in pages]),
                track_key=track_key,
                track_title=track_title,
            )
        )

    async def begin_ingest(self, source_id: str) -> bool:
        result = await self._s.execute(
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

    async def record_progress(self, source_id: str, *, done: int, total: int) -> None:
        await self._s.execute(
            sa.update(notebook_source)
            .where(notebook_source.c.source_id == source_id)
            .values(
                progress_done=done,
                progress_total=total,
                progress_at=sa.func.now(),
            )
        )

    async def fail_ingest(self, source_id: str, reason: str) -> None:
        await self._s.execute(
            sa.update(notebook_source)
            .where(notebook_source.c.source_id == source_id)
            .values(state="failed", stub_reason=reason)
        )

    async def finish_ingest(
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
        if frozen:
            await self._s.execute(
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
            await self._s.execute(
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
        await self._s.execute(
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

    async def mark_ready(self, source_id: str) -> None:
        await self._s.execute(
            sa.update(notebook_source)
            .where(notebook_source.c.source_id == source_id)
            .values(state="ready", stub_reason=None)
        )

    async def topic_orders(self, notebook_id: str) -> dict[str, int]:
        """Each Topic's order within its Module, as frozen at ingest."""
        result = await self._s.execute(
            sa.select(
                notebook_topic.c.topic_id, notebook_topic.c.topic_order
            ).where(notebook_topic.c.notebook_id == notebook_id)
        )
        return {tid: order for tid, order in result.all()}

    async def frozen_topics(self, notebook_id: str) -> dict[str, FrozenTopic]:
        result = await self._s.execute(
            sa.select(notebook_topic)
            .where(notebook_topic.c.notebook_id == notebook_id)
            .order_by(notebook_topic.c.topic_order)
        )
        rows = result.mappings().all()
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

    async def chunks_of(self, notebook_id: str, *, modality: str | None = None) -> list[dict]:
        query = (
            sa.select(notebook_chunk)
            .where(notebook_chunk.c.notebook_id == notebook_id)
            .order_by(notebook_chunk.c.source_id, notebook_chunk.c.char_start)
        )
        if modality is not None:
            query = query.where(notebook_chunk.c.modality == modality)
        result = await self._s.execute(query)
        return [dict(r) for r in result.mappings()]

    async def embeddings_by_hash(
        self, notebook_id: str, *, embedding_model: str | None = None
    ) -> dict[str, tuple[float, ...]]:
        query = sa.select(
            notebook_chunk.c.content_hash, notebook_chunk.c.embedding
        ).where(notebook_chunk.c.notebook_id == notebook_id)
        if embedding_model is not None:
            query = query.where(notebook_chunk.c.embedding_model == embedding_model)
        result = await self._s.execute(query)
        rows = result.all()
        return {h: tuple(v) for h, v in rows}

    # -- reading one document back ------------------------------------------
    #
    # What the Notebook screen shows: the text an extractor made of a document,
    # the Topics cut from it, and where in the text each Topic was cut from.
    # `text[char_start:char_end]` is the chunk exactly (`util/chunking_utils`),
    # so these three reads describe one coordinate space and are only
    # meaningful together.

    async def source_text(self, notebook_id: str, source_id: str) -> str | None:
        """The extracted text of one document, or None if it is not this one's.

        Scoped by both ids rather than by `source_id` alone: a source id
        guessed from somebody else's Library must not resolve, and a route
        that forgot to check would otherwise be the only thing stopping it.

        Deliberately not a field on `SourceRecord`: `_sources()` runs for every
        notebook in a listing, and a `Text` column there means listing five
        notebooks drags every byte of every document into this process to
        render a page of titles.
        """
        result = await self._s.execute(
            sa.select(notebook_source.c.text).where(
                notebook_source.c.notebook_id == notebook_id,
                notebook_source.c.source_id == source_id,
            )
        )
        return result.scalar_one_or_none()

    async def topics_of_source(self, source_id: str) -> list[dict[str, Any]]:
        """The Topics one document was cut into, in the order they were frozen.

        Never selects `centroid`: it is 768 floats per row and no screen can
        use it, so a UI read that materialises one is paying for a vector to
        throw it away.
        """
        result = await self._s.execute(
            sa.select(
                notebook_topic.c.topic_id,
                notebook_topic.c.module_id,
                notebook_topic.c.title,
                notebook_topic.c.topic_order,
                notebook_topic.c.dossier_tokens,
            )
            .where(notebook_topic.c.source_id == source_id)
            .order_by(notebook_topic.c.topic_order)
        )
        return [dict(r) for r in result.mappings()]

    async def spans_of_topics(self, topic_ids: list[str]) -> list[dict[str, Any]]:
        """Where each Topic was drawn from, as spans into its Source's text.

        Queried by `topic_id` because `ix_chunk_topic` is the only index that
        covers this — there is none on `notebook_chunk.source_id`.

        Text only: a figure is anchored to a page rather than to a span of
        prose (ADR-0017), so an image chunk has no range to highlight. The
        chunk's own text is not selected because it *is* the slice the offsets
        name, and sending it beside them would send the document twice.
        """
        if not topic_ids:
            return []
        result = await self._s.execute(
            sa.select(
                notebook_chunk.c.chunk_id,
                notebook_chunk.c.topic_id,
                notebook_chunk.c.page,
                notebook_chunk.c.char_start,
                notebook_chunk.c.char_end,
            )
            .where(
                notebook_chunk.c.topic_id.in_(topic_ids),
                notebook_chunk.c.modality == "text",
            )
            .order_by(notebook_chunk.c.char_start)
        )
        return [dict(r) for r in result.mappings()]

    async def topic_counts(self, notebook_ids: list[str]) -> dict[str, int]:
        """How many Topics each document produced, keyed by `source_id`.

        One grouped query for a whole listing, so a Library can say what became
        of a document without the surface joining two endpoints to work it out
        — which is the surface deciding something the server owns (ADR-0009).
        """
        if not notebook_ids:
            return {}
        result = await self._s.execute(
            sa.select(notebook_topic.c.source_id, sa.func.count())
            .where(notebook_topic.c.notebook_id.in_(notebook_ids))
            .group_by(notebook_topic.c.source_id)
        )
        return {source_id: int(n) for source_id, n in result.all()}

    # -- ownership, deletion, and the async half of upload ------------------
    #
    # Ingestion itself never runs here. `ingest_worker.py` always claims and
    # embeds through the sync `NotebookService` in its background thread,
    # regardless of which route started it, so this store only needs the part
    # of upload that has to finish before the request can answer: extract,
    # dedupe, keep the bytes, write the row.

    async def owner_of(self, notebook_id: str) -> str | None:
        result = await self._s.execute(
            sa.select(notebook_t.c.candidate_id).where(
                notebook_t.c.notebook_id == notebook_id
            )
        )
        return result.scalar_one_or_none()

    async def delete_source(self, notebook_id: str, source_id: str) -> None:
        """One Source out. Refuses a shared Corpus — there is no service layer
        above this store on the async side to hold that guard instead."""
        await self._refuse_if_shared(notebook_id)
        await self._s.execute(
            sa.delete(notebook_chunk).where(notebook_chunk.c.source_id == source_id)
        )
        await self._s.execute(
            sa.delete(notebook_topic).where(notebook_topic.c.source_id == source_id)
        )
        await self._s.execute(
            sa.delete(notebook_source).where(
                notebook_source.c.source_id == source_id
            )
        )

    async def delete_notebook(self, notebook_id: str) -> None:
        """Content only. Nothing here can reach `core` (ISSUE-0027)."""
        await self._refuse_if_shared(notebook_id)
        for table in (notebook_chunk, notebook_topic, notebook_source):
            await self._s.execute(
                sa.delete(table).where(table.c.notebook_id == notebook_id)
            )
        await self._s.execute(
            sa.delete(notebook_t).where(notebook_t.c.notebook_id == notebook_id)
        )

    async def _refuse_if_shared(self, notebook_id: str) -> None:
        from ...db.content import SHARED
        from ...service.notebooks import SharedCorpusIsNotYours

        visibility = await self.visibility_of(notebook_id)
        if visibility == SHARED:
            raise SharedCorpusIsNotYours(notebook_id)

    async def upload_source(
        self,
        notebook_id: str,
        *,
        source_id: str,
        title: str,
        text: str = "",
        data: bytes | None = None,
        media_type: str = "text/markdown",
        url: str = "",
        stub_reason: str | None = None,
        as_operator: bool = False,
        objects=_DEPLOYMENT_STORE,
    ) -> "UploadedSource":
        """Keep the document and list it. Embed nothing (ISSUE-0035).

        The async twin of `NotebookService.upload_source` — same extraction,
        same content-hash dedupe, same object-store write — but this is the
        whole of it: ingestion (`ingest_source`) always runs on the sync path,
        in `ingest_worker`'s background thread, whichever route uploaded.
        """
        from ...service.corpus.sources.notebook.adapter import module_id_for
        from ...service.corpus.sources.notebook.chunking import chunk_source
        from ...service.corpus.sources.notebook.documents.extract import extract
        from ...service.corpus.sources.notebook.documents.sources import digest
        from ...db.content import SHARED
        from ...service.notebooks import SharedCorpusIsNotYours, UploadedSource

        if objects is _DEPLOYMENT_STORE:
            # Resolved here rather than defaulted to None: a caller that simply
            # did not mention the object store means "the deployment's", and
            # reading None as "keep nothing" is how uploads came to write a row
            # pointing at bytes nobody had kept (ISSUE-0033).
            from ... import deps

            objects = deps.get_object_store()

        record = await self.get(notebook_id)
        if record is None:
            raise LookupError(notebook_id)
        if record.visibility == SHARED and not as_operator:
            raise SharedCorpusIsNotYours(notebook_id)

        extracted = extract(text=text, data=data, media_type=media_type, url=url)
        content_hash = digest(
            extracted.text
            or (data.hex() if data else "")
            or (text or "")
            or source_id
        )
        stub_reason = stub_reason or extracted.stub_reason
        body = extracted.text
        existing = await self.source_by_hash(notebook_id, content_hash)
        if existing is not None:
            source = next(s for s in record.sources if s.source_id == existing)
            return UploadedSource(
                source_id=existing,
                module_id=source.module_id,
                state=source.state,
                stub_reason=source.stub_reason,
                deduplicated=True,
                sections=source.progress_total,
            )

        order = await self.next_source_order(notebook_id)
        module_id = module_id_for(notebook_id, source_id)
        payload = data if data is not None else (body or text or "").encode()
        object_key, byte_length = _keep(objects, notebook_id, payload, media_type=media_type)
        is_stub = bool(stub_reason) or not body.strip()
        sections = 0 if is_stub else len(chunk_source(source_id, body))
        await self.create_source(
            notebook_id=notebook_id,
            source_id=source_id,
            module_id=module_id,
            title=title,
            text=body,
            media_type=media_type,
            order=order,
            content_hash=content_hash,
            state="stub" if is_stub else "uploaded",
            stub_reason=stub_reason or ("no extractable text" if is_stub else None),
            object_key=object_key,
            byte_length=byte_length,
            progress_total=sections,
            pages=extracted.pages,
        )
        return UploadedSource(
            source_id=source_id,
            module_id=module_id,
            state="stub" if is_stub else "uploaded",
            stub_reason=stub_reason or ("no extractable text" if is_stub else None),
            sections=sections,
        )

    async def shared_skills(self) -> list[NotebookRecord]:
        """Every shared notebook, regardless of who is asking — the admin list."""
        from ...db.content import SHARED

        result = await self._s.execute(
            sa.select(notebook_t)
            .where(notebook_t.c.visibility == SHARED)
            .order_by(notebook_t.c.created_at, notebook_t.c.notebook_id)
        )
        rows = result.mappings().all()
        return [
            NotebookRecord(
                notebook_id=r["notebook_id"],
                candidate_id=r["candidate_id"],
                title=r["title"],
                embedding_model=r["embedding_model"],
                sources=await self._sources(r["notebook_id"]),
                visibility=r["visibility"],
                provenance=_provenance_from(r["provenance"]),
                active=bool(r["active"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def set_active(self, notebook_id: str, active: bool) -> None:
        await self._s.execute(
            sa.update(notebook_t)
            .where(notebook_t.c.notebook_id == notebook_id)
            .values(active=active)
        )


def _keep(objects, notebook_id: str, payload: bytes, *, media_type: str):
    """Put the document in the object store and say where it went.

    Content-addressed twin of `NotebookService._keep`. A deployment with no
    object store keeps no document and says so with a null key.
    """
    from hashlib import sha256

    from ...service.notebooks.notebook_service import (
        DocumentStoreUnavailable,
        _suffix_for,
    )

    if objects is None or not payload:
        return None, len(payload)
    key = objects.source_key_for(
        notebook_id, sha256(payload).hexdigest(), _suffix_for(media_type)
    )
    try:
        objects.put(key, payload, media_type)
    except Exception as exc:
        raise DocumentStoreUnavailable(str(exc)) from exc
    return key, len(payload)