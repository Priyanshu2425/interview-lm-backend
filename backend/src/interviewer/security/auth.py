"""Who is asking (ADR-0026), and who that makes them here (ADR-0012).

Two steps that stay separate on purpose. Gatehouse says which *member* presented
the token; `IdentityStore` says which **Candidate** that is. The join is a row,
so a Candidate may hold several identities and changing provider repoints rows
rather than rewriting the permanent record.

Every Candidate-scoped endpoint depends on this and none of them takes an id
from the caller. That is the difference between a rule and a habit: a route
that wanted to trust a body would have to ask for it, in writing, where a
reviewer can see it.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..service.identity.store import IdentityStore
from ..adapters.gatehouse import InvalidToken, TokenVerifier
from ..exception.definitions import Refusal


@lru_cache(maxsize=1)
def verifier() -> TokenVerifier:
    """One verifier, so one JWKS cache. Rotation is invisible to the routes."""
    return TokenVerifier()


@lru_cache(maxsize=1)
def identities() -> IdentityStore:
    from ..wiring import wiring

    return IdentityStore(wiring().engine)


#: Declared as a scheme rather than as a header parameter, so it appears once
#: in the schema as security instead of on the parameter list of every route —
#: which is a list the design has opinions about. `auto_error=False` because the
#: refusal is ours: the surface renders from `code` and `message` (ADR-0009),
#: and FastAPI's own 403 carries neither.
scheme = HTTPBearer(auto_error=False, scheme_name="Gatehouse")


def current_candidate(
    credentials: HTTPAuthorizationCredentials | None = Depends(scheme),
) -> str:
    """The Candidate this request is for. Never the one it asked to be.

    The refusal is one sentence whatever went wrong. Expired, forged, and minted
    for another product are the same answer to whoever presented it — telling
    them which would be telling them how to get closer.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise Refusal(401, "not_signed_in", "Sign in to continue.")
    token = (credentials.credentials or "").strip()
    if not token:
        raise Refusal(401, "not_signed_in", "Sign in to continue.")
    try:
        claims = verifier().verify(token)
    except InvalidToken:
        raise Refusal(401, "not_signed_in", "Sign in to continue.") from None
    return identities().resolve(issuer=claims.issuer, subject=claims.subject).candidate_id
