"""Async Binding Store — manages Visit Provider Bindings."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import schema as S
from ...service.metering.client import Binding


class AsyncBindingStore:
    """Async version of BindingStore for API services."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def bind(self, b: Binding) -> Binding:
        """Bind a visit to a provider (idempotent)."""
        existing = await self._s.execute(
            sa.select(S.visit_provider_binding).where(
                S.visit_provider_binding.c.topic_visit_id == b.topic_visit_id
            )
        )
        row = existing.first()
        if row:
            m = row._mapping
            return Binding(m["topic_visit_id"], m["provider"], m["payment_route"], m["byok_key_id"])

        await self._s.execute(
            sa.insert(S.visit_provider_binding).values(
                topic_visit_id=b.topic_visit_id,
                provider=b.provider,
                payment_route=b.payment_route,
                byok_key_id=b.byok_key_id,
            )
        )
        return b

    async def get(self, topic_visit_id: str) -> Binding | None:
        """Get binding for a visit."""
        result = await self._s.execute(
            sa.select(S.visit_provider_binding).where(
                S.visit_provider_binding.c.topic_visit_id == topic_visit_id
            )
        )
        row = result.first()
        if not row:
            return None
        m = row._mapping
        return Binding(m["topic_visit_id"], m["provider"], m["payment_route"], m["byok_key_id"])