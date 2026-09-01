"""Session routes (async). The Answer Turn is a request, not a socket (ADR-0011)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from interviewer.service.graph.sessions import SessionConfig
from interviewer.service.graph.runner import SessionRunner

from ...security.auth import current_candidate
from ...idempotency import once
from ...wiring import wiring
from ...deps_async import (
    get_async_session_store,
    get_async_visit_lifecycle,
    get_async_evidence_ledger,
    get_async_confidence_store,
    get_async_binding_store,
    get_async_credit_ledger,
    get_async_key_vault,
    get_async_corpus_service,
    get_async_dossier_loader,
)

if TYPE_CHECKING:
    # Annotations only. Imported under the guard because these are the
    # dependency types, not the dependency: FastAPI takes the object from
    # `Depends`, and a plain import here would be a second edge into the
    # repository package for no runtime gain.
    from ...repository.async_repositories import (
        AsyncBindingStore,
        AsyncDossierLoader,
        AsyncConfidenceStore,
        AsyncCorpusService,
        AsyncCreditLedger,
        AsyncEvidenceLedger,
        AsyncKeyVault,
        AsyncSessionStore,
        AsyncVisitLifecycle,
    )

router = APIRouter(tags=["sessions"])


class StartIn(BaseModel):
    """No candidate_id. A Session is started by whoever presented the token."""

    module_ids: list[str] = Field(min_length=1)
    duration_seconds: int = Field(gt=0)
    provider: str = "deepseek"
    # Omitted means "whatever this Candidate's key situation implies". The
    # surface holds no invariant (ADR-0009), and which key pays is one.
    payment_route: str | None = None


class TurnIn(BaseModel):
    answer: str


class TurnOut(BaseModel):
    """No field here fuses Coverage and Mastery, and none carries an Answer Key."""

    kind: str
    payload: dict


async def _get_owned_session(
    session_id: str,
    candidate_id: str,
    sessions: AsyncSessionStore,
) -> dict:
    """The Session, if it is this Candidate's. A 404 either way."""
    row = await sessions.get(session_id)
    if not row or row["candidate_id"] != candidate_id:
        raise HTTPException(404, "unknown session")
    return row


@router.post("/sessions", status_code=201)
async def start(
    body: StartIn,
    candidate_id: str = Depends(current_candidate),
    sessions: AsyncSessionStore = Depends(get_async_session_store),
    visits: AsyncVisitLifecycle = Depends(get_async_visit_lifecycle),
    evidence: AsyncEvidenceLedger = Depends(get_async_evidence_ledger),
    confidence: AsyncConfidenceStore = Depends(get_async_confidence_store),
    bindings: AsyncBindingStore = Depends(get_async_binding_store),
    credits: AsyncCreditLedger = Depends(get_async_credit_ledger),
    keyvault: AsyncKeyVault = Depends(get_async_key_vault),
    corpus: AsyncCorpusService = Depends(get_async_corpus_service),
    runner: SessionRunner = Depends(lambda: wiring().runner),
) -> dict:
    """The route is settled here, once, and then belongs to the Session.

    It is decided from the Key Vault rather than taken on the client's word: an
    attached key is the Candidate paying their own Provider, and a Session that
    billed Credits against an attached key would be charging twice over.
    """
    # A Module holding no Topic cannot be examined, and a Session scoped to one
    # would end before it began. Refused here rather than discovered later.
    unusable = [m for m in body.module_ids if not corpus.topic_ids_for([m])]
    if unusable:
        raise HTTPException(
            422,
            f"these modules hold no examinable Topic: {', '.join(sorted(unusable))}",
        )
    key = await keyvault.active(candidate_id)
    route = body.payment_route or ("byok" if key else "credits")
    if route == "byok" and key is None:
        raise HTTPException(409, "no active key is attached for this candidate")
    if key is not None and route == "credits":
        route = "byok"

    cfg = SessionConfig(
        scope_module_ids=tuple(body.module_ids),
        duration_seconds=body.duration_seconds,
        provider=body.provider,
        payment_route=route,
    )
    sid, first = runner.start(
        candidate_id=candidate_id, cfg=cfg,
        byok_key_id=key.key_id if key else None,
    )
    return {"session_id": sid, "kind": first.kind,
            "payment_route": route, **first.payload}


