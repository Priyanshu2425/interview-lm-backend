"""Ingesting a Source, and serving what was ingested.

The pipeline lives in the Adapter; the decisions about *when* it runs live here:
a byte-identical upload is not a second Module, a Source that carries no text is
a stub rather than a failure, and a Source is written whole or not at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy.engine import Engine

from interviewer.corpus.adapters.notebook import (
    HashingEmbedder, Notebook, Source, as_chunks, attach, extract_figures,
    ingest_notebook, module_id_for, match_to_frozen, topic_id_for,
)
from interviewer.corpus.adapters.notebook.adapter import FrozenTopic
from interviewer.corpus.adapters.notebook.chunking import chunk_source, leaf_title
from interviewer.corpus.adapters.notebook.extract import extract
from interviewer.corpus.adapters.notebook.sources import digest
from interviewer.corpus.adapters.notebook.embedding import centroid_of
from interviewer.corpus.contract import Corpus
from interviewer.db.content import PERSONAL, SHARED

from .corpus_view import corpus_for
from .metering import IngestCost, IngestMeter, InsufficientBalance, estimate
from .progress import ProgressEmbedder
from .reuse import ReusingEmbedder
from .store import NotebookRecord, NotebookStore

_log = logging.getLogger(__name__)


class SourceBytesMissing(RuntimeError):
    """The document this Source was made from is not where it should be.

    Named rather than bare, because "we cannot re-extract" is a sentence a
    surface has to be able to say, and because the two ways of arriving here —
    never stored, and stored then lost — are different problems for whoever
    reads the log.
    """

    code = "source_bytes_missing"

    def __init__(self, source_id: str, why: str) -> None:
        super().__init__(f"{source_id}: {why}")
        self.source_id = source_id


class SharedCorpusIsNotYours(RuntimeError):
    """A shared Corpus is read-only to every Candidate, and undeletable by them.

    Named rather than a bare error because the surface renders the refusal from
    the API's own code and message, and "you cannot do that" composed on the
    client is how a message reaches somebody it was never about.
    """

    code = "corpus_is_shared"

    def __init__(self, notebook_id: str) -> None:
        super().__init__(
            f"{notebook_id} is a shared Corpus: it is imported once and is "
            "read-only to every Candidate, because the Topic ids in it are the "
            "join key for everybody else's Evidence."
        )
        self.notebook_id = notebook_id


@dataclass(frozen=True, slots=True)
class ReIngested:
    """What a newer version of a Source did to the ids Evidence is keyed on."""

    source_id: str
    surviving: list[str]
    new: list[str]
    vanished: list[str]
    chunks: int


@dataclass(frozen=True, slots=True)
class UploadedSource:
    """A document in the Library, before anything has been made of it."""

    source_id: str
    module_id: str
    state: str
    stub_reason: str | None = None
    deduplicated: bool = False
    #: Work found: how many sections the embedder will be asked for. Known
    #: before the first provider call, so the progress readout starts at 0 of N
    #: rather than at nothing of nothing.
    sections: int = 0


class IngestNotClaimable(RuntimeError):
    """Something else already has this Source, or it is already a Module.

    Two tabs pressing Retry is the ordinary case, and `ready` is the important
    one: a completed ingest is not re-runnable, which is what stops a retry
    billing twice for one document.
    """

    code = "ingest_not_claimable"

    def __init__(self, source_id: str, state: str) -> None:
        super().__init__(
            f"{source_id} is {state}: "
            + (
                "it has already been ingested"
                if state == "ready"
                else "an ingest is already running for it"
                if state == "ingesting"
                else "it carries no text to ingest"
            )
        )
        self.source_id = source_id
        self.state = state


@dataclass(frozen=True, slots=True)
class AddedSource:
    """What one upload produced. `deduplicated` means nothing was spent."""

    source_id: str
    module_id: str
    state: str
    topics: int
    chunks: int
    dossier_tokens: dict[str, int]
    deduplicated: bool = False
    stub_reason: str | None = None
    #: Figures lifted from the Source and attached to a Topic text drew. Zero
    #: on every text source, and on any deployment with images switched off.
    figures: int = 0
    #: What it cost, measured. A BYOK Candidate sees tokens and provider here
    #: and never a Credit figure (Principle 3).
    cost: "IngestCost | None" = None


class NotebookService:
    __slots__ = (
        "_engine", "_store", "_embedder", "_labeller", "_model_name", "_meter",
        "_objects", "_images",
    )

    def __init__(
        self,
        engine: Engine,
        *,
        embedder=None,
        labeller=None,
        embedding_model: str | None = None,
        credits=None,
        objects=None,
        images: bool = False,
    ) -> None:
        self._engine = engine
        self._store = NotebookStore(engine)
        self._embedder = embedder or HashingEmbedder()
        self._labeller = labeller
        self._model_name = embedding_model or getattr(
            self._embedder, "model_name", "hashing-v1"
        )
        self._meter = IngestMeter(credits)
        self._objects = objects
        # Asked for, and possible. An embedder with no image tower is not a
        # reason to fail an upload — it is a reason to ingest the text and say
        # nothing about pictures.
        self._images = bool(
            images and objects is not None
            and getattr(self._embedder, "supports_images", False)
        )

    @property
    def store(self) -> NotebookStore:
        return self._store

    def create(
        self,
        notebook_id: str,
        candidate_id: str,
        title: str,
        *,
        visibility: str = PERSONAL,
    ) -> NotebookRecord:
        return self._store.create(
            notebook_id, candidate_id, title,
            embedding_model=self._model_name, visibility=visibility,
        )

    def add_source(
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
        route: str = "credits",
        as_operator: bool = False,
    ) -> AddedSource:
        """Upload a Source and ingest it, in one call and in that order.

        The two halves are separable and separated (`upload_source` and
        `ingest_source`), because the upload has to outlive a forty-second
        embed that dies. This is the synchronous composition of them, for
        callers that have nowhere to poll from — a script, an import, MCP.
        """
        uploaded = self.upload_source(
            notebook_id,
            source_id=source_id,
            title=title,
            text=text,
            data=data,
            media_type=media_type,
            url=url,
            stub_reason=stub_reason,
            as_operator=as_operator,
        )
        if uploaded.state != "uploaded":
            return AddedSource(
                source_id=uploaded.source_id,
                module_id=uploaded.module_id,
                state=uploaded.state,
                topics=0,
                chunks=0,
                dossier_tokens={},
                deduplicated=uploaded.deduplicated,
                stub_reason=uploaded.stub_reason,
            )
        return self.ingest_source(notebook_id, uploaded.source_id, route=route)

    def upload_source(
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
    ) -> "UploadedSource":
        """Keep the document and list it. Embed nothing.

        A Source exists as soon as its bytes do (ISSUE-0035), so this returns as
        soon as the file is stored and the row is written — the document appears
        in the Library at once, marked as not yet ingested.

        Extraction happens here rather than in the ingest, and it is the reason
        the progress readout is never indeterminate: chunking is local and free,
        so the work *found* is a measurement taken before the first provider
        call rather than a number that appears after it.
        """
        record = self._store.get(notebook_id)
        if record is None:
            raise LookupError(notebook_id)
        if record.shared and not as_operator:
            raise SharedCorpusIsNotYours(notebook_id)

        extracted = extract(
            text=text, data=data, media_type=media_type, url=url
        )
        # Deduplication is on what was extracted, so the same PDF uploaded
        # twice is one Module however the bytes were framed. When nothing was
        # extracted there is nothing to compare, so the raw upload is hashed
        # instead — two different scans are two Sources, not one.
        content_hash = digest(
            extracted.text
            or (data.hex() if data else "")
            or (text or "")
            or source_id
        )
        stub_reason = stub_reason or extracted.stub_reason
        body = extracted.text
        existing = self._store.source_by_hash(notebook_id, content_hash)
        if existing is not None:
            # The same file twice is the same Module. No embedding, no charge.
            source = next(s for s in record.sources if s.source_id == existing)
            return UploadedSource(
                source_id=existing,
                module_id=source.module_id,
                state=source.state,
                stub_reason=source.stub_reason,
                deduplicated=True,
                sections=source.progress_total,
            )

        order = self._store.next_source_order(notebook_id)
        module_id = module_id_for(notebook_id, source_id)
        # The document is stored before the row is written, the same ordering
        # ADR-0017 fixed for figures. A row without an object is a citation
        # pointing at nothing; an object without a row is unreferenced bytes a
        # sweep can find. One is a broken product, the other is a bill.
        payload = data if data is not None else (body or text or "").encode()
        object_key, byte_length = self._keep(
            notebook_id, payload, media_type=media_type
        )
        is_stub = bool(stub_reason) or not body.strip()
        sections = 0 if is_stub else len(chunk_source(source_id, body))
        self._store.create_source(
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

    def ingest_source(
        self,
        notebook_id: str,
        source_id: str,
        *,
        route: str = "credits",
        before_ready=None,
    ) -> AddedSource:
        """Turn an uploaded document into a Module. The forty seconds.

        Claimed with a conditional UPDATE, so two tabs pressing the same button
        race in the database and exactly one wins. A failure marks the Source
        `failed` and leaves the bytes where they are: a retry re-ingests and
        never re-uploads.
        """
        record = self._store.get(notebook_id)
        if record is None:
            raise LookupError(notebook_id)
        source = next(
            (s for s in record.sources if s.source_id == source_id), None
        )
        if source is None:
            raise LookupError(source_id)
        if not self._store.begin_ingest(source_id):
            raise IngestNotClaimable(source_id, source.state)
        try:
            return self._run_ingest(
                record, source, route=route, before_ready=before_ready
            )
        except Exception as exc:
            # A failure is a state on the document rather than a lost upload.
            # Nothing partial was written: the Topics and chunks land in one
            # transaction at the end, so there is no Module, no orphan Topic and
            # no ledger entry to unwind.
            self._store.fail_ingest(source_id, _failure_reason(exc))
            raise

    def _run_ingest(
        self, record, source, *, route: str, before_ready=None
    ) -> AddedSource:
        source_id = source.source_id
        data, extracted = self._material_of(record.notebook_id, source)
        body = extracted.text
        cost = estimate([body], embedder=self._embedder, route=route)
        # Refused before the first provider call, never half-ingested.
        self._meter.gate(cost, candidate_id=record.candidate_id)

        embedder = ProgressEmbedder(
            ReusingEmbedder(
                self._embedder,
                # Scoped to the model that drew them: a vector from a space this
                # notebook has left is not a saving, it is a corruption.
                self._store.embeddings_by_hash(
                    record.notebook_id, embedding_model=self._model_name
                ),
            ),
            lambda done, total: self._store.record_progress(
                source_id, done=done, total=total
            ),
        )
        ingested = ingest_notebook(
            Notebook(
                notebook_id=record.notebook_id,
                title=record.title,
                sources=(
                    Source(
                        source_id=source_id,
                        title=source.title,
                        text=body,
                        media_type=source.media_type,
                        pages=extracted.pages,
                    ),
                ),
            ),
            embedder=embedder,
            labeller=self._labeller,
        )
        module = ingested.corpus.modules[0]
        orders = {t.id: t.order for t in module.topics}
        tokens = {
            t.id: sum(len(l.text or "") for l in t.leaves) // 4 for t in module.topics
        }
        figures = self._figures_for(
            record.notebook_id, source_id=source_id, data=data,
            media_type=source.media_type, chunks=ingested.chunks,
            embedder=embedder,
        )
        self._store.finish_ingest(
            notebook_id=record.notebook_id,
            source_id=source_id,
            chunks=ingested.chunks + figures,
            frozen=ingested.frozen,
            topic_orders=orders,
            topic_tokens=tokens,
            embedding_model=self._model_name,
        )
        # Whatever the caller has to rebuild before `ready` can be true — the
        # served Corpus, for the API. A Module that is `ready` and not yet
        # composed is a Session refused on the Topic the Candidate just watched
        # finish.
        if before_ready is not None:
            before_ready()
        self._store.mark_ready(source.source_id)
        # Charged on what was actually embedded — a resumed ingest re-reads the
        # vectors it already has and pays for none of them — and idempotent on
        # the Source, so a retry cannot bill twice either.
        cost = estimate(
            ["x" * (embedder.embedded_tokens * 4)],
            embedder=self._embedder,
            route=route,
        )
        self._meter.charge(
            cost,
            candidate_id=record.candidate_id,
            notebook_id=record.notebook_id,
            source_id=source_id,
        )
        return AddedSource(
            source_id=source_id,
            module_id=source.module_id,
            state="ready",
            topics=len(module.topics),
            chunks=len(ingested.chunks),
            dossier_tokens=ingested.report.dossier_tokens,
            cost=cost,
            figures=len(figures),
        )

    def _material_of(self, notebook_id: str, source):
        """What the ingest works from: the extraction, and the bytes if kept.

        The text and its locators come off the row, because extraction happened
        at upload and both were written with it — a deployment with no object
        store keeps its page numbers, which it would not if this re-extracted.

        The bytes are fetched only for the figure lane, which genuinely needs
        them, and their absence costs pictures rather than the Module.
        """
        from interviewer.corpus.adapters.notebook.extract import Extracted, Page

        text = source_text(self._store, source.source_id)
        pages = source.pages or ((Page(1, 0, len(text)),) if text else ())
        try:
            data = self.source_bytes(notebook_id, source.source_id)
        except SourceBytesMissing:
            data = None
        return data, Extracted(text, pages)

    def import_structured(
        self,
        notebook_id: str,
        *,
        source_id: str,
        title: str,
        topics,
        module_id: str | None = None,
        route: str = "credits",
        as_operator: bool = False,
    ) -> AddedSource:
        """Import material that arrived with its own Topics, ids and order.

        The same ingest as any other in every respect that costs money or can
        half-succeed: gated before the first provider call, charged on what was
        actually embedded, and written in one transaction so a Module appears
        whole or not at all. What differs is the middle stage — nothing is
        clustered and no id is minted (ISSUE-0034).

        `module_id` is taken from the source too where one is given. Session
        scope is keyed on it, so a shipped Module that keeps its id survives the
        move off disk instead of becoming a new Module nobody's scope names.
        """
        from interviewer.corpus.adapters.notebook.structured import ingest_given

        record = self._store.get(notebook_id)
        if record is None:
            raise LookupError(notebook_id)
        if record.shared and not as_operator:
            raise SharedCorpusIsNotYours(notebook_id)

        given = list(topics)
        # By content *and* by structure: two imports differing only in a Topic
        # id are two different Corpora, and a hash over the prose alone would
        # call them the same one.
        content_hash = digest(
            *(
                part
                for topic in sorted(given, key=lambda t: t.topic_id)
                for part in (topic.topic_id, topic.title, topic.text)
            )
        )
        existing = self._store.source_by_hash(notebook_id, content_hash)
        if existing is not None:
            source = next(s for s in record.sources if s.source_id == existing)
            return AddedSource(
                source_id=existing,
                module_id=source.module_id,
                state=source.state,
                topics=0,
                chunks=0,
                dossier_tokens={},
                deduplicated=True,
                stub_reason=source.stub_reason,
            )

        order = self._store.next_source_order(notebook_id)
        module = module_id or module_id_for(notebook_id, source_id)
        text = "\n\n".join(topic.text for topic in given)
        object_key, byte_length = self._keep(
            notebook_id, text.encode(), media_type="text/markdown"
        )
        cost = estimate([text], embedder=self._embedder, route=route)
        self._meter.gate(cost, candidate_id=record.candidate_id)

        embedder = ReusingEmbedder(
            self._embedder,
            self._store.embeddings_by_hash(
                notebook_id, embedding_model=self._model_name
            ),
        )
        ingested = ingest_given(
            notebook_id=notebook_id,
            notebook_title=record.title,
            source_id=source_id,
            source_title=title,
            module_id=module,
            module_order=order,
            topics=given,
            embedder=embedder,
        )
        built = ingested.corpus.modules[0]
        self._store.save_source_ingest(
            notebook_id=notebook_id,
            source=Source(source_id=source_id, title=title, text=text),
            module_id=module,
            order=order,
            content_hash=content_hash,
            chunks=ingested.chunks,
            frozen=ingested.frozen,
            topic_orders={t.id: t.order for t in built.topics},
            topic_tokens={
                t.id: sum(len(leaf.text or "") for leaf in t.leaves) // 4
                for t in built.topics
            },
            embedding_model=self._model_name,
            object_key=object_key,
            byte_length=byte_length,
            structure="given",
        )
        cost = estimate(
            ["x" * (embedder.embedded_tokens * 4)],
            embedder=self._embedder,
            route=route,
        )
        self._meter.charge(
            cost,
            candidate_id=record.candidate_id,
            notebook_id=notebook_id,
            source_id=source_id,
        )
        return AddedSource(
            source_id=source_id,
            module_id=module,
            state="ready",
            topics=len(built.topics),
            chunks=len(ingested.chunks),
            dossier_tokens=ingested.report.dossier_tokens,
            cost=cost,
        )

    def _keep(
        self, notebook_id: str, payload: bytes, *, media_type: str
    ) -> tuple[str | None, int]:
        """Put the document in the object store and say where it went.

        Content-addressed, so the same document twice is stored once and a
        re-upload after a failed ingest costs nothing extra.

        A deployment with no object store keeps no document and says so with a
        null key — storage is an addition to this pipeline, never a
        precondition for it, and an upload must not start failing because a
        bucket was not configured.
        """
        if self._objects is None or not payload:
            return None, len(payload)
        key = self._objects.source_key_for(
            notebook_id, sha256(payload).hexdigest(), _suffix_for(media_type)
        )
        self._objects.put(key, payload, media_type)
        return key, len(payload)

    def source_bytes(self, notebook_id: str, source_id: str) -> bytes:
        """The document as it arrived, or a named failure.

        Two different absences, reported as one exception carrying which:
        a Source ingested before ISSUE-0033 never had an object, and a Source
        whose object has gone missing had one. Both mean "cannot re-extract",
        and neither is a bare `KeyError` from inside a bucket client.
        """
        source = next(
            (
                s for s in self._store.get(notebook_id).sources
                if s.source_id == source_id
            ),
            None,
        )
        if source is None:
            raise LookupError(source_id)
        if not source.object_key or self._objects is None:
            raise SourceBytesMissing(
                source_id,
                "this Source was ingested before its bytes were kept, so there "
                "is nothing to re-extract from",
            )
        try:
            return self._objects.get(source.object_key)
        except Exception as exc:
            raise SourceBytesMissing(
                source_id,
                f"the stored document at {source.object_key} could not be read",
            ) from exc

    def re_extract(self, notebook_id: str, source_id: str) -> "ReIngested":
        """Re-ingest from the stored document rather than from the text column.

        `notebook_source.text` is what one extractor made of the bytes on one
        day. Re-running against it can only ever reproduce that opinion, which
        is why a better extractor could never be applied to old material —
        this is the path that can.
        """
        source = next(
            (
                s for s in self._store.get(notebook_id).sources
                if s.source_id == source_id
            ),
            None,
        )
        if source is None:
            raise LookupError(source_id)
        data = self.source_bytes(notebook_id, source_id)
        # The same framing the upload route uses: a PDF is bytes to an
        # extractor, everything else is text that happened to arrive as bytes.
        extracted = extract(
            text=(
                "" if source.media_type == "application/pdf"
                else data.decode("utf-8", errors="replace")
            ),
            data=data,
            media_type=source.media_type,
        )
        return self.replace_source(
            notebook_id, source_id=source_id, text=extracted.text
        )

    def _figures_for(
        self, notebook_id: str, *, source_id: str, data: bytes | None,
        media_type: str, chunks: list, embedder,
    ) -> list:
        """The Source's pictures, embedded and stored, or nothing at all.

        Uploaded before the rows are written, so a chunk never points at a key
        that is not there. A failure anywhere in here costs the figures and not
        the Module: the text of a Candidate's notes is the product, and a
        picture is an addition to it.
        """
        if not (self._images and data):
            return []
        try:
            found = extract_figures(data, media_type=media_type)
            if not found:
                return []
            rows = as_chunks(
                found,
                attach(found, chunks),
                source_id=source_id,
                notebook_id=notebook_id,
                object_key_for=self._objects.key_for,
            )
            if not rows:
                return []
            kept = [f for f, r in zip(found, rows) if r is not None]
            vectors = embedder.embed_images(
                [f.data for f in kept], [r.content_hash for r in rows]
            )
            for row, figure, vector in zip(rows, kept, vectors):
                row.embedding = vector
                self._objects.put(row.object_key, figure.data, figure.media_type)
            return rows
        except Exception:
            _log.warning("figures skipped for %s", source_id, exc_info=True)
            return []

    # -- re-ingest -----------------------------------------------------------

    def replace_source(
        self, notebook_id: str, *, source_id: str, text: str
    ) -> "ReIngested":
        """Take a newer version of a Source that is already ingested.

        Never re-clusters (ADR-0015). Chunks are matched against frozen
        centroids; only material that matches nothing is clustered, and only
        that material can mint an id.
        """
        record = self._store.get(notebook_id)
        if record is None:
            raise LookupError(notebook_id)
        source = next(
            (s for s in self._store.sources_of(notebook_id) if s.source_id == source_id),
            None,
        )
        if source is None:
            raise LookupError(source_id)

        content_hash = digest(text)
        frozen = {
            tid: ft
            for tid, ft in self._store.frozen_topics(notebook_id).items()
            if ft.source_id == source_id
        }
        chunks = chunk_source(source_id, text)
        for chunk, vector in zip(chunks, self._embedder.embed([c.text for c in chunks])):
            chunk.embedding = vector

        module_id = module_id_for(notebook_id, source_id)
        minted: dict[str, FrozenTopic] = {}

        def mint(cluster) -> str:
            hashes = tuple(c.content_hash for c in cluster.chunks)
            topic_id = topic_id_for(notebook_id, source_id, hashes)
            title = self._title_for(cluster)
            minted[topic_id] = FrozenTopic(
                topic_id=topic_id,
                module_id=module_id,
                source_id=source_id,
                title=title,
                centroid=cluster.centroid,
                chunk_hashes=hashes,
            )
            return topic_id

        match = match_to_frozen(chunks, frozen, mint=mint)

        # Surviving Topics keep their id, their title and their centroid. Only
        # membership moves — a centroid recomputed on every upload is a boundary
        # that drifts without saying so.
        surviving = {
            tid: FrozenTopic(
                topic_id=tid,
                module_id=frozen[tid].module_id,
                source_id=source_id,
                title=frozen[tid].title,
                centroid=frozen[tid].centroid,
                chunk_hashes=tuple(
                    c.content_hash for c in chunks if c.topic_id == tid
                ),
            )
            for tid in match.surviving
        }
        kept = {**surviving, **minted}
        orders, tokens = _orders_and_tokens(kept, chunks)

        self._store.replace_source_material(
            notebook_id=notebook_id,
            source_id=source_id,
            text=text,
            content_hash=content_hash,
            chunks=chunks,
            frozen=kept,
            topic_orders=orders,
            topic_tokens=tokens,
            embedding_model=self._model_name,
        )
        self._store.record_version(
            notebook_id=notebook_id,
            source_id=source_id,
            reason="re_ingested",
            surviving=match.surviving,
            new=match.new,
            vanished=match.vanished,
            note=f"{match.matched_chunks} chunk(s) matched, "
                 f"{match.unmatched_chunks} clustered",
        )
        return ReIngested(
            source_id=source_id,
            surviving=match.surviving,
            new=match.new,
            vanished=match.vanished,
            chunks=len(chunks),
        )

    def re_embed(self, notebook_id: str, *, embedding_model: str) -> None:
        """Re-embed in a new space, carrying every Topic membership across.

        Membership is stored data. Re-deriving it here would mean a change of
        embedding model silently redrawing Topic boundaries, which is the one
        thing ADR-0015 forbids outright.
        """
        record = self._store.get(notebook_id)
        if record is None:
            raise LookupError(notebook_id)

        frozen = self._store.frozen_topics(notebook_id)
        rows = self._store.chunks_of(notebook_id)
        # Two modalities, two towers. Passing an image row's empty text through
        # the text encoder would return a zero vector and quietly drag its
        # Topic's centroid toward the origin.
        vectors: dict[str, tuple[float, ...]] = {}
        texts = [r for r in rows if r["modality"] == "text"]
        if texts:
            for row, vector in zip(texts, self._embedder.embed([r["text"] for r in texts])):
                vectors[row["chunk_id"]] = vector
        images = [r for r in rows if r["modality"] == "image"]
        if images:
            if self._objects is None:
                raise RuntimeError(
                    f"{notebook_id} carries figures and no object store is "
                    "configured to read them back"
                )
            payloads = [self._objects.get(r["object_key"]) for r in images]
            for row, vector in zip(
                images, self._embedder.embed_images(payloads, [r["content_hash"] for r in images])
            ):
                vectors[row["chunk_id"]] = vector

        by_topic: dict[str, list[tuple[float, ...]]] = {}
        for row in rows:
            # Centroids are drawn by text (ADR-0015). A figure moved into the
            # Topic, it does not get a say in where the Topic is.
            if row["modality"] != "text":
                continue
            by_topic.setdefault(row["topic_id"], []).append(vectors[row["chunk_id"]])

        self._store.re_embed(
            notebook_id=notebook_id,
            chunk_vectors=vectors,
            centroids={
                tid: centroid_of(vs) for tid, vs in by_topic.items() if tid in frozen
            },
            embedding_model=embedding_model,
        )
        for source in record.sources:
            self._store.record_version(
                notebook_id=notebook_id,
                source_id=source.source_id,
                reason="embedding_model_changed",
                surviving=sorted(
                    tid for tid, ft in frozen.items() if ft.source_id == source.source_id
                ),
                new=[],
                vanished=[],
                note=f"re-embedded into {embedding_model}",
            )

    def versions(self, notebook_id: str) -> list[dict]:
        return self._store.versions(notebook_id)

    def _title_for(self, cluster) -> str:
        first = min(cluster.chunks, key=lambda c: c.char_start)
        if self._labeller is not None:
            try:
                title = (self._labeller([c.text for c in cluster.chunks]) or "").strip()
                if title:
                    return title[:120]
            except Exception:
                pass
        return first.anchor[:120] or leaf_title(first.text)

    # -- reading -------------------------------------------------------------

    def corpus(self, notebook_id: str) -> Corpus | None:
        record = self._store.get(notebook_id)
        return corpus_for(self._store, record) if record else None

    def all_corpora(self) -> list[Corpus]:
        out = []
        for notebook_id in self._store.all_notebook_ids():
            corpus = self.corpus(notebook_id)
            if corpus is not None:
                out.append(corpus)
        return out

    def comparable(self, notebook_id: str) -> bool:
        """Whether a comparison may be drawn across this Corpus at all.

        Shared only. A personal Corpus mints `topic_id`s nobody else holds, so
        its cohort is one by construction — no rule is needed to stop a
        comparison, and this says so rather than leaving the absence of a rule
        to be noticed. ISSUE-0036 reads this before it reads any posterior.
        """
        return self._store.visibility_of(notebook_id) == SHARED

    def delete(self, notebook_id: str) -> None:
        """Retire a Corpus and its material. Refuses a shared one.

        The guard is here rather than at the route, and that placement is the
        slice. ADR-0010 defined `content` as "the Candidate's, and deleted when
        they say so"; a shared Corpus is not that. Deleting one retires the
        `topic_id`s every other Candidate's Evidence points at, and nothing
        would error — the damage surfaces later, as somebody asking why their
        record looks thinner than it did. A refusal that lived only in the
        absence of a route would last exactly until somebody wrote one.
        """
        self._refuse_if_shared(notebook_id)
        self._store.delete_notebook(notebook_id, objects=self._objects)

    def delete_source(self, notebook_id: str, source_id: str) -> None:
        """One Source out, and the same guard: a Source carries Topics too."""
        self._refuse_if_shared(notebook_id)
        self._store.delete_source(source_id)

    def _refuse_if_shared(self, notebook_id: str) -> None:
        if not self._store.deletable(notebook_id):
            raise SharedCorpusIsNotYours(notebook_id)


def _orders_and_tokens(
    frozen: dict, chunks: list
) -> tuple[dict[str, int], dict[str, int]]:
    """Order follows position, never the clusterer (ADR-0015)."""
    earliest = {}
    tokens: dict[str, int] = {}
    for chunk in chunks:
        tid = chunk.topic_id
        earliest[tid] = min(earliest.get(tid, chunk.char_start), chunk.char_start)
        tokens[tid] = tokens.get(tid, 0) + chunk.approx_tokens
    ordered = sorted(frozen, key=lambda tid: earliest.get(tid, 0))
    return {tid: i for i, tid in enumerate(ordered, 1)}, tokens


#: What to call the stored document on disk. Cosmetic — the key is the content
#: hash and nothing reads the extension — but a bucket somebody has to look
#: through by hand is easier when the files are named after what they are.
_SUFFIXES = {
    "application/pdf": "pdf",
    "text/markdown": "md",
    "text/plain": "txt",
    "text/html": "html",
}


def _suffix_for(media_type: str) -> str:
    return _SUFFIXES.get((media_type or "").split(";")[0].strip(), "bin")


def _failure_reason(exc: Exception) -> str:
    """What the Library says about a failed ingest.

    The exception's own words where it has any: a message composed here would
    be this module's guess at somebody else's failure, and the Candidate would
    read the guess.
    """
    message = str(exc).strip()
    return message[:200] if message else f"ingest failed: {type(exc).__name__}"


def source_text(store: NotebookStore, source_id: str) -> str:
    """The cached extraction, for the one case where the bytes are gone."""
    import sqlalchemy as sa

    from interviewer.db.content import notebook_source

    with store._engine.begin() as c:  # noqa: SLF001 — same package, same table
        return c.execute(
            sa.select(notebook_source.c.text).where(
                notebook_source.c.source_id == source_id
            )
        ).scalar_one_or_none() or ""
