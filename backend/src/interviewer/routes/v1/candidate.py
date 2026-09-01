"""Candidate routes (async)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from interviewer.service.metering.credits import LOW_BALANCE_WARN
from interviewer.service.metering.keyvault import RejectedKey

from ...security.auth import current_candidate
from ...wiring import wiring
from .operator import _guard as operator_only
from ...deps_async import (
    get_async_confidence_store,
    get_async_credit_ledger,
    get_async_key_vault,
    get_async_corpus,
    get_async_corpus_service,
    get_async_related_topics,
    get_async_notebook_service,
    get_async_session_store,
)

if TYPE_CHECKING:
    # Annotations only. Imported under the guard because these are the
    # dependency types, not the dependency: FastAPI takes the object from
    # `Depends`, and a plain import here would be a second edge into the
    # repository package for no runtime gain.
    from ...repository.async_repositories import (
        AsyncConfidenceStore,
        AsyncCorpus,
        AsyncCorpusService,
        AsyncCreditLedger,
        AsyncKeyVault,
        AsyncNotebookService,
        AsyncSessionStore,
    )

router = APIRouter(tags=["candidate"])


class KeyIn(BaseModel):
    """No candidate_id. Whose key it is comes from the token that carried it."""

    openrouter_key: str


class OnboardingIn(BaseModel):
    """What the form asks. No candidate_id, and nothing ADR-0026 refuses.

    Whose answers these are comes from the token, as everywhere else under
    `/candidates/me`. There is no field here for a credential or an address, and
    a body carrying one is refused rather than ignored — the surface should hear
    about it at the point it sent it, not discover the value never arrived.

    A PATCH, and it means it: an omitted field is left as it was rather than
    reset to its default. A person correcting one answer should not have to
    restate the other three, and a form that posts only what changed should not
    be able to erase what it did not ask about.
    """

    model_config = {"extra": "forbid"}

    display_name: str | None = None
    target_role: str | None = None
    experience_level: str | None = None
    goal: str | None = None


class GrantIn(BaseModel):
    candidate_id: str
    credits: int
    payment_ref: str


def _me(row: dict | None, candidate_id: str) -> dict:
    """The `/me` reading, from a row that may not exist yet.

    Three fields and no more. The three answers the form collects are not
    returned, because nothing reads them and a value on the wire is a value
    something will start depending on.

    `onboarded` is derived here rather than stored beside the timestamp: one
    fact, so there is no second one to fall out of step with it. A Candidate the
    row has never seen and one who has never finished the form are the same
    answer — `false` — which is the answer the surface needs either way.
    """
    return {
        "candidate_id": candidate_id,
        "display_name": (row or {}).get("display_name"),
        "onboarded": bool(row and row.get("onboarded_at")),
    }


@router.get("/candidates/me")
async def me(
    candidate_id: str = Depends(current_candidate),
    sessions: AsyncSessionStore = Depends(get_async_session_store),
) -> dict:
    """Who the surface is looking at, and whether it has ever been told.

    Read-only on purpose: a real token has already minted the row on its way
    through `IdentityStore.resolve`, so a GET that also inserted would exist
    only for a case that cannot happen — and a first authenticated load is the
    last place to hide a write.
    """
    return _me(await sessions.profile(candidate_id), candidate_id)


@router.patch("/candidates/me")
async def onboard(
    body: OnboardingIn,
    candidate_id: str = Depends(current_candidate),
    sessions: AsyncSessionStore = Depends(get_async_session_store),
) -> dict:
    """The Candidate tells us who they are (ISSUE-0048).

    Idempotent in the way that matters: the answers are whatever was last sent,
    and `onboarded_at` is stamped once and never moved. A second PATCH is a
    correction, not a second completion.
    """
    await sessions.ensure_candidate(candidate_id)
    row = await sessions.record_onboarding(
        candidate_id, body.model_dump(exclude_unset=True)
    )
    return _me(row, candidate_id)


@router.get("/candidates/me/confidence")
async def confidence(
    candidate_id: str = Depends(current_candidate),
    # SummaryService still uses sync - use wiring for now
) -> dict:
    """Coverage and Mastery, as two separate readings. There is no field here
    that merges them."""
    return wiring().summary.candidate_readings(candidate_id)


@router.get("/candidates/me/topics/{topic_id}/standing")
async def topic_standing(
    topic_id: str,
    candidate_id: str = Depends(current_candidate),
    confidence: AsyncConfidenceStore = Depends(get_async_confidence_store),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> dict:
    """Where this Candidate stands on one shared Topic (ISSUE-0036)."""
    from interviewer.service.confidence.comparison import rank_within_topic

    if not await notebook_service.store.comparable_topic(topic_id):
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
    posteriors = await confidence.all_on_topic(topic_id)
    standing = rank_within_topic(
        topic_id,
        candidate_id=candidate_id,
        posteriors=posteriors,
    )
    return {
        "topic_id": standing.topic_id,
        "rank": standing.rank,
        "cohort": standing.cohort,
        "shared": standing.shared,
        "reason": standing.reason,
    }


@router.get("/candidates/me/coverage-standing")
async def coverage_standing(
    module_id: list[str] | None = None,
    candidate_id: str = Depends(current_candidate),
    corpus: AsyncCorpus = Depends(get_async_corpus),
    confidence: AsyncConfidenceStore = Depends(get_async_confidence_store),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> dict:
    """Coverage compared as Coverage. A second, separate reading."""
    from interviewer.service.confidence.comparison import coverage_percentile

    svc = notebook_service
    shared_topics = [
        topic.id
        for module in corpus.modules
        for topic in module.topics
        if await svc.store.comparable_topic(topic.id)
    ]
    standing = coverage_percentile(
        candidate_id=candidate_id,
        examined=await confidence.examined_counts(shared_topics),
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
async def provider_prices() -> dict:
    """What each Provider has actually cost per Topic, from history."""
    from interviewer.service.metering.operator import PriceService

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
async def weakest(
    limit: int = 10,
    candidate_id: str = Depends(current_candidate),
) -> dict:
    """Topics that look weakest, among those with enough evidence to say."""
    return {"topics": wiring().summary.weakest(candidate_id, limit)}


@router.get("/candidates/me/credits")
async def credits(
    candidate_id: str = Depends(current_candidate),
    credits: AsyncCreditLedger = Depends(get_async_credit_ledger),
    keyvault: AsyncKeyVault = Depends(get_async_key_vault),
) -> dict:
    balance = await credits.balance(candidate_id)
    key = await keyvault.active(candidate_id)
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
            for r in await credits.entries_for(candidate_id)
        ] if not key else [],
        "byok": None if not key else {
            "key_id": key.key_id,
            "fingerprint": key.fingerprint,
            "status": key.status,
            "credits_spent": None,
        },
    }


@router.post("/candidates/me/byok", status_code=201)
async def attach_key(
    body: KeyIn,
    candidate_id: str = Depends(current_candidate),
    keyvault: AsyncKeyVault = Depends(get_async_key_vault),
) -> dict:
    try:
        k = await keyvault.attach(candidate_id, body.openrouter_key)
    except RejectedKey as e:
        raise HTTPException(400, str(e)) from None
    return {"key_id": k.key_id, "fingerprint": k.fingerprint, "status": k.status}


@router.delete("/candidates/me/byok/{key_id}")
async def revoke_key(
    key_id: str,
    candidate_id: str = Depends(current_candidate),
    keyvault: AsyncKeyVault = Depends(get_async_key_vault),
) -> dict:
    if not await keyvault.revoke(candidate_id, key_id):
        raise HTTPException(404, "no such key")
    return {"status": "revoked"}


@router.post("/credits/grants", status_code=201)
async def grant(
    body: GrantIn,
    x_operator_token: str | None = Header(default=None),
    credits: AsyncCreditLedger = Depends(get_async_credit_ledger),
) -> dict:
    """Consumes a *payment cleared* event and produces a grant."""
    operator_only(x_operator_token)
    e = await credits.grant(
        candidate_id=body.candidate_id,
        credits=body.credits,
        payment_ref=body.payment_ref,
    )
    return {"entry_id": e.id, "credits": e.delta, "already_granted": e.already_existed}