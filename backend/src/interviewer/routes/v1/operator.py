"""Operator console (async). Authenticated separately from Candidate access."""

from __future__ import annotations

from typing import TYPE_CHECKING

import os
import uuid

import anyio.to_thread
from dataclasses import asdict

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from interviewer.service.metering.operator import OperatorService

from ... import ingest_worker
from ...deps import get_object_store, refresh_corpus
from ...deps_async import get_async_notebook_service, get_async_pool_ledger
from ...exception.definitions import Refusal
from ...wiring import wiring

if TYPE_CHECKING:
    # Annotations only. Imported under the guard because these are the
    # dependency types, not the dependency: FastAPI takes the object from
    # `Depends`, and a plain import here would be a second edge into the
    # repository package for no runtime gain.
    from ...repository.async_repositories import (
        AsyncNotebookService,
        AsyncPoolLedger,
    )

router = APIRouter(tags=["operator"])


def _guard(token: str | None) -> None:
    expected = os.environ.get("OPERATOR_TOKEN", "dev-operator-token")
    if token != expected:
        raise HTTPException(401, "operator access required")


@router.get("/operator/pool")
async def pool(
    x_operator_token: str | None = Header(default=None),
    pool_ledger: AsyncPoolLedger = Depends(get_async_pool_ledger),
) -> list[dict]:
    _guard(x_operator_token)
    return await pool_ledger.entries()


@router.get("/operator/providers")
async def providers(
    x_operator_token: str | None = Header(default=None),
) -> dict:
    _guard(x_operator_token)
    svc = OperatorService(wiring().engine)
    return {
        "unpriced_rate": svc.unpriced_rate(),
        "providers": [asdict(p) for p in svc.by_provider()],
        "normaliser": None,
    }


@router.get("/operator/sessions")
async def sessions(
    x_operator_token: str | None = Header(default=None),
) -> dict:
    _guard(x_operator_token)
    return {"sessions": OperatorService(wiring().engine).sessions()}


# -- Skills (shared, platform-authored notebooks) ---------------------------
#
# A shared Skill is imported once and read by everybody, which is exactly the
# thing a Candidate must not be able to create: the `topic_id`s in it become the
# join key for everyone's Evidence, and a second one meaning the same thing
# would split a measurement in half without saying so.
#
# So every route here lives behind the operator credential, and the
# Candidate-facing `POST /notebooks` carries no visibility field at all. Not
# refused — unreachable. This is also the one place the team creates a shared
# Skill at all — the dashboard replaces `scripts/import_corpus.py` as the entry
# point (its `POST .../import` still backs bulk structured loads).


class SharedSkillIn(BaseModel):
    title: str = Field(min_length=1)


class SharedSourceIn(BaseModel):
    title: str = Field(min_length=1)
    text: str = ""
    media_type: str = "text/markdown"
    url: str = ""


class GivenLeafIn(BaseModel):
    leaf_id: str
    title: str = ""
    text: str
    kind: str = "content"
    answers_leaf_id: str | None = None


class GivenTopicIn(BaseModel):
    topic_id: str
    title: str
    order: int
    leaves: list[GivenLeafIn] = Field(default_factory=list)


class ImportIn(BaseModel):
    """One Module of authored material, with the divisions it arrived with."""

    title: str = Field(min_length=1)
    module_id: str | None = None
    track_key: str = ""
    track_title: str = ""
    topics: list[GivenTopicIn] = Field(min_length=1)


class ActiveIn(BaseModel):
    active: bool


def _source_states(record) -> dict[str, int]:
    counts = {"uploaded": 0, "ingesting": 0, "ready": 0, "failed": 0, "stub": 0}
    for s in record.sources:
        counts[s.state] = counts.get(s.state, 0) + 1
    return counts


def _skill_summary(record) -> dict:
    return {
        "notebook_id": record.notebook_id,
        "title": record.title,
        "active": record.active,
        "source_count": len(record.sources),
        "states": _source_states(record),
    }


async def _shared_or_404(notebook_service, notebook_id: str):
    from interviewer.db.content import SHARED

    record = await notebook_service.store.get(notebook_id)
    if record is None or record.visibility != SHARED:
        raise Refusal(404, "unknown_notebook_id", "No shared Skill has that id.")
    return record


def _sync_notebook_service():
    from ...deps import get_notebook_service

    return get_notebook_service()


