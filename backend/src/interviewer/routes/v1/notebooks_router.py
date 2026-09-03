"""Notebook routes (async) — a Corpus the Candidate brought.

Nothing here quotes a price and nothing here asks for confirmation: ingest
begins when a Source is added, and its cost lands on the same ledger as a
Session's (ISSUE-0026).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from interviewer.service.notebooks import (
    DocumentStoreUnavailable, IngestNotClaimable, SharedCorpusIsNotYours,
)

from ... import ingest_worker
from ...deps import refresh_corpus
from ...deps_async import (
    get_async_notebook_service,
    get_async_notebook_store,
)
from ...exception.definitions import Refusal
from ...security.auth import current_candidate
from ...wiring import wiring

if TYPE_CHECKING:
    # Annotations only. Imported under the guard because these are the
    # dependency types, not the dependency: FastAPI takes the object from
    # `Depends`, and a plain import here would be a second edge into the
    # repository package for no runtime gain.
    from ...repository.async_repositories import (
        AsyncNotebookService,
    )

router = APIRouter(tags=["notebooks"])


class NotebookIn(BaseModel):
    """No candidate_id. A Corpus belongs to whoever uploaded it (ISSUE-0032)."""

    title: str = Field(min_length=1)


class SourceIn(BaseModel):
    title: str = Field(min_length=1)
    text: str = ""
    media_type: str = "text/markdown"
    # For a page: where it came from, so a citation can point back at it.
    url: str = ""
    # Extraction failing is a state, not an error. ISSUE-0023 names the reasons.
    stub_reason: str | None = None


class SourceOut(BaseModel):
    """A document in the Library, in whatever state it is actually in.

    `uploaded | ingesting | ready | failed | stub`. A Source exists as soon as
    its bytes do, so a document appears here before it is examinable — listed,
    not selectable, and saying why (ISSUE-0035).
    """

    source_id: str
    module_id: str
    title: str
    state: str
    stub_reason: str | None = None
    # Sections embedded of sections found. Never indeterminate: the total is
    # measured at upload, before the first provider call.
    progress_done: int = 0
    progress_total: int = 0
    # Whether a Session may be scoped to this document's Module.
    selectable: bool = False
    # How many Topics this document was cut into. Served rather than derived:
    # the surface used to work it out by joining the Module list against this
    # row's `module_id`, which is the client computing something the server
    # owns (ADR-0009).
    topic_count: int = 0
    # How long the current ingest has been running, and how long since it last
    # moved. A worker that stalls inside a live process cannot be detected by a
    # deadline we invented, so both are reported and neither is judged.
    elapsed_seconds: float | None = None
    since_progress_seconds: float | None = None


class NotebookOut(BaseModel):
    notebook_id: str
    candidate_id: str
    title: str
    embedding_model: str
    sources: list[SourceOut]
    # personal | shared. A shared Corpus is listed for every Candidate and is
    # read-only to all of them; there is no field here that would let one be
    # created, which is why a Candidate cannot make one by accident.
    visibility: str = "personal"
    #: When this Library was started, so a listing can order and date itself
    #: without asking a second endpoint.
    created_at: str | None = None


def _out(record, topic_counts: dict[str, int] | None = None) -> NotebookOut:
    return NotebookOut(
        notebook_id=record.notebook_id,
        candidate_id=record.candidate_id,
        title=record.title,
        embedding_model=record.embedding_model,
        visibility=record.visibility,
        created_at=(
            record.created_at.isoformat() if record.created_at is not None else None
        ),
        sources=[
            SourceOut(
                source_id=s.source_id,
                module_id=s.module_id,
                title=s.title,
                state=s.state,
                stub_reason=s.stub_reason,
                progress_done=s.progress_done,
                progress_total=s.progress_total,
                selectable=s.selectable,
                topic_count=(topic_counts or {}).get(s.source_id, 0),
                elapsed_seconds=s.elapsed_seconds if s.ingesting else None,
                since_progress_seconds=(
                    s.since_progress_seconds if s.ingesting else None
                ),
            )
            for s in record.sources
        ],
    )


async def _reachable(
    notebook_id: str,
    candidate_id: str,
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
):
    """The Library, if this Candidate may see it. A 404 either way."""
    record = await notebook_service.store.get(notebook_id)
    if record is None:
        raise HTTPException(404, "unknown notebook_id")
    if record.visibility != "shared" and record.candidate_id != candidate_id:
        raise HTTPException(404, "unknown notebook_id")
    return record


async def _own(
    notebook_id: str,
    candidate_id: str,
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
):
    """The Candidate's *own* Library, and a 404 for anything that is not.

    `_reachable` lets a shared Corpus through on purpose, because a write to
    one must refuse with a reason rather than pretend it is missing. A read is
    the other way round: the Notebook screen is a Candidate's own material
    (SPEC-0006), and a shared Skill is chosen where it is used — the Session
    picker — so here it is simply not theirs.

    The check is on the owner rather than on `visibility`: `PLATFORM_OWNER` is
    a sentinel for who holds a platform Corpus, never a rule about who may
    read one.
    """
    record = await notebook_service.store.get(notebook_id)
    if record is None or record.candidate_id != candidate_id:
        raise HTTPException(404, "unknown notebook_id")
    return record


@router.post("/notebooks", status_code=201, response_model=NotebookOut)
async def create_notebook(
    body: NotebookIn,
    candidate_id: str = Depends(current_candidate),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> NotebookOut:
    record = await notebook_service.create(
        f"nb-{uuid.uuid4().hex[:12]}", candidate_id, body.title
    )
    return _out(record)


@router.get("/notebooks", response_model=list[NotebookOut])
async def list_notebooks(
    candidate_id: str = Depends(current_candidate),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> list[NotebookOut]:
    """This Candidate's own Corpora, and nobody else's.

    Not `visible_to`: a shared Skill is imported by an operator and chosen at
    Session setup, where it is used. Listing it here made the Notebook screen
    a place where material the Candidate never uploaded sat beside material
    they did, with no way to tell which was which (SPEC-0006).
    """
    records = await notebook_service.store.for_candidate(candidate_id)
    counts = await notebook_service.store.topic_counts(
        [r.notebook_id for r in records]
    )
    return [_out(r, counts) for r in records]


@router.get("/notebooks/{notebook_id}", response_model=NotebookOut)
async def read_notebook(
    notebook_id: str,
    candidate_id: str = Depends(current_candidate),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> NotebookOut:
    """One Library, with each document's state and progress."""
    record = await _own(notebook_id, candidate_id, notebook_service)
    counts = await notebook_service.store.topic_counts([notebook_id])
    return _out(record, counts)


