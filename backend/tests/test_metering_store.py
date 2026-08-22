"""ISSUE-0008 / 0009 — the chokepoint, the ledger, and the pool invariant."""

from decimal import Decimal

import pytest
import sqlalchemy as sa

from interviewer.db import schema as S
from interviewer.metering.client import (
    Binding, BindingStore, MeteredModelClient, ProviderFailure,
)
from interviewer.metering.ledger import CreditLedger, PoolLedger
from interviewer.metering.transport import ScriptedTransport

CAND = "cand_meter"
VISIT = "visit_meter_1"
SESS = "sess_meter_1"


@pytest.fixture()
def wired(clean_db):
    ledger = CreditLedger(clean_db)
    transport = ScriptedTransport()
    client = MeteredModelClient(clean_db, transport, ledger)
    client.bind(Binding(VISIT, "deepseek", "credits"),
                session_id=SESS, candidate_id=CAND)
    return clean_db, ledger, transport, client


def _records(engine):
    with engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(sa.select(S.call_record)).all()]


# -- the chokepoint ----------------------------------------------------------

def test_every_call_emits_one_record_carrying_its_topic_visit_id(wired):
    engine, _, _, client = wired
    client.complete(topic_visit_id=VISIT, role="judge", system="s", user="u")
    rows = _records(engine)
    assert len(rows) == 1
    assert rows[0]["topic_visit_id"] == VISIT
    assert rows[0]["role"] == "judge"


def test_a_call_without_a_topic_visit_id_is_rejected(wired):
    _, _, _, client = wired
    with pytest.raises(ValueError, match="topic_visit_id"):
        client.complete(topic_visit_id="", role="judge", system="s", user="u")


def test_a_call_for_an_unbound_visit_is_rejected(wired):
    _, _, _, client = wired
    with pytest.raises(ValueError, match="no Provider is bound"):
        client.complete(topic_visit_id="some_other_visit", role="judge",
                        system="s", user="u")


def test_an_unpriced_response_is_flagged_and_charges_nothing(clean_db):
    ledger = CreditLedger(clean_db)
    t = ScriptedTransport(cost_usd=None)
    c = MeteredModelClient(clean_db, t, ledger)
    c.bind(Binding(VISIT, "gemini", "credits"), session_id=SESS, candidate_id=CAND)
    c.complete(topic_visit_id=VISIT, role="judge", system="s", user="u")

    row = _records(clean_db)[0]
    assert row["cost_status"] == "unpriced"
    assert row["credits_charged"] == 0
    assert ledger.balance(CAND) == 0


def test_unpriced_calls_are_countable_not_indistinguishable_from_free(clean_db):
    ledger = CreditLedger(clean_db)
    for i, cost in enumerate([Decimal("0.05"), None, Decimal("0.00"), None]):
        t = ScriptedTransport(cost_usd=cost)
        c = MeteredModelClient(clean_db, t, ledger)
        vid = f"{VISIT}_{i}"
        c.bind(Binding(vid, "gemini", "credits"), session_id=SESS, candidate_id=CAND)
        c.complete(topic_visit_id=vid, role="judge", system="s", user="u")

    with clean_db.connect() as conn:
        unpriced = conn.execute(
            sa.select(sa.func.count()).select_from(S.call_record)
            .where(S.call_record.c.cost_status == "unpriced")
        ).scalar()
        zero_priced = conn.execute(
            sa.select(sa.func.count()).select_from(S.call_record)
            .where(S.call_record.c.cost_status == "priced",
                   S.call_record.c.credits_charged == 0)
        ).scalar()
    assert unpriced == 2
    assert zero_priced == 1     # a real zero, distinguishable from a gap


def test_a_failed_call_is_still_recorded(wired):
    engine, _, transport, client = wired
    transport.fail_with = "provider_unavailable"
    with pytest.raises(ProviderFailure):
        client.complete(topic_visit_id=VISIT, role="judge", system="s", user="u")
    row = _records(engine)[0]
    assert row["outcome"] == "provider_error"


def test_cost_is_never_derived_from_token_counts(clean_db):
    ledger = CreditLedger(clean_db)
    t = ScriptedTransport(cost_usd=Decimal("0.03"))
    c = MeteredModelClient(clean_db, t, ledger)
    c.bind(Binding(VISIT, "claude", "credits"), session_id=SESS, candidate_id=CAND)
    c.complete(topic_visit_id=VISIT, role="judge", system="s", user="u")
    row = _records(clean_db)[0]
    assert row["credits_charged"] == 3          # from the reported 0.03, not 150 tokens
    assert row["prompt_tokens"] == 100


def test_a_byok_session_writes_no_debit_rows(clean_db):
    ledger = CreditLedger(clean_db)
    c = MeteredModelClient(clean_db, ScriptedTransport(), ledger,
                           key_resolver=lambda cid: "sk-or-test")
    c.bind(Binding(VISIT, "deepseek", "byok"), session_id=SESS, candidate_id=CAND)
    c.complete(topic_visit_id=VISIT, role="judge", system="s", user="u")

    assert ledger.balance(CAND) == 0
    assert ledger.rows(CAND) == []
    row = _records(clean_db)[0]
    assert row["payment_route"] == "byok"
    assert row["credits_charged"] == 0
    assert row["provider"] == "deepseek"     # still a full operational record


def test_under_byok_the_candidates_key_is_used(clean_db):
    t = ScriptedTransport()
    c = MeteredModelClient(clean_db, t, CreditLedger(clean_db),
                           key_resolver=lambda cid: "sk-or-candidate")
    c.bind(Binding(VISIT, "deepseek", "byok"), session_id=SESS, candidate_id=CAND)
    c.complete(topic_visit_id=VISIT, role="judge", system="s", user="u")
    assert t.sent[0]["api_key"] == "sk-or-candidate"


