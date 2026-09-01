"""Credit Ledger and Pool Ledger — append-only.

Balance is derived from ledger rows. There is no balance column to drift and no
code path that edits one. Idempotency is expressed as partial unique indexes
(SPEC-0005 §2.1), so a retried write is a constraint violation we absorb rather
than a check we remember to perform.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from ...db import schema as S


def _id() -> str:
    return f"led_{uuid.uuid4().hex[:22]}"


@dataclass(frozen=True, slots=True)
class Entry:
    id: str
    delta: int
    already_existed: bool


class CreditLedger:
    def __init__(self, engine: Engine) -> None:
        self._e = engine

    # -- readings ----------------------------------------------------------

    def balance(self, candidate_id: str) -> int:
        with self._e.connect() as c:
            v = c.execute(
                sa.select(sa.func.coalesce(sa.func.sum(S.credit_ledger.c.delta_credits), 0))
                .where(S.credit_ledger.c.candidate_id == candidate_id)
            ).scalar()
        return int(v or 0)

    def rows(self, candidate_id: str) -> list[dict]:
        with self._e.connect() as c:
            return [
                dict(r._mapping)
                for r in c.execute(
                    sa.select(S.credit_ledger)
                    .where(S.credit_ledger.c.candidate_id == candidate_id)
                    .order_by(S.credit_ledger.c.created_at, S.credit_ledger.c.id)
                ).all()
            ]

    def visit_cost(self, topic_visit_id: str) -> int:
        with self._e.connect() as c:
            v = c.execute(
                sa.select(sa.func.coalesce(sa.func.sum(-S.credit_ledger.c.delta_credits), 0))
                .where(
                    S.credit_ledger.c.topic_visit_id == topic_visit_id,
                    S.credit_ledger.c.entry_type == "debit",
                )
            ).scalar()
        return int(v or 0)

    # -- writes ------------------------------------------------------------

    def grant(self, candidate_id: str, credits: int, payment_ref: str) -> Entry:
        """Credits are granted only once payment clears. That ordering is what
        makes the pool invariant hold by construction."""
        if credits <= 0:
            raise ValueError("a grant must be positive")
        return self._insert(
            candidate_id=candidate_id, entry_type="grant", delta=credits,
            payment_ref=payment_ref,
            dedupe=sa.and_(
                S.credit_ledger.c.entry_type == "grant",
                S.credit_ledger.c.payment_ref == payment_ref,
            ),
        )

    def promo_grant(self, candidate_id: str, credits: int, reason: str) -> Entry:
        return self._insert(
            candidate_id=candidate_id, entry_type="promo_grant",
            delta=credits, reason=reason, dedupe=None,
        )

    def debit(
        self, *, candidate_id: str, call_id: str, credits: int,
        topic_visit_id: str, session_id: str,
    ) -> Entry:
        """Idempotent on call_id."""
        return self._insert(
            candidate_id=candidate_id, entry_type="debit", delta=-abs(credits),
            call_id=call_id, topic_visit_id=topic_visit_id, session_id=session_id,
            dedupe=sa.and_(
                S.credit_ledger.c.entry_type == "debit",
                S.credit_ledger.c.call_id == call_id,
            ),
        )

    def refund_visit(self, topic_visit_id: str, reason: str) -> Entry:
        """Sums every debit under a Visit and writes one positive entry.

        A refund is never a balance edit. The ledger is the record; a balance is
        a reading of it.
        """
        with self._e.connect() as c:
            row = c.execute(
                sa.select(
                    S.credit_ledger.c.candidate_id,
                    S.credit_ledger.c.session_id,
                    sa.func.coalesce(sa.func.sum(-S.credit_ledger.c.delta_credits), 0),
                )
                .where(
                    S.credit_ledger.c.topic_visit_id == topic_visit_id,
                    S.credit_ledger.c.entry_type == "debit",
                )
                .group_by(S.credit_ledger.c.candidate_id, S.credit_ledger.c.session_id)
            ).first()
        if not row:
            return Entry("", 0, True)
        candidate_id, session_id, total = row[0], row[1], int(row[2])
        return self._insert(
            candidate_id=candidate_id, entry_type="refund", delta=total,
            topic_visit_id=topic_visit_id, session_id=session_id,
            refunded_visit_id=topic_visit_id, reason=reason,
            dedupe=sa.and_(
                S.credit_ledger.c.entry_type == "refund",
                S.credit_ledger.c.refunded_visit_id == topic_visit_id,
            ),
        )

    def _insert(self, *, candidate_id: str, entry_type: str, delta: int,
                dedupe, **cols) -> Entry:
        if dedupe is not None:
            with self._e.connect() as c:
                existing = c.execute(
                    sa.select(S.credit_ledger.c.id, S.credit_ledger.c.delta_credits)
                    .where(dedupe)
                ).first()
            if existing:
                return Entry(existing[0], int(existing[1]), True)
        eid = _id()
        try:
            with self._e.begin() as c:
                c.execute(
                    sa.insert(S.credit_ledger).values(
                        id=eid, candidate_id=candidate_id, entry_type=entry_type,
                        delta_credits=delta, **cols,
                    )
                )
        except IntegrityError:
            # A concurrent writer won the race; the constraint is the mechanism.
            with self._e.connect() as c:
                existing = c.execute(
                    sa.select(S.credit_ledger.c.id, S.credit_ledger.c.delta_credits)
                    .where(dedupe)
                ).first()
            return Entry(existing[0], int(existing[1]), True)
        return Entry(eid, delta, False)


class PoolLedger:
    """Operator-side. Drawdown is measured in our own numbers (ADR-0014)."""

    def __init__(self, engine: Engine) -> None:
        self._e = engine

    def prefunded_for(self, credits: int) -> bool:
        """Whether granting this many Credits keeps `pool >= sum(balances)`.

        Pre-funding is what removes the failure rather than detecting it: the
        pool is topped up ahead of receipts, so a Candidate with a positive
        balance is never blocked by an empty pool.
        """
        return self.pool() - self.sum_balances() >= credits

    def topup(self, credits: int, source_ref: str) -> None:
        with self._e.begin() as c:
            c.execute(sa.insert(S.pool_ledger).values(
                id=_id(), entry_type="topup", delta_credits=credits,
                source_ref=source_ref,
            ))

    def drawdown(self, our_credits: int, source_ref: str,
                 provider_reported: int | None = None) -> None:
        with self._e.begin() as c:
            c.execute(sa.insert(S.pool_ledger).values(
                id=_id(), entry_type="drawdown", delta_credits=-abs(our_credits),
                provider_reported_credits=provider_reported, source_ref=source_ref,
            ))

    def pool(self) -> int:
        with self._e.connect() as c:
            return int(c.execute(
                sa.select(sa.func.coalesce(sa.func.sum(S.pool_ledger.c.delta_credits), 0))
            ).scalar() or 0)

    def sum_balances(self) -> int:
        with self._e.connect() as c:
            return int(c.execute(
                sa.select(sa.func.coalesce(sa.func.sum(S.credit_ledger.c.delta_credits), 0))
            ).scalar() or 0)

    def headroom(self) -> int:
        return self.pool() - self.sum_balances()

    def divergence(self) -> int:
        """Cumulative provider-reported minus ours. Should sit near zero."""
        with self._e.connect() as c:
            rows = c.execute(
                sa.select(
                    S.pool_ledger.c.delta_credits,
                    S.pool_ledger.c.provider_reported_credits,
                ).where(S.pool_ledger.c.entry_type == "drawdown")
            ).all()
        return sum(
            int(rep) - abs(int(delta)) for delta, rep in rows if rep is not None
        )
