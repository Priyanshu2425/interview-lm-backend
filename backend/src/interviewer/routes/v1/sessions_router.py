"""Session routes (async). The Answer Turn is a request, not a socket (ADR-0011)."""

from __future__ import annotations
from interviewer.model.spend_models import SessionSpend, VisitCost

from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from interviewer.service.ending_service import EndReason
from interviewer.service.graph.sessions import SessionConfig
from interviewer.service.graph.runner_service import SessionRunner

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
)

if TYPE_CHECKING:
    # Annotations only. Imported under the guard because these are the
    # dependency types, not the dependency: FastAPI takes the object from
    # `Depends`, and a plain import here would be a second edge into the
    # repository package for no runtime gain.
    from ...repository.async_repositories import (
        AsyncBindingStore,
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
    # Omitted means "whatever this Candidate's key situation implies"; named
    # means the Candidate chose, and the choice is obeyed. `mcp` is not on the
    # list because it is not a Candidate's to pick — the MCP surface sets it.
    payment_route: Literal["credits", "byok"] | None = None


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

    A Candidate who names a route gets it. What the Key Vault decides is the
    *default* — an attached key means the Candidate is paying their own
    Provider unless they say otherwise — and the one thing it still refuses is
    `byok` with no key to spend, because there is nothing to bill against.

    Choosing Credits with a key attached is not a double charge: the two routes
    use different keys. Under `credits` the call goes out on ours and the cents
    land on the Candidate's ledger; under `byok` it goes out on theirs and the
    ledger records nothing. The key is left unused, not billed twice.
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

    cfg = SessionConfig(
        scope_module_ids=tuple(body.module_ids),
        duration_seconds=body.duration_seconds,
        provider=body.provider,
        payment_route=route,
    )
    # Carried only by the route that spends it. A Credits Session that named a
    # key in its bindings would say a key was used to buy what our own key
    # bought.
    sid, first = runner.start(
        candidate_id=candidate_id, cfg=cfg,
        byok_key_id=key.key_id if key and route == "byok" else None,
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


@router.get("/sessions")
async def list_sessions(
    candidate_id: str = Depends(current_candidate),
    sessions: AsyncSessionStore = Depends(get_async_session_store),
) -> dict:
    """Every Session this Candidate has sat, newest first.

    What a row says is what happened — when, for how long, over which Modules,
    how far into its plan it got, and how many Topics it measured. What no row
    says is how it went: there is no figure for a Session as a whole, and
    `SessionReport` has no field that could hold one.

    The three states are three different facts. A Session that is **running**
    resumes. One that **ended** is graded and has a report. One that is
    **parked** is waiting rather than finished, so it has not been graded and
    has nothing to report — topping up Credits carries it on.
    """
    rows = await sessions.for_candidate(candidate_id)
    return {
        "sessions": [
            {
                "session_id": r["session_id"],
                "state": r["state"],
                "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                "ended_at": r["ended_at"].isoformat() if r["ended_at"] else None,
                "duration_seconds": r["duration_seconds"],
                "provider": r["provider_chosen"],
                "payment_route": r["payment_route"],
                "module_ids": list(r["scope_module_ids"] or []),
                "ended_reason": r["ended_reason"],
                "parked_reason": r["parked_reason"],
                # Null rather than zero where a Session has no plan: MCP Mode's
                # do not, and neither does anything older than the planner. A
                # zero would read as a plan that asked nothing.
                "budget_questions": r["budget_questions"],
                "questions_asked": int(r["asked"] or 0),
                # Evidence rows. A count of what was measured, never a score.
                "topics_measured": int(r["measured"] or 0),
            }
            for r in rows
        ]
    }


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
) -> dict:
    """What this Session will ask, decided before it asked anything.

    Read twice, this returns the same bytes: the plan is fixed at the database
    (`trg_plan_item_fixed`), the items come back in `item_order`, and there is
    no writer on this path. The Candidate can see the shape of their Session in
    advance, which is what fixing the plan bought.

    The plan is shaped by `SessionReadingService`, which is where `/report`
    takes it from as well. It was shaped here too until the two shapes started
    disagreeing about what a plan item looks like, and a third copy of the
    retired-Topic title rule lived in this handler.
    """
    await _get_owned_session(session_id, candidate_id, sessions)
    stored = wiring().reading.plan_view(session_id)
    if stored is None:
        raise HTTPException(404, "this session has no plan")
    return stored


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

    Ending is also grading (ISSUE-0044), and both halves belong to
    `SessionEnding` — the module the graph's last node closes through too. A
    Session ended here and one ended by the clock reach the same Evidence rows,
    in the same order, because it is the same call.

    The row is marked ended by that module rather than here. Marking it on this
    engine and grading on the graph's is two transactions in the wrong order:
    the grader would read the Session before the end was committed.
    """
    row = await _get_owned_session(session_id, candidate_id, sessions)
    open_visit = await visits.being_asked(session_id)
    if open_visit:
        return {
            "state": row["state"],
            "note": "this Topic will finish before the Session ends",
            "topic_visit_id": open_visit["topic_visit_id"],
        }
    ended = wiring().ending.close(session_id, EndReason.CANDIDATE_ENDED.value)
    return {
        "state": ended.state,
        "reason": ended.reason,
        "graded": len(ended.graded),
    }


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
    # A list, not a bare genexp: `await` inside one makes an async generator,
    # and `tuple` cannot consume that.
    visit_costs = [
        VisitCost(
            topic_visit_id=v["topic_visit_id"],
            topic_id=v["topic_id"],
            state=v["state"],
            credits=None if byok else await credits.visit_cost(v["topic_visit_id"]),
        )
        for v in visits_list
    ]
    spend = SessionSpend(
        route=row["payment_route"],
        planning=None if byok else await credits.visit_cost(f"plan_{session_id}"),
        visits=tuple(visit_costs),
        balance=None if byok else await credits.balance(row["candidate_id"]),
    )
    return {
        "route": spend.route,
        "credits": spend.credits,
        "planning": spend.planning,
        "balance": spend.balance,
        "per_visit": [
            {
                "topic_visit_id": v.topic_visit_id,
                "topic_id": v.topic_id,
                "state": v.state,
                "credits": v.credits,
            }
            for v in spend.visits
        ],
    }


@router.get("/sessions/{session_id}/report")
async def report(
    session_id: str,
    candidate_id: str = Depends(current_candidate),
    sessions: AsyncSessionStore = Depends(get_async_session_store),
) -> dict:
    """The Session's result, in one place (ISSUE-0045).

    The plan as it was fixed and what became of each item, a reading per
    reached Topic, and the Topics that were planned and never reached — named,
    with nothing scored against them. A Session that reached nothing still
    answers: an empty reading is a reading, and a 404 here would read as "no
    such Session".

    Nothing on this path writes, so the same Session reports the same twice.
    """
    row = await _get_owned_session(session_id, candidate_id, sessions)
    from dataclasses import asdict

    reading = wiring().reading
    return asdict(reading.report_of(reading.of_row(row)))


@router.get("/sessions/{session_id}/summary")
async def summary(
    session_id: str,
    candidate_id: str = Depends(current_candidate),
    sessions: AsyncSessionStore = Depends(get_async_session_store),
) -> dict:
    row = await _get_owned_session(session_id, candidate_id, sessions)
    from dataclasses import asdict

    reading = wiring().reading
    return asdict(reading.summary_of(reading.of_row(row)))