def test_under_credits_the_candidates_key_is_never_consulted(clean_db):
    calls = []
    c = MeteredModelClient(clean_db, ScriptedTransport(), CreditLedger(clean_db),
                           key_resolver=lambda cid: calls.append(cid) or "sk")
    c.bind(Binding(VISIT, "deepseek", "credits"), session_id=SESS, candidate_id=CAND)
    c.complete(topic_visit_id=VISIT, role="judge", system="s", user="u")
    assert calls == []


# -- provider binding --------------------------------------------------------

def test_a_binding_is_write_once_per_visit(clean_db):
    store = BindingStore(clean_db)
    first = store.bind(Binding(VISIT, "deepseek", "credits"))
    second = store.bind(Binding(VISIT, "claude", "credits"))
    assert first.provider == second.provider == "deepseek"


def test_a_provider_may_change_between_visits(clean_db):
    store = BindingStore(clean_db)
    store.bind(Binding("v1", "deepseek", "credits"))
    store.bind(Binding("v2", "claude", "credits"))
    assert store.get("v1").provider == "deepseek"
    assert store.get("v2").provider == "claude"


def test_there_is_no_function_to_change_a_binding_mid_visit():
    """Structurally absent: splitting one score across two graders would corrupt
    the provenance record."""
    assert not hasattr(BindingStore, "rebind")
    assert not hasattr(BindingStore, "failover")
    assert not hasattr(MeteredModelClient, "switch_provider")


# -- ledger ------------------------------------------------------------------

def test_balance_is_derived_from_ledger_rows(clean_db):
    l = CreditLedger(clean_db)
    l.grant(CAND, 5000, "pay_1")
    l.debit(candidate_id=CAND, call_id="c1", credits=21,
            topic_visit_id=VISIT, session_id=SESS)
    assert l.balance(CAND) == 4979
    assert len(l.rows(CAND)) == 2


def test_a_replayed_payment_grants_once(clean_db):
    l = CreditLedger(clean_db)
    a = l.grant(CAND, 5000, "pay_same")
    b = l.grant(CAND, 5000, "pay_same")
    assert b.already_existed
    assert l.balance(CAND) == 5000


def test_a_retried_debit_for_the_same_call_is_a_no_op(clean_db):
    l = CreditLedger(clean_db)
    l.grant(CAND, 1000, "p")
    l.debit(candidate_id=CAND, call_id="c1", credits=30,
            topic_visit_id=VISIT, session_id=SESS)
    again = l.debit(candidate_id=CAND, call_id="c1", credits=30,
                    topic_visit_id=VISIT, session_id=SESS)
    assert again.already_existed
    assert l.balance(CAND) == 970


def test_a_refund_returns_every_debit_under_one_visit_exactly_once(clean_db):
    l = CreditLedger(clean_db)
    l.grant(CAND, 1000, "p")
    for i, amt in enumerate((12, 9, 17)):
        l.debit(candidate_id=CAND, call_id=f"c{i}", credits=amt,
                topic_visit_id=VISIT, session_id=SESS)
    assert l.balance(CAND) == 962

    r = l.refund_visit(VISIT, "our failure")
    assert r.delta == 38
    assert l.balance(CAND) == 1000

    again = l.refund_visit(VISIT, "our failure")
    assert again.already_existed
    assert l.balance(CAND) == 1000


def test_a_refund_is_its_own_row_never_an_edited_debit(clean_db):
    l = CreditLedger(clean_db)
    l.grant(CAND, 500, "p")
    l.debit(candidate_id=CAND, call_id="c1", credits=40,
            topic_visit_id=VISIT, session_id=SESS)
    l.refund_visit(VISIT, "ours")
    kinds = [r["entry_type"] for r in l.rows(CAND)]
    assert kinds == ["grant", "debit", "refund"]


def test_a_balance_may_go_negative(clean_db):
    l = CreditLedger(clean_db)
    l.grant(CAND, 10, "p")
    l.debit(candidate_id=CAND, call_id="c1", credits=25,
            topic_visit_id=VISIT, session_id=SESS)
    assert l.balance(CAND) == -15


# -- the pool ----------------------------------------------------------------

def test_the_pool_invariant_holds_across_grant_spend_and_refund(clean_db):
    l, pool = CreditLedger(clean_db), PoolLedger(clean_db)
    pool.topup(1_000_000, "bank_1")
    l.grant(CAND, 5000, "pay_1")
    l.debit(candidate_id=CAND, call_id="c1", credits=120,
            topic_visit_id=VISIT, session_id=SESS)
    l.refund_visit(VISIT, "ours")
    assert pool.headroom() >= 0
    assert pool.pool() >= pool.sum_balances()


def test_drawdown_records_both_figures_and_reports_their_divergence(clean_db):
    pool = PoolLedger(clean_db)
    pool.topup(500_000, "bank")
    pool.drawdown(1000, "window_1", provider_reported=1000)
    assert pool.divergence() == 0
    pool.drawdown(1000, "window_2", provider_reported=1075)
    assert pool.divergence() == 75      # provider says more than we recorded


def test_promotional_credits_draw_from_the_same_pool(clean_db):
    l, pool = CreditLedger(clean_db), PoolLedger(clean_db)
    pool.topup(10_000, "bank")
    l.promo_grant(CAND, 500, "launch")
    assert l.balance(CAND) == 500
    assert pool.headroom() == 9_500
