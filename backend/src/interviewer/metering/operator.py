"""Operator readings (PRD-0005 §7).

Everything here reads off ledgers that already exist. No new instrumentation,
and nothing a Candidate sees is derived from a different source than this.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from ..db import schema as S
from .ledger import PoolLedger

POOL_HEADROOM_ALERT = 150_000


@dataclass(frozen=True, slots=True)
class PoolReading:
    pool: int
    sum_balances: int
    headroom: int
    alert: bool
    float_usd: float
    divergence: int


@dataclass(frozen=True, slots=True)
class ProviderReading:
    provider: str
    visits: int
    credits: int
    credits_per_visit: int
    unpriced_rate: float
    failure_rate: float


class PriceService:
    """What each Provider has actually cost, per Topic Visit.

    History, not a forecast. PRD-0005 refuses to quote a Session price in
    advance, so this reports what previous Visits cost and says so.
    """

    def __init__(self, engine: Engine) -> None:
        self._e = engine

    def per_visit(self) -> list[dict]:
        cr = S.call_record
        with self._e.connect() as c:
            rows = c.execute(
                sa.select(
                    cr.c.provider,
                    sa.func.count(sa.distinct(cr.c.topic_visit_id)).label("visits"),
                    sa.func.sum(cr.c.credits_charged).label("credits"),
                )
                .where(cr.c.payment_route == "credits")
                .group_by(cr.c.provider)
            ).all()
        out = []
        for r in rows:
            visits = int(r.visits) or 1
            out.append({
                "provider": r.provider,
                "credits_per_visit": round(int(r.credits or 0) / visits),
                "observed_visits": int(r.visits),
                "basis": "what your previous Topics actually cost, not a forecast",
            })
        return sorted(out, key=lambda x: x["credits_per_visit"])


class OperatorService:
    def __init__(self, engine: Engine) -> None:
        self._e = engine
        self._pool = PoolLedger(engine)

    def pool(self) -> PoolReading:
        pool, balances = self._pool.pool(), self._pool.sum_balances()
        headroom = pool - balances
        return PoolReading(
            pool=pool,
            sum_balances=balances,
            headroom=headroom,
            alert=headroom < POOL_HEADROOM_ALERT,
            # One-way float: recoverable as service, not as cash.
            float_usd=round(pool / 100, 2),
            divergence=self._pool.divergence(),
        )

    def by_provider(self) -> list[ProviderReading]:
        cr = S.call_record
        with self._e.connect() as c:
            rows = c.execute(
                sa.select(
                    cr.c.provider,
                    sa.func.count().label("calls"),
                    sa.func.count(sa.distinct(cr.c.topic_visit_id)).label("visits"),
                    sa.func.sum(cr.c.credits_charged).label("credits"),
                    sa.func.sum(
                        sa.case((cr.c.cost_status == "unpriced", 1), else_=0)
                    ).label("unpriced"),
                    sa.func.sum(
                        sa.case((cr.c.outcome != "ok", 1), else_=0)
                    ).label("failed"),
                ).group_by(cr.c.provider)
            ).all()
        out = []
        for r in rows:
            calls = int(r.calls) or 1
            visits = int(r.visits) or 1
            credits = int(r.credits or 0)
            out.append(ProviderReading(
                provider=r.provider,
                visits=int(r.visits),
                credits=credits,
                credits_per_visit=round(credits / visits),
                # Unpriced was never collapsed into zero, which is the only
                # reason this figure is visible at all.
                unpriced_rate=round(int(r.unpriced or 0) / calls, 4),
                failure_rate=round(int(r.failed or 0) / calls, 4),
            ))
        return sorted(out, key=lambda x: -x.visits)

    def unpriced_rate(self) -> float:
        cr = S.call_record
        with self._e.connect() as c:
            total = c.execute(sa.select(sa.func.count()).select_from(cr)).scalar() or 0
            unpriced = c.execute(
                sa.select(sa.func.count()).select_from(cr)
                .where(cr.c.cost_status == "unpriced")
            ).scalar() or 0
        return round(unpriced / total, 4) if total else 0.0

    def sessions(self, limit: int = 50) -> list[dict]:
        """Spend rolls up call → Visit → Session → Candidate on existing keys."""
        s, v, cl = S.session, S.topic_visit, S.credit_ledger
        with self._e.connect() as c:
            rows = c.execute(
                sa.select(
                    s.c.session_id, s.c.payment_route, s.c.state,
                    s.c.ended_reason, s.c.parked_reason,
                    sa.select(sa.func.count()).select_from(v)
                      .where(v.c.session_id == s.c.session_id)
                      .scalar_subquery().label("visits"),
                    sa.select(sa.func.coalesce(sa.func.sum(-cl.c.delta_credits), 0))
                      .where(cl.c.session_id == s.c.session_id,
                             cl.c.entry_type == "debit")
                      .scalar_subquery().label("credits"),
                    sa.select(sa.func.coalesce(sa.func.sum(cl.c.delta_credits), 0))
                      .where(cl.c.session_id == s.c.session_id,
                             cl.c.entry_type == "refund")
                      .scalar_subquery().label("refunded"),
                ).order_by(s.c.started_at.desc()).limit(limit)
            ).all()
        return [
            {
                "session_id": r.session_id,
                "route": r.payment_route,
                "visits": int(r.visits),
                # BYOK and MCP carry null, never 0 — zero would read as a
                # Session that cost nothing.
                "credits": int(r.credits) if r.payment_route == "credits" else None,
                "refunded": int(r.refunded) if r.payment_route == "credits" else None,
                "ended": r.ended_reason or r.parked_reason or r.state,
            }
            for r in rows
        ]
