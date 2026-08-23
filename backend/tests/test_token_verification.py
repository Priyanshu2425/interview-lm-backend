"""ISSUE-0011 / ADR-0026 — a Gatehouse token, verified here rather than asked about.

Real RS256 throughout. A test that mocks the verification proves the mock, and
the one claim that matters here is silent when it is wrong: a token minted for
another tenant is signed by the same key, verifies against the same JWKS, and
passes every check except `aud`.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from interviewer.identity.tokens import (
    InvalidToken,
    TokenVerifier,
    audience,
    issuer,
    jwks_url,
)

ISS = "https://auth.buildspacelabs.com"
AUD = "interview-lm"


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def mint(key, *, iss=ISS, aud=AUD, sub="member-uuid", sid="session-uuid",
         exp_in=900, kid="2026-08", **extra):
    now = int(time.time())
    claims = {"iss": iss, "aud": aud, "sub": sub, "sid": sid,
              "iat": now, "exp": now + exp_in, **extra}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def verifier(key, **kw):
    return TokenVerifier(expect_issuer=ISS, expect_audience=AUD,
                         keys=lambda _t: key.public_key(), **kw)


def test_a_valid_token_yields_a_subject_and_a_session(key):
    v = verifier(key).verify(mint(key))
    assert v.subject == "member-uuid"
    assert v.session == "session-uuid"
    assert v.issuer == ISS


def test_a_token_for_another_tenant_is_refused(key):
    """The whole reason `aud` is checked: same key, same JWKS, different product."""
    with pytest.raises(InvalidToken):
        verifier(key).verify(mint(key, aud="moorings"))


def test_a_token_from_another_issuer_is_refused(key):
    with pytest.raises(InvalidToken):
        verifier(key).verify(mint(key, iss="https://auth.somewhere.else"))


def test_an_expired_token_is_refused(key):
    with pytest.raises(InvalidToken):
        verifier(key).verify(mint(key, exp_in=-1))


def test_a_token_signed_by_somebody_else_is_refused(key, other_key):
    with pytest.raises(InvalidToken):
        verifier(key).verify(mint(other_key))


def test_an_unsigned_token_is_refused(key):
    """`alg: none` is the oldest trick there is, and RS256-only is what refuses it."""
    forged = jwt.encode({"iss": ISS, "aud": AUD, "sub": "x", "exp": int(time.time()) + 60},
                        key=None, algorithm="none")
    with pytest.raises(InvalidToken):
        verifier(key).verify(forged)


def test_a_token_missing_a_required_claim_is_refused(key):
    now = int(time.time())
    without_sub = jwt.encode({"iss": ISS, "aud": AUD, "exp": now + 60},
                             key, algorithm="RS256", headers={"kid": "2026-08"})
    with pytest.raises(InvalidToken):
        verifier(key).verify(without_sub)


def test_nothing_is_not_a_token(key):
    with pytest.raises(InvalidToken):
        verifier(key).verify("")


def test_the_refusal_says_nothing_about_which_check_failed(key, other_key):
    """One answer to whoever presented it, three lines in the log."""
    reasons = set()
    for token in (mint(key, aud="moorings"), mint(key, exp_in=-1), mint(other_key)):
        try:
            verifier(key).verify(token)
        except InvalidToken as exc:
            reasons.add(type(exc))
    assert reasons == {InvalidToken}


def test_an_unknown_kid_refetches_once_rather_than_failing(key):
    """A rotation is invisible: the first token carrying the new kid fetches it."""
    calls = {"n": 0}

    def keys(_token):
        calls["n"] += 1
        if calls["n"] == 1:
            raise LookupError("no such kid")
        return key.public_key()

    v = TokenVerifier(expect_issuer=ISS, expect_audience=AUD, keys=keys)
    assert v.verify(mint(key)).subject == "member-uuid"
    assert calls["n"] == 2


def test_a_second_failure_is_a_real_one(key):
    def keys(_token):
        raise LookupError("no such kid")

    v = TokenVerifier(expect_issuer=ISS, expect_audience=AUD, keys=keys)
    with pytest.raises(InvalidToken):
        v.verify(mint(key))


def test_the_issuer_is_configuration_because_a_laptop_issues_its_own():
    assert issuer({}) == ISS
    assert issuer({"GATEHOUSE_ISSUER": "https://auth.ballast.local"}) == "https://auth.ballast.local"


def test_the_audience_is_our_slug():
    assert audience({}) == AUD
    assert audience({"GATEHOUSE_AUDIENCE": "something-else"}) == "something-else"


def test_the_jwks_lives_under_the_issuer_unless_told_otherwise():
    assert jwks_url({}) == f"{ISS}/.well-known/jwks.json"
    assert jwks_url({"GATEHOUSE_ISSUER": "https://auth.ballast.local"}) == \
        "https://auth.ballast.local/.well-known/jwks.json"
    assert jwks_url({"GATEHOUSE_JWKS_URL": "https://keys.example/jwks"}) == \
        "https://keys.example/jwks"
