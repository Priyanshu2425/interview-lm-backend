"""ISSUE-0008 / ISSUE-0009 — Credit Math and the Failure Classifier.

Pure tests, no I/O. The exhaustive classifier check is the one that matters:
it asserts a property over the whole input space, not an example.
"""

from decimal import Decimal

import pytest

from interviewer.model.credits_models import (
    HEADROOM_CREDITS,
    Balance,
    Cost,
    CostStatus,
)
from interviewer.model.failures_models import (
    CREDIT_EVENTS,
    Cause,
    Event,
    Route,
    UserFacingEvent,
)


# -- Credit Math -------------------------------------------------------------

def test_one_credit_is_one_us_cent_of_provider_cost():
    assert Cost.of_usd(Decimal("9.70")).credits == 970
    assert Cost.of_usd(Decimal("0.21")).credits == 21


def test_a_sub_cent_call_costs_zero_credits_not_one():
    """Rounding up would make a chatty Visit a rounding-fee product."""
    assert Cost.of_usd(Decimal("0.004")).credits == 0
    assert Cost.of_usd(Decimal("0.0099")).credits == 0
    assert Cost.of_usd(Decimal("0.01")).credits == 1


@pytest.mark.parametrize("usd,expected", [
    ("0.07", 7), ("0.29", 29), ("1.15", 115), ("0.83", 83), ("12.34", 1234),
])
def test_conversion_is_exact_where_floating_point_would_drift(usd, expected):
    assert Cost.of_usd(Decimal(usd)).credits == expected


def test_an_unreported_cost_is_unpriced_and_never_zero_cost():
    c = Cost.of_usd(None)
    assert c == Cost(0, CostStatus.UNPRICED)
    assert Cost.of_usd(Decimal("0")).status is CostStatus.PRICED


def test_a_negative_provider_cost_is_refused():
    with pytest.raises(ValueError):
        Cost.of_usd(Decimal("-1"))


def test_a_debit_larger_than_the_balance_goes_negative_rather_than_clamping():
    assert Balance(10).debit(25).credits == -15
    assert Balance(0).debit(1).credits == -1


def test_a_refund_restores_the_exact_prior_balance():
    start = 4180
    assert Balance(start).debit(38).refund(38).credits == start


def test_balances_are_integers_at_every_step():
    b = 100
    for step in (7, 3, 21):
        b = Balance(b).debit(step).credits
        assert isinstance(b, int)
    assert isinstance(Balance(b).refund(5).credits, int)


def test_headroom_clears_and_fails_exactly_at_the_boundary():
    assert Balance(HEADROOM_CREDITS).clears_headroom()
    assert not Balance(HEADROOM_CREDITS - 1).clears_headroom()
    assert not Balance(-1).clears_headroom()


# -- Failure Classifier ------------------------------------------------------

def test_an_exhausted_balance_on_a_credit_session_names_credits():
    e = UserFacingEvent.of(route=Route.CREDITS, cause=Cause.BALANCE_EXHAUSTED)
    assert e.code is Event.CREDITS_EXHAUSTED
    assert "credit" in e.message.lower()
    assert e.recoverable


def test_mid_visit_exhaustion_reports_a_completed_visit_not_a_failure():
    e = UserFacingEvent.of(route=Route.CREDITS, cause=Cause.BALANCE_EXHAUSTED_MID_VISIT)
    assert e.code is Event.CREDITS_EXHAUSTED_MID_VISIT
    assert "finish" in e.message.lower()
    assert "cut" in e.message.lower()


@pytest.mark.parametrize("cause,code", [
    (Cause.KEY_REVOKED, Event.BYOK_KEY_REVOKED),
    (Cause.KEY_UNFUNDED, Event.BYOK_KEY_UNFUNDED),
    (Cause.KEY_RATE_LIMITED, Event.BYOK_KEY_RATE_LIMITED),
    (Cause.KEY_INVALID, Event.BYOK_KEY_INVALID),
])
def test_a_byok_failure_names_the_provider_and_the_reason(cause, code):
    e = UserFacingEvent.of(route=Route.BYOK, cause=cause, provider="DeepSeek")
    assert e.code is code
    if cause is not Cause.KEY_INVALID:
        assert "DeepSeek" in e.message


@pytest.mark.parametrize("cause", [
    Cause.KEY_REVOKED, Cause.KEY_UNFUNDED, Cause.KEY_RATE_LIMITED, Cause.KEY_INVALID,
])
def test_a_refused_key_on_the_credits_route_is_ours_not_theirs(cause):
    """The `KEY_*` causes name the key that was refused, not whose it is.

    On the Credits route the key is the platform's, so none of these may reach
    a Candidate as advice about a key they do not hold — the mirror of the rule
    that no BYOK failure may name Credits.
    """
    e = UserFacingEvent.of(route=Route.CREDITS, cause=cause, provider="DeepSeek")

    assert e.code not in CREDIT_EVENTS, "their balance did not run out"
    assert e.code.value.startswith("PROVIDER_") or e.code is Event.PLATFORM_KEY_MISSING
    assert "your key" not in e.message.lower()
    assert "your credits" not in e.message.lower()


def test_a_rate_limited_platform_key_parks_rather_than_ending_the_session():
    """Waiting fixes it, so the Candidate is told to wait.

    This is the case that used to raise. The failure happened *inside* the
    parking path, so a pause the product was designed to recover from became a
    500 instead.
    """
    e = UserFacingEvent.of(
        route=Route.CREDITS, cause=Cause.KEY_RATE_LIMITED, provider="DeepSeek"
    )
    assert e.recoverable
    assert "DeepSeek" in e.message


def test_every_cause_a_provider_can_raise_is_classifiable_on_the_credits_route():
    """The transport raises these from status codes without knowing whose key
    it used. Any one of them unclassified is a 500 in the parking path."""
    from interviewer.adapters.openrouter import OpenRouterTransport  # noqa: F401

    for cause in Cause:
        if cause in (Cause.BALANCE_EXHAUSTED, Cause.BALANCE_EXHAUSTED_MID_VISIT):
            continue  # the ledger raises these, not the provider
        UserFacingEvent.of(route=Route.CREDITS, cause=cause, provider="DeepSeek")


def test_exhaustively_no_byok_input_can_produce_a_credit_event():
    """The honesty rule as a property over the whole input space."""
    for cause in Cause:
        for provider in (None, "DeepSeek", "Gemini", "Claude"):
            try:
                e = UserFacingEvent.of(route=Route.BYOK, cause=cause, provider=provider)
            except ValueError:
                continue          # not classifiable on this route: also fine
            assert e.code not in CREDIT_EVENTS, (cause, e.code)
            assert "credit" not in e.message.lower(), (cause, e.message)


def test_exhaustively_no_mcp_input_mentions_credits_or_a_key():
    for cause in Cause:
        try:
            e = UserFacingEvent.of(route=Route.MCP, cause=cause, provider="Claude")
        except ValueError:
            continue
        assert e.code not in CREDIT_EVENTS
        assert "credit" not in e.message.lower()
        assert " key" not in e.message.lower()


def test_a_credit_session_never_blames_the_provider_for_running_out():
    e = UserFacingEvent.of(route=Route.CREDITS, cause=Cause.BALANCE_EXHAUSTED)
    for word in ("deepseek", "gemini", "claude", "openrouter", "key"):
        assert word not in e.message.lower()


def test_route_is_required_so_the_rule_cannot_be_bypassed():
    with pytest.raises(TypeError):
        UserFacingEvent.of(cause=Cause.BALANCE_EXHAUSTED)  # type: ignore[call-arg]
