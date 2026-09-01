"""ISSUE-0008 / ISSUE-0009 — Credit Math and the Failure Classifier.

Pure tests, no I/O. The exhaustive classifier check is the one that matters:
it asserts a property over the whole input space, not an example.
"""

from decimal import Decimal

import pytest

from interviewer.service.metering.credits import (
    HEADROOM_CREDITS,
    Cost,
    CostStatus,
    apply_debit,
    apply_refund,
    clears_headroom,
    usd_to_credits,
)
from interviewer.service.metering.failures import (
    CREDIT_EVENTS,
    Cause,
    Event,
    Route,
    classify,
)


# -- Credit Math -------------------------------------------------------------

def test_one_credit_is_one_us_cent_of_provider_cost():
    assert usd_to_credits(Decimal("9.70")).credits == 970
    assert usd_to_credits(Decimal("0.21")).credits == 21


def test_a_sub_cent_call_costs_zero_credits_not_one():
    """Rounding up would make a chatty Visit a rounding-fee product."""
    assert usd_to_credits(Decimal("0.004")).credits == 0
    assert usd_to_credits(Decimal("0.0099")).credits == 0
    assert usd_to_credits(Decimal("0.01")).credits == 1


@pytest.mark.parametrize("usd,expected", [
    ("0.07", 7), ("0.29", 29), ("1.15", 115), ("0.83", 83), ("12.34", 1234),
])
def test_conversion_is_exact_where_floating_point_would_drift(usd, expected):
    assert usd_to_credits(Decimal(usd)).credits == expected


def test_an_unreported_cost_is_unpriced_and_never_zero_cost():
    c = usd_to_credits(None)
    assert c == Cost(0, CostStatus.UNPRICED)
    assert usd_to_credits(Decimal("0")).status is CostStatus.PRICED


def test_a_negative_provider_cost_is_refused():
    with pytest.raises(ValueError):
        usd_to_credits(Decimal("-1"))


def test_a_debit_larger_than_the_balance_goes_negative_rather_than_clamping():
    assert apply_debit(10, 25) == -15
    assert apply_debit(0, 1) == -1


def test_a_refund_restores_the_exact_prior_balance():
    start = 4180
    assert apply_refund(apply_debit(start, 38), 38) == start


def test_balances_are_integers_at_every_step():
    b = 100
    for step in (7, 3, 21):
        b = apply_debit(b, step)
        assert isinstance(b, int)
    assert isinstance(apply_refund(b, 5), int)


def test_headroom_clears_and_fails_exactly_at_the_boundary():
    assert clears_headroom(HEADROOM_CREDITS)
    assert not clears_headroom(HEADROOM_CREDITS - 1)
    assert not clears_headroom(-1)


# -- Failure Classifier ------------------------------------------------------

def test_an_exhausted_balance_on_a_credit_session_names_credits():
    e = classify(route=Route.CREDITS, cause=Cause.BALANCE_EXHAUSTED)
    assert e.code is Event.CREDITS_EXHAUSTED
    assert "credit" in e.message.lower()
    assert e.recoverable


def test_mid_visit_exhaustion_reports_a_completed_visit_not_a_failure():
    e = classify(route=Route.CREDITS, cause=Cause.BALANCE_EXHAUSTED_MID_VISIT)
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
    e = classify(route=Route.BYOK, cause=cause, provider="DeepSeek")
    assert e.code is code
    if cause is not Cause.KEY_INVALID:
        assert "DeepSeek" in e.message


def test_exhaustively_no_byok_input_can_produce_a_credit_event():
    """The honesty rule as a property over the whole input space."""
    for cause in Cause:
        for provider in (None, "DeepSeek", "Gemini", "Claude"):
            try:
                e = classify(route=Route.BYOK, cause=cause, provider=provider)
            except ValueError:
                continue          # not classifiable on this route: also fine
            assert e.code not in CREDIT_EVENTS, (cause, e.code)
            assert "credit" not in e.message.lower(), (cause, e.message)


def test_exhaustively_no_mcp_input_mentions_credits_or_a_key():
    for cause in Cause:
        try:
            e = classify(route=Route.MCP, cause=cause, provider="Claude")
        except ValueError:
            continue
        assert e.code not in CREDIT_EVENTS
        assert "credit" not in e.message.lower()
        assert " key" not in e.message.lower()


def test_a_credit_session_never_blames_the_provider_for_running_out():
    e = classify(route=Route.CREDITS, cause=Cause.BALANCE_EXHAUSTED)
    for word in ("deepseek", "gemini", "claude", "openrouter", "key"):
        assert word not in e.message.lower()


def test_route_is_required_so_the_rule_cannot_be_bypassed():
    with pytest.raises(TypeError):
        classify(cause=Cause.BALANCE_EXHAUSTED)  # type: ignore[call-arg]
