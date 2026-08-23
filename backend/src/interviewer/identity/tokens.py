"""Verifying a Gatehouse access token (ADR-0026).

Locally, against the published keys, and never by asking Gatehouse. A call to
the issuer on every request would make a Gatehouse outage an outage of this
product, which is the coupling verifying locally exists to remove.

Three claims are the whole of the check, and the second is the one that is
silent when it is missing:

- `iss` — from configuration, not a constant. A development Gatehouse issues
  under its own name, so a compiled-in production issuer rejects every token on
  a laptop and the failure reads as a signing problem.
- `aud` — our slug. Every tenant's tokens are signed by the same key and verify
  against the same JWKS, so a token minted for another product is
  cryptographically valid and passes every other check. Skip this and any
  member of any product is a Candidate here.
- `exp` — left to the library, which is what libraries are for.

What comes back is a subject, not a Candidate. `IdentityStore` turns one into
the other, and the separation is ADR-0012: `candidate_id` is ours, opaque, and
appears in no token.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_ISSUER = "https://auth.buildspacelabs.com"
DEFAULT_AUDIENCE = "interview-lm"


class InvalidToken(Exception):
    """The token is absent, malformed, expired, or minted for somebody else."""


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    """What a valid token says. Deliberately not a Candidate."""

    subject: str
    session: str
    issuer: str


def issuer(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    return (env.get("GATEHOUSE_ISSUER") or "").strip() or DEFAULT_ISSUER


def audience(env: dict | None = None) -> str:
    """Our slug, which is permanent and in the `aud` of every token minted for us."""
    env = os.environ if env is None else env
    return (env.get("GATEHOUSE_AUDIENCE") or "").strip() or DEFAULT_AUDIENCE


def jwks_url(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    explicit = (env.get("GATEHOUSE_JWKS_URL") or "").strip()
    return explicit or f"{issuer(env).rstrip('/')}/.well-known/jwks.json"


class TokenVerifier:
    """Verifies against a cached JWKS, refreshed on an unknown `kid`.

    On the key rather than on a timer: a rotation is invisible to us because
    the first token carrying the new `kid` is what fetches it, and a key that
    never rotates is never re-fetched. A timer would do both jobs worse.

    `keys` is injectable so the tests can mint their own without a network.
    """

    __slots__ = ("_issuer", "_audience", "_url", "_keys", "_client")

    def __init__(
        self,
        *,
        expect_issuer: str | None = None,
        expect_audience: str | None = None,
        url: str | None = None,
        keys=None,
    ) -> None:
        self._issuer = expect_issuer or issuer()
        self._audience = expect_audience or audience()
        self._url = url or jwks_url()
        self._keys = keys
        self._client = None

    def _signing_key(self, token: str, *, refresh: bool = False):
        if self._keys is not None:
            return self._keys(token)
        from jwt import PyJWKClient

        if self._client is None or refresh:
            self._client = PyJWKClient(self._url, cache_keys=True)
        return self._client.get_signing_key_from_jwt(token).key

    def verify(self, token: str) -> VerifiedToken:
        import jwt

        if not token:
            raise InvalidToken("no token")
        try:
            key = self._signing_key(token)
        except Exception:
            # An unknown `kid` is what a rotation looks like from here, and it
            # is indistinguishable from a stale cache. Re-fetch once; a second
            # failure is a real one.
            try:
                key = self._signing_key(token, refresh=True)
            except Exception as exc:
                raise InvalidToken(f"no signing key for this token: {exc}") from None
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except Exception as exc:
            # The reason is not told to the caller. A token that is expired, a
            # token for another tenant and a token signed by nobody are one
            # answer to whoever presented it, and three lines in the log.
            raise InvalidToken(str(exc)) from None
        return VerifiedToken(
            subject=claims["sub"],
            session=claims.get("sid", ""),
            issuer=claims["iss"],
        )
