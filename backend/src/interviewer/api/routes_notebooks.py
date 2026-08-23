"""Notebook routes — a Corpus the Candidate brought.

Nothing here quotes a price and nothing here asks for confirmation: ingest
begins when a Source is added, and its cost lands on the same ledger as a
Session's (ISSUE-0026).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from interviewer.notebooks import (
    DocumentStoreUnavailable, IngestNotClaimable, SharedCorpusIsNotYours,
)
from interviewer.notebooks.metering import InsufficientBalance

from . import ingest_worker
from .deps import get_notebook_service, refresh_corpus
from .errors import Refusal
from .auth import current_candidate
from .wiring import wiring

router = APIRouter(tags=["notebooks"])


class NotebookIn(BaseModel):
    """No candidate_id. A Corpus belongs to whoever uploaded it (ISSUE-0032)."""

    title: str = Field(min_length=1)


class SourceIn(BaseModel):
    title: str = Field(min_length=1)
    text: str = ""
    media_type: str = "text/markdown"
    #: For a page: where it came from, so a citation can point back at it. The
    #: server never follows it — HTML arrives already fetched, from the browser
    #: the Candidate was reading it in.
    url: str = ""
    #: Extraction failing is a state, not an error. ISSUE-0023 names the reasons.
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
    #: Sections embedded of sections found. Never indeterminate: the total is
    #: measured at upload, before the first provider call.
    progress_done: int = 0
    progress_total: int = 0
    #: Whether a Session may be scoped to this document's Module.
    selectable: bool = False
    #: How long the current ingest has been running, and how long since it last
    #: moved. A worker that stalls inside a live process cannot be detected by a
    #: deadline we invented, so both are reported and neither is judged.
    elapsed_seconds: float | None = None
    since_progress_seconds: float | None = None


class NotebookOut(BaseModel):
    notebook_id: str
    candidate_id: str
    title: str
    embedding_model: str
    sources: list[SourceOut]
    #: personal | shared. A shared Corpus is listed for every Candidate and is
    #: read-only to all of them; there is no field here that would let one be
    #: created, which is why a Candidate cannot make one by accident.
    visibility: str = "personal"


def _out(record) -> NotebookOut:
    return NotebookOut(
        notebook_id=record.notebook_id,
        candidate_id=record.candidate_id,
        title=record.title,
        embedding_model=record.embedding_model,
        visibility=record.visibility,
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
                elapsed_seconds=s.elapsed_seconds if s.ingesting else None,
                since_progress_seconds=(
                    s.since_progress_seconds if s.ingesting else None
                ),
            )
            for s in record.sources
        ],
    )


@router.post("/notebooks", status_code=201, response_model=NotebookOut)
def create_notebook(body: NotebookIn,
                    candidate_id: str = Depends(current_candidate)) -> NotebookOut:
    svc = get_notebook_service()
    record = svc.create(f"nb-{uuid.uuid4().hex[:12]}", candidate_id, body.title)
    return _out(record)


@router.get("/notebooks", response_model=list[NotebookOut])
def list_notebooks(candidate_id: str = Depends(current_candidate)) -> list[NotebookOut]:
    """This Candidate's Library: their own Corpora, plus every shared one.

    Shared appears here because it is examinable, not because it is theirs —
    every write path below reads `visibility` rather than this list.
    """
    svc = get_notebook_service()
    return [_out(r) for r in svc.store.visible_to(candidate_id)]


@router.get("/notebooks/{notebook_id}", response_model=NotebookOut)
def read_notebook(notebook_id: str) -> NotebookOut:
    """One Library, with each document's state and progress.

    This is what the surface polls while an ingest runs. It is a plain read of
    rows the worker is updating, so it costs nothing and cannot itself stall.
    """
    record = get_notebook_service().store.get(notebook_id)
    if record is None:
        raise HTTPException(404, "unknown notebook_id")
    return _out(record)


@router.post("/notebooks/{notebook_id}/sources", status_code=201)
def add_source(notebook_id: str, body: SourceIn) -> dict:
    """Keep the document and list it. Ingestion starts by itself.

    Returns as soon as the bytes are durable and the row is written, because a
    forty-second embed is not something to hold a request open for — and because
    an upload that outlives its ingestion is what makes a failure survivable
    (ISSUE-0035).
    """
    svc = get_notebook_service()
    route = _route_for(notebook_id)
    try:
        uploaded = svc.upload_source(
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
    return _started(notebook_id, uploaded, route)


def _started(notebook_id: str, uploaded, route: str) -> dict:
    """The upload's own answer, and the ingest set going behind it."""
    if uploaded.state == "uploaded" and not uploaded.deduplicated:
        ingest_worker.start(notebook_id, uploaded.source_id, route=route)
    else:
        # A stub reaches no embedder at all, and a duplicate is already a
        # Module. Either way the Library changed and the picker has to see it.
        refresh_corpus()
    return {
        "source_id": uploaded.source_id,
        "module_id": uploaded.module_id,
        "state": uploaded.state,
        "stub_reason": uploaded.stub_reason,
        "deduplicated": uploaded.deduplicated,
        # Work found, before any work is done. A progress readout that starts
        # at nothing of nothing is the indeterminate spinner by another name.
        "progress_done": 0,
        "progress_total": uploaded.sections,
    }


