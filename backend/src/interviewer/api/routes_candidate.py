from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from interviewer.metering.credits import LOW_BALANCE_WARN
from interviewer.metering.keyvault import RejectedKey

from .auth import current_candidate
from .routes_operator import _guard as operator_only
from .wiring import wiring

router = APIRouter(tags=["candidate"])


class KeyIn(BaseModel):
    """No candidate_id. Whose key it is comes from the token that carried it."""

    openrouter_key: str


class GrantIn(BaseModel):
    candidate_id: str
    credits: int
    payment_ref: str


@router.get("/candidates/me/confidence")
def confidence(candidate_id: str = Depends(current_candidate)) -> dict:
    """Coverage and Mastery, as two separate readings. There is no field here
    that merges them."""
    return wiring().summary.candidate_readings(candidate_id)


@router.get("/candidates/me/topics/{topic_id}/standing")
def topic_standing(topic_id: str, candidate_id: str = Depends(current_candidate)) -> dict:
    """Where this Candidate stands on one shared Topic (ISSUE-0036).

    Inside a Topic, and only inside one. Mastery means one thing there and needs
    no fusing, so ordering it costs nothing Principle 4 protects — whereas any
    figure spanning Topics would need Coverage and Mastery combined, and there
    is no such figure and no route that returns one.

    Where this reading *appears* is a human decision and is deliberately not
    taken here: a rank shown beside a score reads as "study these next", which
    is Topic recommendation, which does not exist.
    """
    from interviewer.confidence.comparison import rank_within_topic

    from .deps import get_notebook_service

    w = wiring()
    if not get_notebook_service().comparable_topic(topic_id):
        # A personal Corpus mints ids nobody else holds, so its cohort is one by
        # construction. Reported as a state rather than refused: "there is
        # nobody to compare you to" is the true answer, not an error.
        return {
            "topic_id": topic_id,
            "rank": None,
            "cohort": 0,
            "shared": False,
            "reason": (
                "this Topic is not part of a shared Library, so nobody else "
                "holds it — there is nobody to compare you to"
            ),
        }
    standing = rank_within_topic(
        topic_id,
        candidate_id=candidate_id,
        posteriors=w.deps.confidence.all_on_topic(topic_id),
    )
    return {
        "topic_id": standing.topic_id,
        "rank": standing.rank,
        "cohort": standing.cohort,
        # `#7= of 340` rather than `#7 of 340`: two Candidates the mathematics
        # cannot separate share a position.
        "shared": standing.shared,
        "reason": standing.reason,
    }


@router.get("/candidates/me/coverage-standing")
def coverage_standing(module_id: list[str] | None = None,
                      candidate_id: str = Depends(current_candidate)) -> dict:
    """Coverage compared as Coverage. A second, separate reading.

    Its own route, returning its own shape, so that combining it with a Topic
    rank into a position is something no caller can do by reading one response.
    """
    from interviewer.confidence.comparison import coverage_percentile

    from .deps import get_corpus, get_notebook_service

    svc = get_notebook_service()
    shared_topics = [
        topic.id
        for module in get_corpus().modules
        for topic in module.topics
        if svc.comparable_topic(topic.id)
    ]
    w = wiring()
    standing = coverage_percentile(
        candidate_id=candidate_id,
        examined=w.deps.confidence.examined_counts(shared_topics),
        topics_available=len(shared_topics),
    )
    return {
        "topics_examined": standing.topics_examined,
        "topics_available": standing.topics_available,
        "cohort": standing.cohort,
        "percentile": standing.percentile,
        "reason": standing.reason,
    }


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


@router.get("/candidates/me/weakest")
def weakest(limit: int = 10, candidate_id: str = Depends(current_candidate)) -> dict:
    """Topics that look weakest, among those with enough evidence to say.

    Untested Topics are absent rather than ranked last — they are unknown, not
    weak.
    """
    return {"topics": wiring().summary.weakest(candidate_id, limit)}


@router.get("/candidates/me/credits")
def credits(candidate_id: str = Depends(current_candidate)) -> dict:
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
def attach_key(body: KeyIn, candidate_id: str = Depends(current_candidate)) -> dict:
    try:
        k = wiring().vault.attach(candidate_id, body.openrouter_key)
    except RejectedKey as e:
        raise HTTPException(400, str(e)) from None
    return {"key_id": k.key_id, "fingerprint": k.fingerprint, "status": k.status}


@router.delete("/candidates/me/byok/{key_id}")
def revoke_key(key_id: str, candidate_id: str = Depends(current_candidate)) -> dict:
    if not wiring().vault.revoke(candidate_id, key_id):
        # Not "whose key is this" — a key that is not yours and a key that does
        # not exist are one answer, or the difference between them is a way to
        # enumerate the other.
        raise HTTPException(404, "no such key")
    return {"status": "revoked"}


@router.post("/credits/grants", status_code=201)
def grant(body: GrantIn, x_operator_token: str | None = Header(default=None)) -> dict:
    """Consumes a *payment cleared* event and produces a grant. Payment
    processing itself is out of scope.

    Operator-authenticated, and deliberately not Candidate-authenticated: a
    grant is made *about* somebody by whatever cleared their payment, never
    *by* them. Signing in is not evidence that money arrived, so a member's own
    token must not be able to mint Credits — for themselves or for anybody else.
    """
    operator_only(x_operator_token)
    e = wiring().credits.grant(body.candidate_id, body.credits, body.payment_ref)
    return {"entry_id": e.id, "credits": e.delta, "already_granted": e.already_existed}
