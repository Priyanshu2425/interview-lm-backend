"""Session routes. The Answer Turn is a request, not a socket (ADR-0011)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from interviewer.graph.sessions import SessionConfig

from .auth import current_candidate
from .idempotency import once
from .wiring import wiring

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


@router.post("/sessions", status_code=201)
def start(body: StartIn, candidate_id: str = Depends(current_candidate)) -> dict:
    """The route is settled here, once, and then belongs to the Session.

    It is decided from the Key Vault rather than taken on the client's word: an
    attached key is the Candidate paying their own Provider, and a Session that
    billed Credits against an attached key would be charging twice over.
    """
    w = wiring()
    # A Module holding no Topic cannot be examined, and a Session scoped to one
    # would end before it began. Refused here rather than discovered later.
    unusable = [m for m in body.module_ids if not w.deps.corpus.topic_ids_for([m])]
    if unusable:
        raise HTTPException(
            422,
            f"these modules hold no examinable Topic: {', '.join(sorted(unusable))}",
        )
    key = w.vault.active(candidate_id)
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
    sid, first = w.runner.start(
        candidate_id=candidate_id, cfg=cfg,
        byok_key_id=key.key_id if key else None,
    )
    return {"session_id": sid, "kind": first.kind,
            "payment_route": route, **first.payload}


def _owned(session_id: str, candidate_id: str) -> dict:
    """The Session, if it is this Candidate's. A 404 either way.

    A session id is opaque but it is not a secret: it comes back from
    `POST /sessions` and travels wherever that response goes. So the check is
    ownership, not existence — and the two answers are one answer, because the
    difference between "no such Session" and "not yours" is a way to learn
    which ids are real.
    """
    row = wiring().sessions.get(session_id)
    if not row or row["candidate_id"] != candidate_id:
        raise HTTPException(404, "unknown session")
    return row


@router.post("/sessions/{session_id}/turns", response_model=TurnOut)
def turn(
    session_id: str,
    body: TurnIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    candidate_id: str = Depends(current_candidate),
) -> TurnOut:
    """Long-running: returns when the graph next parks.

    Idempotent on its key, so a mashed submit button, a flaky network and a
    browser refresh all converge on one Answer Turn.
    """
    w = wiring()
    _owned(session_id, candidate_id)

    def run():
        r = w.runner.submit(session_id, body.answer)
        return TurnOut(kind=r.kind, payload=r.payload)

    return once(f"{session_id}:{idempotency_key}", run) if idempotency_key else run()


@router.get("/sessions/{session_id}")
def get_session(session_id: str,
                candidate_id: str = Depends(current_candidate)) -> dict:
    w = wiring()
    row = _owned(session_id, candidate_id)
    pending = w.runner.pending(session_id)
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
            for v in w.deps.visits.for_session(session_id)
        ],
        "pending": pending,
    }


@router.post("/sessions/{session_id}/resume")
def resume(session_id: str,
           candidate_id: str = Depends(current_candidate)) -> dict:
    w = wiring()
    _owned(session_id, candidate_id)
    out = w.runner.resume_after_interruption(session_id)
    if out is None:
        raise HTTPException(409, "nothing to resume")
    return {"kind": out.kind, **out.payload}


@router.post("/sessions/{session_id}/end")
def end(session_id: str, candidate_id: str = Depends(current_candidate)) -> dict:
    """Soft: the current Topic Visit completes first."""
    w = wiring()
    row = _owned(session_id, candidate_id)
    open_visit = w.deps.visits.unresolved(session_id)
    if open_visit:
        return {
            "state": row["state"],
            "note": "this Topic will finish before the Session ends",
            "topic_visit_id": open_visit["topic_visit_id"],
        }
    w.sessions.end(session_id, "candidate_ended")
    return {"state": "ended", "reason": "candidate_ended"}


@router.get("/sessions/{session_id}/spend")
def spend(session_id: str,
          candidate_id: str = Depends(current_candidate)) -> dict:
    """A running total, so a Candidate can end early if it is costing more than
    they expected."""
    w = wiring()
    row = _owned(session_id, candidate_id)
    visits = w.deps.visits.for_session(session_id)
    byok = row["payment_route"] != "credits"
    return {
        "route": row["payment_route"],
        # BYOK and MCP carry null, never 0 — zero reads as "it was free".
        "credits": None if byok else sum(
            w.credits.visit_cost(v["topic_visit_id"]) for v in visits
        ),
        "balance": None if byok else w.credits.balance(row["candidate_id"]),
        "per_visit": [
            {
                "topic_visit_id": v["topic_visit_id"],
                "topic_id": v["topic_id"],
                "state": v["state"],
                "credits": None if byok else w.credits.visit_cost(v["topic_visit_id"]),
            }
            for v in visits
        ],
    }


@router.get("/sessions/{session_id}/summary")
def summary(session_id: str,
            candidate_id: str = Depends(current_candidate)) -> dict:
    w = wiring()
    row = _owned(session_id, candidate_id)
    from dataclasses import asdict

    return asdict(w.summary.for_session(row))
