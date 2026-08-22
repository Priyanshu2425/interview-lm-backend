"""Operator console. Authenticated separately from Candidate access."""

from __future__ import annotations

import os
from dataclasses import asdict

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from interviewer.metering.operator import OperatorService

from .wiring import wiring

router = APIRouter(tags=["operator"])


def _guard(token: str | None) -> None:
    expected = os.environ.get("OPERATOR_TOKEN", "dev-operator-token")
    if token != expected:
        raise HTTPException(401, "operator access required")


@router.get("/operator/pool")
def pool(x_operator_token: str | None = Header(default=None)) -> dict:
    _guard(x_operator_token)
    return asdict(OperatorService(wiring().engine).pool())


@router.get("/operator/providers")
def providers(x_operator_token: str | None = Header(default=None)) -> dict:
    _guard(x_operator_token)
    svc = OperatorService(wiring().engine)
    return {
        "unpriced_rate": svc.unpriced_rate(),
        "providers": [asdict(p) for p in svc.by_provider()],
        # Weights are set by Grading Mode alone. No normaliser is applied to
        # any figure here, and none will be invented.
        "normaliser": None,
    }


@router.get("/operator/corpus-index")
def corpus_index(x_operator_token: str | None = Header(default=None)) -> dict:
    """Whether Related Topics is being served, and what it was built from.

    A reading beside the ledgers rather than an alert: a stale index is a state,
    not a failure. The Corpus stays fully examinable with no index at all, so
    this reports and never raises — including when there has never been one.
    """
    _guard(x_operator_token)
    from .deps import get_related_topics

    return get_related_topics().staleness.reading()


@router.get("/operator/sessions")
def sessions(x_operator_token: str | None = Header(default=None)) -> dict:
    _guard(x_operator_token)
    return {"sessions": OperatorService(wiring().engine).sessions()}


# -- shared Corpora ----------------------------------------------------------
#
# A shared Corpus is imported once and read by everybody, which is exactly the
# thing a Candidate must not be able to create: the `topic_id`s in it become the
# join key for everyone's Evidence, and a second one meaning the same thing
# would split a measurement in half without saying so.
#
# So the create route lives here, behind the operator credential, and the
# Candidate-facing `POST /notebooks` carries no visibility field at all. Not
# refused — unreachable.


class SharedCorpusIn(BaseModel):
    title: str = Field(min_length=1)


class SharedSourceIn(BaseModel):
    title: str = Field(min_length=1)
    text: str = ""
    media_type: str = "text/markdown"
    url: str = ""


@router.post("/operator/corpora", status_code=201)
def create_shared_corpus(
    body: SharedCorpusIn, x_operator_token: str | None = Header(default=None)
) -> dict:
    _guard(x_operator_token)
    import uuid

    from interviewer.db.content import PLATFORM_OWNER, SHARED

    from .deps import get_notebook_service, refresh_corpus

    svc = get_notebook_service()
    record = svc.create(
        f"nb-{uuid.uuid4().hex[:12]}", PLATFORM_OWNER, body.title,
        visibility=SHARED,
    )
    refresh_corpus()
    return {
        "notebook_id": record.notebook_id,
        "title": record.title,
        "visibility": record.visibility,
    }


@router.post("/operator/corpora/{notebook_id}/sources", status_code=201)
def add_shared_source(
    notebook_id: str,
    body: SharedSourceIn,
    x_operator_token: str | None = Header(default=None),
) -> dict:
    """Material into a shared Corpus. The one writer a shared Corpus has.

    Metered on the platform's own ledger rather than a Candidate's: the import
    is paid once, not per signup, which is half the reason shared exists.
    """
    _guard(x_operator_token)
    import uuid

    from .deps import get_notebook_service, refresh_corpus
    from .routes_notebooks import _added_out

    svc = get_notebook_service()
    try:
        added = svc.add_source(
            notebook_id,
            source_id=f"src-{uuid.uuid4().hex[:12]}",
            title=body.title,
            text=body.text,
            media_type=body.media_type,
            url=body.url,
            as_operator=True,
        )
    except LookupError:
        raise HTTPException(404, "unknown notebook_id") from None
    refresh_corpus()
    return _added_out(added)


class GivenLeafIn(BaseModel):
    leaf_id: str
    title: str = ""
    text: str
    #: content | prompt | ground_truth. Carried because Ground Truth decides a
    #: Module's Grading Mode ceiling, and an import that dropped it would
    #: downgrade every imported Module without reporting the loss.
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
    topics: list[GivenTopicIn] = Field(min_length=1)


@router.post("/operator/corpora/{notebook_id}/import", status_code=201)
def import_structured(
    notebook_id: str,
    body: ImportIn,
    x_operator_token: str | None = Header(default=None),
) -> dict:
    """Import material that already carries its Topics, ids and order.

    The one thing an import must not do is cluster: the ids it arrives with are
    the join key for every row of Evidence and Topic Confidence, and re-deriving
    them would produce a different set meaning something different by every one
    (ISSUE-0034).
    """
    _guard(x_operator_token)
    import uuid

    from interviewer.corpus.adapters.notebook.structured import GivenLeaf, GivenTopic

    from .deps import get_notebook_service, refresh_corpus
    from .routes_notebooks import _added_out

    svc = get_notebook_service()
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
    try:
        added = svc.import_structured(
            notebook_id,
            source_id=f"src-{uuid.uuid4().hex[:12]}",
            title=body.title,
            module_id=body.module_id,
            topics=topics,
            as_operator=True,
        )
    except LookupError:
        raise HTTPException(404, "unknown notebook_id") from None
    refresh_corpus()
    return _added_out(added)
