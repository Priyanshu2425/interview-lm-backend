"""Async Pool Ledger — manages the platform credit pool."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import schema as S


class AsyncPoolLedger:
    """Async version of PoolLedger for API services."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def topup(
        self,
        *,
        delta_credits: int,
        provider_reported_credits: int | None,
        source_ref: str,
    ) -> None:
        """Record a platform topup."""
        await self._s.execute(
            sa.insert(S.pool_ledger).values(
                id=source_ref,
                entry_type="topup",
                delta_credits=delta_credits,
                provider_reported_credits=provider_reported_credits,
                source_ref=source_ref,
            )
        )

    async def drawdown(
        self,
        *,
        delta_credits: int,
        source_ref: str,
    ) -> None:
        """Record a platform drawdown."""
        if delta_credits <= 0:
            return
        await self._s.execute(
            sa.insert(S.pool_ledger).values(
                id=source_ref,
                entry_type="drawdown",
                delta_credits=-delta_credits,
                provider_reported_credits=None,
                source_ref=source_ref,
            )
        )

    async def balance(self) -> int:
        """Get pool balance."""
        result = await self._s.execute(
            sa.select(sa.func.sum(S.pool_ledger.c.delta_credits))
        )
        return result.scalar() or 0

    async def entries(self) -> list[dict[str, Any]]:
        """All pool ledger entries."""
        result = await self._s.execute(
            sa.select(S.pool_ledger).order_by(S.pool_ledger.c.created_at)
        )
        return [dict(r._mapping) for r in result.all()]