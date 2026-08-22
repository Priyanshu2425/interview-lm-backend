from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from interviewer.metering.credits import LOW_BALANCE_WARN
from interviewer.metering.keyvault import RejectedKey

from .wiring import wiring

router = APIRouter(tags=["candidate"])


class KeyIn(BaseModel):
    candidate_id: str
    openrouter_key: str


class GrantIn(BaseModel):
    candidate_id: str
    credits: int
    payment_ref: str


@router.get("/candidates/{candidate_id}/confidence")
def confidence(candidate_id: str) -> dict:
    """Coverage and Mastery, as two separate readings. There is no field here
    that merges them."""
    return wiring().summary.candidate_readings(candidate_id)


@router.get("/providers/prices")
def provider_prices() -> dict:
    """What each Provider has actually cost per Topic, from history.

    Deliberately not an estimate of what a Session will cost: Topic material
    varies more than four-fold and the Candidate chooses the duration, so the
    total is not knowable before it runs.
    """
    from interviewer.metering.operator import PriceService

    return {
        "prices": PriceService(wiring().engine).per_visit(),
        "session_total_quotable": False,
        "why": (
            "Topic material varies more than four-fold across Modules and you "
            "choose the duration, so a Session's total is not knowable before "
            "it runs. You will see the real number after every Topic."
        ),
    }


@router.get("/candidates/{candidate_id}/weakest")
def weakest(candidate_id: str, limit: int = 10) -> dict:
    """Topics that look weakest, among those with enough evidence to say.

    Untested Topics are absent rather than ranked last — they are unknown, not
    weak.
    """
    return {"topics": wiring().summary.weakest(candidate_id, limit)}


@router.get("/candidates/{candidate_id}/credits")
def credits(candidate_id: str) -> dict:
    w = wiring()
    balance = w.credits.balance(candidate_id)
    key = w.vault.active(candidate_id)
    return {
        "balance": None if key else balance,
        "route": "byok" if key else "credits",
        "low_balance": (balance < LOW_BALANCE_WARN) if not key else False,
        "ledger": [
            {
                "entry_type": r["entry_type"],
                "delta_credits": r["delta_credits"],
                "topic_visit_id": r["topic_visit_id"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in w.credits.rows(candidate_id)
        ] if not key else [],
        "byok": None if not key else {
            "key_id": key.key_id,
            "fingerprint": key.fingerprint,
            "status": key.status,
            # A Candidate on their own key spends no Credits. Reported as null,
            # never as 0, which would read as "it was free".
            "credits_spent": None,
        },
    }


@router.post("/candidates/me/byok", status_code=201)
def attach_key(body: KeyIn) -> dict:
    try:
        k = wiring().vault.attach(body.candidate_id, body.openrouter_key)
    except RejectedKey as e:
        raise HTTPException(400, str(e)) from None
    return {"key_id": k.key_id, "fingerprint": k.fingerprint, "status": k.status}


@router.delete("/candidates/me/byok/{key_id}")
def revoke_key(key_id: str) -> dict:
    wiring().vault.revoke(key_id)
    return {"status": "revoked"}


@router.post("/credits/grants", status_code=201)
def grant(body: GrantIn) -> dict:
    """Consumes a *payment cleared* event and produces a grant. Payment
    processing itself is out of scope."""
    e = wiring().credits.grant(body.candidate_id, body.credits, body.payment_ref)
    return {"entry_id": e.id, "credits": e.delta, "already_granted": e.already_existed}
