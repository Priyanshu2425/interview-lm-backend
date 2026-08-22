"""ISSUE-0013 — the operator console."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from interviewer.api import idempotency
from interviewer.api.app import create_app
from interviewer.api.wiring import wiring
from interviewer.metering.client import Binding, MeteredModelClient
from interviewer.metering.ledger import CreditLedger, PoolLedger
from interviewer.metering.operator import POOL_HEADROOM_ALERT, OperatorService
from interviewer.metering.transport import ScriptedTransport

HDR = {"x-operator-token": "dev-operator-token"}


@pytest.fixture()
def svc(clean_db):
    return OperatorService(clean_db)


def _call(engine, provider, cost, visit, outcome_fail=False):
    t = ScriptedTransport(cost_usd=cost,
                          fail_with="provider_unavailable" if outcome_fail else None)
    c = MeteredModelClient(engine, t, CreditLedger(engine))
    c.bind(Binding(visit, provider, "credits"), session_id="s", candidate_id="c")
    try:
        c.complete(topic_visit_id=visit, role="judge", system="s", user="u")
    except Exception:
        pass


def test_pool_headroom_is_pool_minus_the_sum_of_balances(clean_db, svc):
    PoolLedger(clean_db).topup(1_000_000, "bank")
    CreditLedger(clean_db).grant("c1", 400_000, "p1")
    r = svc.pool()
    assert r.pool == 1_000_000
    assert r.sum_balances == 400_000
    assert r.headroom == 600_000


def test_an_alert_is_raised_below_the_threshold(clean_db, svc):
    PoolLedger(clean_db).topup(POOL_HEADROOM_ALERT - 1, "bank")
    assert svc.pool().alert is True
    PoolLedger(clean_db).topup(500_000, "bank2")
    assert svc.pool().alert is False


def test_float_is_reported_as_working_capital(clean_db, svc):
    PoolLedger(clean_db).topup(1_004_200, "bank")
    assert svc.pool().float_usd == 10042.0


def test_drawdown_divergence_is_signed_so_its_direction_is_readable(clean_db, svc):
    p = PoolLedger(clean_db)
    p.topup(500_000, "bank")
    p.drawdown(1000, "w1", provider_reported=1080)   # provider says more
    assert svc.pool().divergence == 80
    p.drawdown(1000, "w2", provider_reported=940)    # and then less
    assert svc.pool().divergence == 20


def test_unpriced_calls_are_visible_because_they_were_never_zeroed(clean_db, svc):
    _call(clean_db, "gemini", None, "v1")
    _call(clean_db, "gemini", Decimal("0.05"), "v2")
    _call(clean_db, "gemini", Decimal("0.00"), "v3")
    assert svc.unpriced_rate() == pytest.approx(1 / 3, abs=0.01)


def test_per_provider_readings_come_from_call_records_alone(clean_db, svc):
    _call(clean_db, "deepseek", Decimal("0.18"), "v1")
    _call(clean_db, "deepseek", Decimal("0.18"), "v2")
    _call(clean_db, "claude", Decimal("0.96"), "v3")
    rows = {r.provider: r for r in svc.by_provider()}
    assert rows["deepseek"].visits == 2
    assert rows["claude"].credits_per_visit == 96
    assert rows["deepseek"].credits_per_visit == 18


def test_failure_rate_is_reported_per_provider(clean_db, svc):
    _call(clean_db, "gemini", Decimal("0.04"), "v1")
    _call(clean_db, "gemini", None, "v2", outcome_fail=True)
    assert svc.by_provider()[0].failure_rate == 0.5


def test_byok_and_mcp_sessions_render_null_not_zero(clean_db, svc, deps):
    from interviewer.graph.sessions import SessionConfig

    mods = [m.module_id for m in deps.corpus.modules("aiml")][:1]
    deps.sessions.ensure_candidate("c_op")
    deps.sessions.create("c_op", SessionConfig(
        scope_module_ids=tuple(mods), duration_seconds=600,
        payment_route="byok", provider="deepseek"))
    deps.sessions.create("c_op", SessionConfig(
        scope_module_ids=tuple(mods), duration_seconds=600,
        payment_route="mcp", provider=None, mode="mcp"))
    rows = svc.sessions()
    assert all(r["credits"] is None for r in rows)


def test_the_console_states_that_no_normaliser_is_applied(clean_db):
    wiring.cache_clear()
    idempotency.reset()
    c = TestClient(create_app())
    body = c.get("/v1/operator/providers", headers=HDR).json()
    assert body["normaliser"] is None


def test_operator_access_is_authenticated_separately(clean_db):
    wiring.cache_clear()
    c = TestClient(create_app())
    assert c.get("/v1/operator/pool").status_code == 401
    assert c.get("/v1/operator/pool", headers={"x-operator-token": "wrong"}).status_code == 401
    assert c.get("/v1/operator/pool", headers=HDR).status_code == 200


def test_a_candidate_token_does_not_reach_the_operator_console(clean_db):
    wiring.cache_clear()
    c = TestClient(create_app())
    assert c.get("/v1/operator/sessions",
                 headers={"x-operator-token": "candidate"}).status_code == 401
