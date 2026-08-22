"""Notebook routes — a Corpus the Candidate brought.

Nothing here quotes a price and nothing here asks for confirmation: ingest
begins when a Source is added, and its cost lands on the same ledger as a
Session's (ISSUE-0026).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from interviewer.notebooks.metering import InsufficientBalance

from .deps import get_notebook_service, refresh_corpus
from .wiring import wiring

router = APIRouter(tags=["notebooks"])


class NotebookIn(BaseModel):
    candidate_id: str
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
    source_id: str
    module_id: str
    title: str
    state: str
    stub_reason: str | None = None


class NotebookOut(BaseModel):
    notebook_id: str
    candidate_id: str
    title: str
    embedding_model: str
    sources: list[SourceOut]


def _out(record) -> NotebookOut:
    return NotebookOut(
        notebook_id=record.notebook_id,
        candidate_id=record.candidate_id,
        title=record.title,
        embedding_model=record.embedding_model,
        sources=[
            SourceOut(
                source_id=s.source_id,
                module_id=s.module_id,
                title=s.title,
                state=s.state,
                stub_reason=s.stub_reason,
            )
            for s in record.sources
        ],
    )


@router.post("/notebooks", status_code=201, response_model=NotebookOut)
def create_notebook(body: NotebookIn) -> NotebookOut:
    svc = get_notebook_service()
    record = svc.create(f"nb-{uuid.uuid4().hex[:12]}", body.candidate_id, body.title)
    return _out(record)


@router.get("/notebooks", response_model=list[NotebookOut])
def list_notebooks(candidate_id: str) -> list[NotebookOut]:
    svc = get_notebook_service()
    return [_out(r) for r in svc.store.for_candidate(candidate_id)]


@router.post("/notebooks/{notebook_id}/sources", status_code=201)
def add_source(notebook_id: str, body: SourceIn) -> dict:
    svc = get_notebook_service()
    route = _route_for(notebook_id)
    try:
        added = svc.add_source(
            notebook_id,
            source_id=f"src-{uuid.uuid4().hex[:12]}",
            title=body.title,
            text=body.text,
            media_type=body.media_type,
            url=body.url,
            stub_reason=body.stub_reason,
            route=route,
        )
    except LookupError:
        raise HTTPException(404, "unknown notebook_id") from None
    except InsufficientBalance as short:
        # A refusal, not a quote: nothing was spent and nothing was stored.
        raise HTTPException(
            402,
            f"ingest was not started — it needs {short.required} Credits and the "
            f"balance is {short.balance}, short by {short.shortfall}",
        ) from None
    refresh_corpus()
    return _added_out(added)


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
        added = svc.add_source(
            notebook_id,
            source_id=f"src-{uuid.uuid4().hex[:12]}",
            title=title or file.filename or "Untitled",
            data=data,
            text="" if is_pdf else data.decode("utf-8", errors="replace"),
            media_type=media_type,
            route=route,
        )
    except LookupError:
        raise HTTPException(404, "unknown notebook_id") from None
    except InsufficientBalance as short:
        raise HTTPException(
            402,
            f"ingest was not started — it needs {short.required} Credits and the "
            f"balance is {short.balance}, short by {short.shortfall}",
        ) from None
    refresh_corpus()
    return _added_out(added)


@router.delete("/notebooks/{notebook_id}/sources/{source_id}", status_code=204)
def delete_source(notebook_id: str, source_id: str) -> None:
    """One Source out. Its Topics retire; every other Module is untouched."""
    svc = get_notebook_service()
    record = svc.store.get(notebook_id)
    if record is None:
        raise HTTPException(404, "unknown notebook_id")
    if source_id not in {s.source_id for s in record.sources}:
        raise HTTPException(404, "unknown source_id")
    svc.store.delete_source(source_id)
    refresh_corpus()


@router.delete("/notebooks/{notebook_id}", status_code=204)
def delete_notebook(notebook_id: str) -> None:
    """Content goes. Evidence stays, and its Topics retire (ISSUE-0027)."""
    svc = get_notebook_service()
    if svc.store.get(notebook_id) is None:
        raise HTTPException(404, "unknown notebook_id")
    svc.delete(notebook_id)
    refresh_corpus()