class SpanOut(BaseModel):
    """Where a Topic was drawn from, addressed into the Source's own text.

    `text[char_start:char_end]` is the passage exactly (`util/chunking_utils`),
    which is what lets a surface show the material a Topic came from rather
    than a paraphrase of it. The text itself is not repeated here: it is the
    slice these offsets name, and carrying both would send the document twice.
    """

    chunk_id: str
    page: int
    char_start: int
    char_end: int


class TopicOut(BaseModel):
    """One Topic this document was cut into, frozen at ingest (ADR-0015)."""

    topic_id: str
    title: str
    topic_order: int
    dossier_tokens: int
    spans: list[SpanOut]


class PageOut(BaseModel):
    """A page boundary, in the same coordinate space as a span."""

    number: int
    char_start: int
    char_end: int
    anchor: str


class SourceDetailOut(SourceOut):
    """One document read back: what was extracted, and what became of it.

    `text` is what one extractor made of the document and is a cache of it,
    not the document — the bytes themselves are in the object store
    (ISSUE-0033) and are not served here.

    The Topics and their spans travel with it deliberately. The offsets are
    only meaningful against one exact string, so a surface that fetched text
    and spans separately could pair a highlight with a re-extracted text and
    point at the wrong passage — silently, which is the one failure this
    screen exists to prevent.
    """

    notebook_id: str
    media_type: str
    byte_length: int
    text: str
    pages: list[PageOut]
    topics: list[TopicOut]