@router.post("/sessions/{session_id}/turns", response_model=TurnOut)
async def turn(
    session_id: str,
    body: TurnIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    candidate_id: str = Depends(current_candidate),
    sessions: AsyncSessionStore = Depends(get_async_session_store),
    runner: SessionRunner = Depends(lambda: wiring().runner),
) -> TurnOut:
    """Long-running: returns when the graph next parks.

    Idempotent on its key, so a mashed submit button, a flaky network and a
    browser refresh all converge on one Answer Turn.
    """
    await _get_owned_session(session_id, candidate_id, sessions)

    def run():
        r = runner.submit(session_id, body.answer)
        return TurnOut(kind=r.kind, payload=r.payload)

    return once(f"{session_id}:{idempotency_key}", run) if idempotency_key else run()


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    candidate_id: str = Depends(current_candidate),
    sessions: AsyncSessionStore = Depends(get_async_session_store),
    visits: AsyncVisitLifecycle = Depends(get_async_visit_lifecycle),
    runner: SessionRunner = Depends(lambda: wiring().runner),
) -> dict:
    row = await _get_owned_session(session_id, candidate_id, sessions)
    pending = runner.pending(session_id)
    visits_list = await visits.for_session(session_id)
    return {
        "session_id": session_id,
        "state": row["state"],
        "parked_reason": row["parked_reason"],
        "ended_reason": row["ended_reason"],
        "duration_seconds": row["duration_seconds"],
        "provider": row["provider_chosen"],
        "payment_route": row["payment_route"],
        "visits": [
            {
                "topic_visit_id": v["topic_visit_id"],
                "topic_id": v["topic_id"],
                "state": v["state"],
                "grading_mode": v["grading_mode"],
                "turn_count": v["turn_count"],
            }
            for v in visits_list
        ],
        "pending": pending,
    }


@router.get("/sessions/{session_id}/plan")
async def plan(
    session_id: str,
    candidate_id: str = Depends(current_candidate),
    sessions: AsyncSessionStore = Depends(get_async_session_store),
    loader: AsyncDossierLoader = Depends(get_async_dossier_loader),
) -> dict:
    """What this Session will ask, decided before it asked anything.

    Read twice, this returns the same bytes: the plan is fixed at the database
    (`trg_plan_item_fixed`), the items come back in `item_order`, and there is
    no writer on this path. The Candidate can see the shape of their Session in
    advance, which is what fixing the plan bought.

    Titles are resolved here rather than stored on the item. A stored title is a
    copy of the Corpus that goes stale when a Topic is renamed, and the plan is
    fixed on `topic_ids` — the identity — not on how they were captioned.
    """
    await _get_owned_session(session_id, candidate_id, sessions)
    stored = await sessions.plan(session_id)
    if stored is None:
        raise HTTPException(404, "this session has no plan")

    def title(topic_id: str) -> str:
        try:
            return loader.load(topic_id).topic_title
        except LookupError:
            # A Topic retired since the plan was fixed. It keeps its place in
            # the plan under its id rather than vanishing from it.
            return topic_id

    return {
        **stored,
        "items": [
            {**item, "topic_titles": [title(t) for t in item["topic_ids"]]}
            for item in stored["items"]
        ],
    }