def _route_for(notebook_id: str) -> str:
    """Which ledger this ingest is on, decided from the Key Vault.

    Taken from the vault rather than the client's word, for the same reason a
    Session's route is (ADR-0008): an attached key means the Candidate pays
    their own Provider, and charging Credits as well would bill twice over.
    """
    svc = get_notebook_service()
    owner = svc.store.owner_of(notebook_id)
    if owner is None:
        raise HTTPException(404, "unknown notebook_id")
    return "byok" if wiring().vault.active(owner) else "credits"


def _added_out(added) -> dict:
    cost = added.cost
    out = {
        "source_id": added.source_id,
        "module_id": added.module_id,
        "state": added.state,
        "topics": added.topics,
        "chunks": added.chunks,
        # Reported rather than inferred: zero means "none found" on a deployment
        # with the figure lane on, and "not looked for" on one without. The
        # surface must not have to guess which (ADR-0017).
        "figures": added.figures,
        "dossier_tokens": added.dossier_tokens,
        "deduplicated": added.deduplicated,
        "stub_reason": added.stub_reason,
    }
    if cost is not None:
        # A BYOK Candidate is shown the provider and the token count, and never
        # a Credit figure (Principle 3).
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


@router.post("/notebooks/{notebook_id}/files", status_code=201)
async def add_file(
    notebook_id: str,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
) -> dict:
    """A PDF as it actually arrives: as a file.

    A file carrying no extractable text — a scan, a malformed PDF — becomes a
    stub Module rather than an error. It is listed, it states its reason, and it
    never reaches the embedder, so a notebook of scans costs nothing.
    """
    svc = get_notebook_service()
    data = await file.read()
    media_type = file.content_type or "application/octet-stream"
    is_pdf = media_type.startswith("application/pdf")
    route = _route_for(notebook_id)
    try:
        uploaded = svc.upload_source(
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
    return _started(notebook_id, uploaded, route)


@router.post("/notebooks/{notebook_id}/sources/{source_id}/retry", status_code=202)
def retry_source(notebook_id: str, source_id: str) -> dict:
    """Re-ingest a failed document. It is never re-uploaded.

    The bytes are already stored, so a retry costs the embedding again — about
    two cents for a 200-page PDF — and nothing else. Starting over rather than
    resuming is deliberate: resuming would mean chunks belonging to no Module,
    which is a class of partial state worth more than the two cents it saves.

    A Source that is already `ready` cannot be claimed, which is what stops a
    retry billing twice for one document.
    """
    svc = get_notebook_service()
    record = svc.store.get(notebook_id)
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
    ingest_worker.start(notebook_id, source_id, route=_route_for(notebook_id))
    return {"source_id": source_id, "state": "ingesting"}


@router.delete("/notebooks/{notebook_id}/sources/{source_id}", status_code=204)
def delete_source(notebook_id: str, source_id: str) -> None:
    """One Source out. Its Topics retire; every other Module is untouched."""
    svc = get_notebook_service()
    record = svc.store.get(notebook_id)
    if record is None:
        raise HTTPException(404, "unknown notebook_id")
    if source_id not in {s.source_id for s in record.sources}:
        raise HTTPException(404, "unknown source_id")
    try:
        svc.delete_source(notebook_id, source_id)
    except SharedCorpusIsNotYours as refused:
        raise _shared(refused) from None
    refresh_corpus()


@router.delete("/notebooks/{notebook_id}", status_code=204)
def delete_notebook(notebook_id: str) -> None:
    """Content goes. Evidence stays, and its Topics retire (ISSUE-0027)."""
    svc = get_notebook_service()
    if svc.store.get(notebook_id) is None:
        raise HTTPException(404, "unknown notebook_id")
    try:
        svc.delete(notebook_id)
    except SharedCorpusIsNotYours as refused:
        raise _shared(refused) from None
    refresh_corpus()


def _no_store(refused: DocumentStoreUnavailable) -> Refusal:
    """503, because the Candidate did nothing wrong and it may work in a minute.

    Named so the surface can say *the upload was refused, not half-kept* —
    which is the honest sentence, and the one a Candidate needs before they
    decide whether to try again.
    """
    return Refusal(503, refused.code, str(refused))


def _shared(refused: SharedCorpusIsNotYours) -> Refusal:
    """409, because the Corpus is in a state this request cannot be applied to.

    Not 403: nothing about the Candidate's credentials would make it succeed.
    """
    return Refusal(409, refused.code, str(refused))