@router.get(
    "/notebooks/{notebook_id}/sources/{source_id}",
    response_model=SourceDetailOut,
)
async def read_source(
    notebook_id: str,
    source_id: str,
    candidate_id: str = Depends(current_candidate),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> SourceDetailOut:
    """One document, its text, and the Topics cut out of it.

    Every state answers. A document being read has text and no Topics yet; one
    that carried no text says why and has neither; one whose embedding failed
    has its text and no Topics. None of those is an error — a state is data,
    and a document that vanished from this route would look like one that
    never arrived.
    """
    record = await _own(notebook_id, candidate_id, notebook_service)
    source = next(
        (s for s in record.sources if s.source_id == source_id), None
    )
    if source is None:
        raise HTTPException(404, "unknown source_id")

    store = notebook_service.store
    text = await store.source_text(notebook_id, source_id) or ""
    topics = await store.topics_of_source(source_id)
    spans = await store.spans_of_topics([t["topic_id"] for t in topics])

    by_topic: dict[str, list[SpanOut]] = {}
    for span in spans:
        by_topic.setdefault(span["topic_id"], []).append(
            SpanOut(
                chunk_id=span["chunk_id"],
                page=span["page"],
                char_start=span["char_start"],
                char_end=span["char_end"],
            )
        )

    return SourceDetailOut(
        source_id=source.source_id,
        notebook_id=notebook_id,
        module_id=source.module_id,
        title=source.title,
        state=source.state,
        stub_reason=source.stub_reason,
        progress_done=source.progress_done,
        progress_total=source.progress_total,
        selectable=source.selectable,
        topic_count=len(topics),
        elapsed_seconds=source.elapsed_seconds if source.ingesting else None,
        since_progress_seconds=(
            source.since_progress_seconds if source.ingesting else None
        ),
        media_type=source.media_type,
        byte_length=source.byte_length,
        text=text,
        pages=[
            PageOut(
                number=p.number,
                char_start=p.char_start,
                char_end=p.char_end,
                anchor=p.anchor,
            )
            for p in source.pages
        ],
        topics=[
            TopicOut(
                topic_id=t["topic_id"],
                title=t["title"],
                topic_order=t["topic_order"],
                dossier_tokens=t["dossier_tokens"],
                spans=by_topic.get(t["topic_id"], []),
            )
            for t in topics
        ],
    )


async def _route_for(
    notebook_id: str,
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
    keyvault: "AsyncKeyVault" = None,
) -> str:
    """Which ledger this ingest is on, decided from the Key Vault."""
    # We need keyvault - import here to avoid circular
    # This is a simplified version - in practice we'd inject keyvault
    # For now use the sync wiring
    owner = await notebook_service.store.owner_of(notebook_id)
    if owner is None:
        raise HTTPException(404, "unknown notebook_id")
    # `wiring().vault.active` is entirely synchronous (it bootstraps `wiring()`
    # itself on first call, which may run a blocking DDL migration) — run it
    # off the event loop thread. Called on-thread, it can block waiting on a
    # lock this same request's own async session is still holding, and
    # nothing is left free to release it.
    import anyio.to_thread

    key = await anyio.to_thread.run_sync(lambda: wiring().vault.active(owner))
    return "byok" if key else "credits"


def _started(notebook_id: str, uploaded, route: str) -> dict:
    """The upload's own answer, and the ingest set going behind it."""
    if uploaded.state == "uploaded" and not uploaded.deduplicated:
        ingest_worker.start(notebook_id, uploaded.source_id, route=route)
    else:
        refresh_corpus()
    return {
        "source_id": uploaded.source_id,
        "module_id": uploaded.module_id,
        "state": uploaded.state,
        "stub_reason": uploaded.stub_reason,
        "deduplicated": uploaded.deduplicated,
        "progress_done": 0,
        "progress_total": uploaded.sections,
    }


def _added_out(added) -> dict:
    cost = added.cost
    out = {
        "source_id": added.source_id,
        "module_id": added.module_id,
        "state": added.state,
        "topics": added.topics,
        "chunks": added.chunks,
        "figures": added.figures,
        "dossier_tokens": added.dossier_tokens,
        "deduplicated": added.deduplicated,
        "stub_reason": added.stub_reason,
    }
    if cost is not None:
        out["cost"] = (
            {"route": "byok", "tokens": cost.tokens, "embedding_model": cost.model}
            if cost.route == "byok"
            else {
                "route": "credits",
                "tokens": cost.tokens,
                "credits": cost.credits,
                "embedding_model": cost.model,
            }
        )
    return out


@router.post("/notebooks/{notebook_id}/sources", status_code=201)
async def add_source(
    notebook_id: str,
    body: SourceIn,
    candidate_id: str = Depends(current_candidate),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> dict:
    """Keep the document and list it. Ingestion starts by itself."""
    await _reachable(notebook_id, candidate_id, notebook_service)
    route = await _route_for(notebook_id, notebook_service)
    try:
        uploaded = await notebook_service.store.upload_source(
            notebook_id,
            source_id=f"src-{uuid.uuid4().hex[:12]}",
            title=body.title,
            text=body.text,
            media_type=body.media_type,
            url=body.url,
            stub_reason=body.stub_reason,
        )
    except LookupError:
        raise HTTPException(404, "unknown notebook_id") from None
    except SharedCorpusIsNotYours as refused:
        raise _shared(refused) from None
    except DocumentStoreUnavailable as refused:
        raise _no_store(refused) from None
    # Ingestion, whether started here or refreshed inline, reads this row
    # through a different connection than the one that just wrote it.
    await notebook_service.store.commit()
    return _started(notebook_id, uploaded, route)


@router.post("/notebooks/{notebook_id}/files", status_code=201)
async def add_file(
    notebook_id: str,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    candidate_id: str = Depends(current_candidate),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> dict:
    """A PDF as it actually arrives: as a file."""
    await _reachable(notebook_id, candidate_id, notebook_service)
    data = await file.read()
    media_type = file.content_type or "application/octet-stream"
    is_pdf = media_type.startswith("application/pdf")
    route = await _route_for(notebook_id, notebook_service)
    try:
        uploaded = await notebook_service.store.upload_source(
            notebook_id,
            source_id=f"src-{uuid.uuid4().hex[:12]}",
            title=title or file.filename or "Untitled",
            data=data,
            text="" if is_pdf else data.decode("utf-8", errors="replace"),
            media_type=media_type,
        )
    except LookupError:
        raise HTTPException(404, "unknown notebook_id") from None
    except SharedCorpusIsNotYours as refused:
        raise _shared(refused) from None
    except DocumentStoreUnavailable as refused:
        raise _no_store(refused) from None
    await notebook_service.store.commit()
    return _started(notebook_id, uploaded, route)


@router.post("/notebooks/{notebook_id}/sources/{source_id}/retry", status_code=202)
async def retry_source(
    notebook_id: str,
    source_id: str,
    candidate_id: str = Depends(current_candidate),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> dict:
    """Re-ingest a failed document. It is never re-uploaded."""
    await _reachable(notebook_id, candidate_id, notebook_service)
    record = await notebook_service.store.get(notebook_id)
    if record is None:
        raise HTTPException(404, "unknown notebook_id")
    source = next(
        (s for s in record.sources if s.source_id == source_id), None
    )
    if source is None:
        raise HTTPException(404, "unknown source_id")
    if record.shared:
        raise _shared(SharedCorpusIsNotYours(notebook_id))
    if source.state not in ("failed", "uploaded"):
        raise Refusal(
            409, IngestNotClaimable.code,
            str(IngestNotClaimable(source_id, source.state)),
        )
    route = await _route_for(notebook_id, notebook_service)
    ingest_worker.start(notebook_id, source_id, route=route)
    return {"source_id": source_id, "state": "ingesting"}


@router.delete("/notebooks/{notebook_id}/sources/{source_id}", status_code=204)
async def delete_source(
    notebook_id: str,
    source_id: str,
    candidate_id: str = Depends(current_candidate),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> None:
    """One Source out. Its Topics retire; every other Module is untouched."""
    record = await _reachable(notebook_id, candidate_id, notebook_service)
    if source_id not in {s.source_id for s in record.sources}:
        raise HTTPException(404, "unknown source_id")
    try:
        await notebook_service.store.delete_source(notebook_id, source_id)
    except SharedCorpusIsNotYours as refused:
        raise _shared(refused) from None
    await notebook_service.store.commit()
    refresh_corpus()


@router.delete("/notebooks/{notebook_id}", status_code=204)
async def delete_notebook(
    notebook_id: str,
    candidate_id: str = Depends(current_candidate),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> None:
    """Content goes. Evidence stays, and its Topics retire (ISSUE-0027)."""
    await _reachable(notebook_id, candidate_id, notebook_service)
    try:
        await notebook_service.store.delete_notebook(notebook_id)
    except SharedCorpusIsNotYours as refused:
        raise _shared(refused) from None
    await notebook_service.store.commit()
    refresh_corpus()


def _no_store(refused: DocumentStoreUnavailable) -> Refusal:
    """503, because the Candidate did nothing wrong and it may work in a minute."""
    return Refusal(503, refused.code, str(refused))


def _shared(refused: SharedCorpusIsNotYours) -> Refusal:
    """409, because the Corpus is in a state this request cannot be applied to."""
    return Refusal(409, refused.code, str(refused))