@router.post("/operator/skills", status_code=201)
async def create_shared_skill(
    body: SharedSkillIn,
    x_operator_token: str | None = Header(default=None),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> dict:
    _guard(x_operator_token)
    from interviewer.db.content import PLATFORM_OWNER, SHARED

    record = await notebook_service.create(
        f"nb-{uuid.uuid4().hex[:12]}", PLATFORM_OWNER, body.title,
        visibility=SHARED,
    )
    await notebook_service.store.commit()
    refresh_corpus()
    return {
        "notebook_id": record.notebook_id,
        "title": record.title,
        "visibility": record.visibility,
        "active": record.active,
    }


@router.get("/operator/skills")
async def list_shared_skills(
    x_operator_token: str | None = Header(default=None),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> list[dict]:
    _guard(x_operator_token)
    records = await notebook_service.store.shared_skills()
    return [_skill_summary(r) for r in records]


@router.get("/operator/skills/{notebook_id}")
async def get_shared_skill(
    notebook_id: str,
    x_operator_token: str | None = Header(default=None),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> dict:
    _guard(x_operator_token)
    record = await _shared_or_404(notebook_service, notebook_id)
    return {
        "notebook_id": record.notebook_id,
        "title": record.title,
        "active": record.active,
        "sources": [
            {
                "source_id": s.source_id,
                "module_id": s.module_id,
                "title": s.title,
                "state": s.state,
                "stub_reason": s.stub_reason,
                "progress_done": s.progress_done,
                "progress_total": s.progress_total,
            }
            for s in record.sources
        ],
    }


@router.post("/operator/skills/{notebook_id}/sources", status_code=201)
async def add_shared_source(
    notebook_id: str,
    body: SharedSourceIn,
    x_operator_token: str | None = Header(default=None),
) -> dict:
    """Text or URL material into a shared Skill, ingested inline.

    Calls the *sync* `NotebookService` directly rather than the async store:
    this route answers with topic/chunk counts immediately, which means the
    full extract-chunk-embed-cluster pipeline has to run before it responds —
    exactly what `NotebookService.add_source` already does, tested, and what
    `ingest_worker`'s background thread already runs for every other ingest in
    this app. `providers`/`sessions` above already set the precedent for
    calling a sync, `wiring().engine`-backed service from an async handler.
    """
    _guard(x_operator_token)
    service = _sync_notebook_service()
    try:
        added = await anyio.to_thread.run_sync(
            lambda: service.add_source(
                notebook_id,
                source_id=f"src-{uuid.uuid4().hex[:12]}",
                title=body.title,
                text=body.text,
                media_type=body.media_type,
                url=body.url,
                as_operator=True,
            )
        )
    except LookupError:
        raise HTTPException(404, "unknown notebook_id") from None
    refresh_corpus()
    return _added_out(added)


@router.post("/operator/skills/{notebook_id}/import", status_code=201)
async def import_structured(
    notebook_id: str,
    body: ImportIn,
    x_operator_token: str | None = Header(default=None),
) -> dict:
    """Import material that already carries its Topics, ids and order.

    Same reasoning as `add_shared_source`: this is the synchronous,
    full-pipeline path, so it calls the sync `NotebookService` directly.
    """
    _guard(x_operator_token)
    from interviewer.adapters.internal.notebook.structured import GivenLeaf, GivenTopic

    topics = [
        GivenTopic(
            topic_id=t.topic_id,
            title=t.title,
            order=t.order,
            leaves=tuple(
                GivenLeaf(
                    leaf_id=leaf.leaf_id,
                    title=leaf.title,
                    text=leaf.text,
                    kind=leaf.kind,
                    answers_leaf_id=leaf.answers_leaf_id,
                )
                for leaf in t.leaves
            ),
        )
        for t in body.topics
    ]
    service = _sync_notebook_service()
    try:
        added = await anyio.to_thread.run_sync(
            lambda: service.import_structured(
                notebook_id,
                source_id=f"src-{uuid.uuid4().hex[:12]}",
                title=body.title,
                module_id=body.module_id,
                track_key=body.track_key,
                track_title=body.track_title,
                topics=topics,
                as_operator=True,
            )
        )
    except LookupError:
        raise HTTPException(404, "unknown notebook_id") from None
    refresh_corpus()
    return _added_out(added)


@router.post("/operator/skills/{notebook_id}/files", status_code=201)
async def add_shared_file(
    notebook_id: str,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    x_operator_token: str | None = Header(default=None),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> dict:
    """A PDF (or any file) dropped onto a shared Skill.

    The lightweight half only — create the Source row, then hand off to
    `ingest_worker` exactly like `notebooks.py`'s candidate-facing `add_file`
    does. Ingestion itself still runs on the sync path either way, so this
    route never touches the embed/cluster pipeline directly.
    """
    _guard(x_operator_token)
    await _shared_or_404(notebook_service, notebook_id)
    data = await file.read()
    media_type = file.content_type or "application/octet-stream"
    is_pdf = media_type.startswith("application/pdf")
    try:
        uploaded = await notebook_service.store.upload_source(
            notebook_id,
            source_id=f"src-{uuid.uuid4().hex[:12]}",
            title=title or file.filename or "Untitled",
            data=data,
            text="" if is_pdf else data.decode("utf-8", errors="replace"),
            media_type=media_type,
            as_operator=True,
            objects=get_object_store(),
        )
    except LookupError:
        raise HTTPException(404, "unknown notebook_id") from None
    # Ingestion, whether started here or refreshed inline, reads this row
    # through a different connection than the one that just wrote it.
    await notebook_service.store.commit()
    # No candidate BYOK key applies to a platform-owned Skill — everything
    # here is billed the same way, so there is no key-vault lookup to make.
    if uploaded.state == "uploaded" and not uploaded.deduplicated:
        ingest_worker.start(notebook_id, uploaded.source_id, route="credits")
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


@router.patch("/operator/skills/{notebook_id}/active")
async def set_skill_active(
    notebook_id: str,
    body: ActiveIn,
    x_operator_token: str | None = Header(default=None),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> dict:
    """Take a shared Skill out of discovery, or bring it back.

    Reversible and immediate: a candidate's in-flight Evidence and topic
    lookups are unaffected either way (`GET /skills/topics/{id}` never checks
    this flag) — only what gets listed for new Sessions changes.
    """
    _guard(x_operator_token)
    await _shared_or_404(notebook_service, notebook_id)
    await notebook_service.store.set_active(notebook_id, body.active)
    await notebook_service.store.commit()
    refresh_corpus()
    return {"notebook_id": notebook_id, "active": body.active}


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
