"""Async Session Store — manages Session records."""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import schema as S
from ...service.graph.sessions import SessionConfig, RUBRIC_VERSION


class AsyncSessionStore:
    """Async version of SessionStore for API services."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    def ensure_candidate(self, candidate_id: str, name: str | None = None) -> str:
        """Ensure candidate exists (upsert)."""
        stmt = (
            sa.dialects.postgresql.insert(S.candidate)
            .values(candidate_id=candidate_id, display_name=name)
            .on_conflict_do_nothing(index_elements=["candidate_id"])
        )
        return candidate_id

    async def create(self, candidate_id: str, cfg: SessionConfig) -> str:
        """Create a new session."""
        sid = f"sess_{uuid.uuid4().hex[:22]}"
        await self._s.execute(
            sa.insert(S.session).values(
                session_id=sid,
                candidate_id=candidate_id,
                mode=cfg.mode,
                payment_route=cfg.payment_route,
                provider_chosen=cfg.provider,
                scope_module_ids=list(cfg.scope_module_ids),
                duration_seconds=cfg.duration_seconds,
                rubric_version=RUBRIC_VERSION,
                state="running",
            )
        )
        return sid

    async def get(self, session_id: str) -> dict[str, Any] | None:
        """Get session by ID."""
        result = await self._s.execute(
            sa.select(S.session).where(S.session.c.session_id == session_id)
        )
        row = result.first()
        return dict(row._mapping) if row else None

    async def park(self, session_id: str, reason: str) -> None:
        """Park a session."""
        await self._s.execute(
            sa.update(S.session)
            .where(S.session.c.session_id == session_id)
            .values(state="parked", parked_reason=reason)
        )

    async def resume(self, session_id: str) -> None:
        """Resume a parked session."""
        await self._s.execute(
            sa.update(S.session)
            .where(S.session.c.session_id == session_id)
            .values(state="running", parked_reason=None)
        )

    async def end(self, session_id: str, reason: str) -> None:
        """End a session."""
        await self._s.execute(
            sa.update(S.session)
            .where(S.session.c.session_id == session_id)
            .values(state="ended", ended_reason=reason, ended_at=sa.func.now())
        )