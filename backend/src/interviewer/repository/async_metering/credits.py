"""Async Credit Ledger — manages candidate credit ledger."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import schema as S
from ...model.credits_models import Cost, CostStatus
# One Entry type and one id minter for both ledgers. A second definition is
# how `already_existed` came to mean nothing on this side.
from ...service.metering.ledger import Entry, _id


class AsyncCreditLedger:
    """Async version of CreditLedger for API services."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def balance(self, candidate_id: str) -> int:
        """Summed from the ledger, never stored.

        The ledger is the record; a balance is a reading of it. There is no
        `candidate.credits` column to read, and an earlier version of this
        method reading one is why every balance answered zero.
        """
        result = await self._s.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(S.credit_ledger.c.delta_credits), 0)
            ).where(S.credit_ledger.c.candidate_id == candidate_id)
        )
        return int(result.scalar() or 0)

    async def debit(
        self,
        *,
        candidate_id: str,
        call_id: str,
        credits: int,
        topic_visit_id: str,
        session_id: str,
    ) -> None:
        """Debit credits for a call (idempotent)."""
        if credits <= 0:
            return
        await self._s.execute(
            sa.insert(S.credit_ledger).values(
                id=call_id,
                candidate_id=candidate_id,
                entry_type="debit",
                delta_credits=-credits,
                topic_visit_id=topic_visit_id,
                session_id=session_id,
            )
        )

    async def grant(
        self,
        *,
        candidate_id: str,
        credits: int,
        payment_ref: str,
    ) -> Entry:
        """Credits are granted only once payment clears. That ordering is what
        makes the pool invariant hold by construction.

        Idempotent on `payment_ref`, and it reports which it was: a caller that
        cannot tell a fresh grant from a replayed one cannot tell a duplicate
        payment from a duplicate delivery of the same one.
        """
        if credits <= 0:
            raise ValueError("a grant must be positive")
        return await self._insert(
            candidate_id=candidate_id,
            entry_type="grant",
            delta=credits,
            payment_ref=payment_ref,
            dedupe=sa.and_(
                S.credit_ledger.c.entry_type == "grant",
                S.credit_ledger.c.payment_ref == payment_ref,
            ),
        )

    async def _insert(
        self, *, candidate_id: str, entry_type: str, delta: int, dedupe, **cols
    ) -> Entry:
        """The sync ledger's `_insert`, awaited. Same dedupe, same race.

        The id is minted rather than borrowed from `payment_ref`: an entry id
        that is also a payment reference cannot be written twice for the same
        payment under two entry types, and the ledger has more than one.
        """
        if dedupe is not None:
            existing = (
                await self._s.execute(
                    sa.select(
                        S.credit_ledger.c.id, S.credit_ledger.c.delta_credits
                    ).where(dedupe)
                )
            ).first()
            if existing:
                return Entry(existing[0], int(existing[1]), True)
        eid = _id()
        try:
            await self._s.execute(
                sa.insert(S.credit_ledger).values(
                    id=eid,
                    candidate_id=candidate_id,
                    entry_type=entry_type,
                    delta_credits=delta,
                    **cols,
                )
            )
        except IntegrityError:
            # A concurrent writer won the race; the constraint is the mechanism.
            existing = (
                await self._s.execute(
                    sa.select(
                        S.credit_ledger.c.id, S.credit_ledger.c.delta_credits
                    ).where(dedupe)
                )
            ).first()
            return Entry(existing[0], int(existing[1]), True)
        return Entry(eid, delta, False)

    async def refund(
        self,
        *,
        candidate_id: str,
        credits: int,
        refunded_visit_id: str,
    ) -> None:
        """Refund credits for a visit (idempotent on refunded_visit_id)."""
        if credits <= 0:
            return
        await self._s.execute(
            sa.insert(S.credit_ledger).values(
                id=refunded_visit_id,
                candidate_id=candidate_id,
                entry_type="refund",
                delta_credits=credits,
                refunded_visit_id=refunded_visit_id,
            )
        )

    async def visit_cost(self, topic_visit_id: str) -> int:
        """What a Visit cost, read from the debits that paid for it.

        The ledger, not `call_record`: a call that was recorded but never
        charged is not a cost, and the two tables can disagree.
        """
        result = await self._s.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(-S.credit_ledger.c.delta_credits), 0)
            ).where(
                S.credit_ledger.c.topic_visit_id == topic_visit_id,
                S.credit_ledger.c.entry_type == "debit",
            )
        )
        return int(result.scalar() or 0)

    async def entries_for(self, candidate_id: str) -> list[dict[str, Any]]:
        """All ledger entries for a candidate."""
        result = await self._s.execute(
            sa.select(S.credit_ledger)
            .where(S.credit_ledger.c.candidate_id == candidate_id)
            .order_by(S.credit_ledger.c.created_at)
        )
        return [dict(r._mapping) for r in result.all()]