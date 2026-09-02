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
    """This Candidate's Library: their own Corpora, plus every shared one."""
    records = await notebook_service.store.visible_to(candidate_id)
    return [_out(r) for r in records]


@router.get("/notebooks/{notebook_id}", response_model=NotebookOut)
async def read_notebook(
    notebook_id: str,
    candidate_id: str = Depends(current_candidate),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> NotebookOut:
    """One Library, with each document's state and progress."""
    return _out(await _reachable(notebook_id, candidate_id, notebook_service))


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