@router.get("/sessions/{session_id}/transcript")
async def transcript(
    session_id: str,
    candidate_id: str = Depends(current_candidate),
    sessions: AsyncSessionStore = Depends(get_async_session_store),
) -> dict:
    """Everything that was said, in order (ISSUE-0042).

    A transcript, not a report: every question, probe, hint and answer, each
    labelled with the `kind` the loop knew and the `topic_ids` the plan fixed.
    No score appears here, because while a Session is running there is none —
    it is graded once, at the end.
    """
    await _get_owned_session(session_id, candidate_id, sessions)
    return {
        "session_id": session_id,
        "messages": await sessions.transcript(session_id),
    }


@router.post("/sessions/{session_id}/resume")
async def resume(
    session_id: str,
    candidate_id: str = Depends(current_candidate),
    sessions: AsyncSessionStore = Depends(get_async_session_store),
    runner: SessionRunner = Depends(lambda: wiring().runner),
) -> dict:
    await _get_owned_session(session_id, candidate_id, sessions)
    out = runner.resume_after_interruption(session_id)
    if out is None:
        raise HTTPException(409, "nothing to resume")
    return {"kind": out.kind, **out.payload}


@router.post("/sessions/{session_id}/end")
async def end(
    session_id: str,
    candidate_id: str = Depends(current_candidate),
    sessions: AsyncSessionStore = Depends(get_async_session_store),
    visits: AsyncVisitLifecycle = Depends(get_async_visit_lifecycle),
    runner: SessionRunner = Depends(lambda: wiring().runner),
) -> dict:
    """Soft: the question being asked completes first.

    `being_asked` rather than `unresolved` since ISSUE-0042: an answered
    question is finished, and waiting for it to be graded would mean a Session
    could never be ended early once it had answered anything.
    """
    row = await _get_owned_session(session_id, candidate_id, sessions)
    open_visit = await visits.being_asked(session_id)
    if open_visit:
        return {
            "state": row["state"],
            "note": "this Topic will finish before the Session ends",
            "topic_visit_id": open_visit["topic_visit_id"],
        }
    await sessions.end(session_id, "candidate_ended")
    return {"state": "ended", "reason": "candidate_ended"}


@router.get("/sessions/{session_id}/spend")
async def spend(
    session_id: str,
    candidate_id: str = Depends(current_candidate),
    sessions: AsyncSessionStore = Depends(get_async_session_store),
    visits: AsyncVisitLifecycle = Depends(get_async_visit_lifecycle),
    credits: AsyncCreditLedger = Depends(get_async_credit_ledger),
) -> dict:
    """A running total, so a Candidate can end early if it is costing more than
    they expected."""
    row = await _get_owned_session(session_id, candidate_id, sessions)
    visits_list = await visits.for_session(session_id)
    byok = row["payment_route"] != "credits"
    # Planning is a model call and therefore a charge, and it belongs to no
    # Visit — so a total built only from Visits would be smaller than what the
    # ledger actually took. It is reported on its own line rather than folded
    # into a Visit that did not make it (ISSUE-0041).
    planning = None if byok else await credits.visit_cost(f"plan_{session_id}")
    return {
        "route": row["payment_route"],
        # BYOK and MCP carry null, never 0 — zero reads as "it was free".
        # A list, not a generator: `await` inside a bare genexp makes an async
        # generator, and `sum` cannot consume one.
        "credits": None if byok else planning + sum(
            [await credits.visit_cost(v["topic_visit_id"]) for v in visits_list]
        ),
        "planning": planning,
        "balance": None if byok else await credits.balance(row["candidate_id"]),
        "per_visit": [
            {
                "topic_visit_id": v["topic_visit_id"],
                "topic_id": v["topic_id"],
                "state": v["state"],
                "credits": None if byok else await credits.visit_cost(v["topic_visit_id"]),
            }
            for v in visits_list
        ],
    }


@router.get("/sessions/{session_id}/summary")
async def summary(
    session_id: str,
    candidate_id: str = Depends(current_candidate),
    sessions: AsyncSessionStore = Depends(get_async_session_store),
) -> dict:
    row = await _get_owned_session(session_id, candidate_id, sessions)
    from dataclasses import asdict

    return asdict(wiring().summary.for_session(row))