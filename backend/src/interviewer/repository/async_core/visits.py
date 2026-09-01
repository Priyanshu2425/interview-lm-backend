"""Async Visit Lifecycle — manages Topic Visit records."""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import schema as S
from ...model.corpus import GradingMode
from ...service.confidence.store import new_id


class AsyncVisitLifecycle:
    """Async version of VisitLifecycle for API services."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def open(
        self,
        *,
        session_id: str,
        candidate_id: str,
        topic_id: str,
        visit_index: int,
    ) -> str:
        """Open a new topic visit."""
        vid = new_id("visit")
        await self._s.execute(
            sa.insert(S.topic_visit).values(
                topic_visit_id=vid,
                session_id=session_id,
                candidate_id=candidate_id,
                topic_id=topic_id,
                visit_index=visit_index,
                state="open",
            )
        )
        return vid

    async def record_answer(
        self,
        topic_visit_id: str,
        *,
        exchange: dict,
        turn_count: int,
        mode: GradingMode,
        grounding_ref: dict | None = None,
    ) -> None:
        """Record the answer exchange before grading."""
        await self._s.execute(
            sa.update(S.topic_visit)
            .where(S.topic_visit.c.topic_visit_id == topic_visit_id)
            .values(
                state="answered",
                exchange=exchange,
                turn_count=turn_count,
                grading_mode=mode.value,
                grounding_ref=grounding_ref,
                answered_at=sa.func.now(),
            )
        )

    async def get(self, topic_visit_id: str) -> dict[str, Any] | None:
        """Get visit by ID."""
        result = await self._s.execute(
            sa.select(S.topic_visit).where(S.topic_visit.c.topic_visit_id == topic_visit_id)
        )
        row = result.first()
        return dict(row._mapping) if row else None

    async def unresolved(self, session_id: str) -> dict[str, Any] | None:
        """Get unresolved visit for a session (open or answered)."""
        result = await self._s.execute(
            sa.select(S.topic_visit)
            .where(
                S.topic_visit.c.session_id == session_id,
                S.topic_visit.c.state.in_(("open", "answered")),
            )
        )
        row = result.first()
        return dict(row._mapping) if row else None

    async def open_topic_ids(self) -> set[str]:
        """Get all topic IDs with visits in flight."""
        result = await self._s.execute(
            sa.select(S.topic_visit.c.topic_id).where(
                S.topic_visit.c.state.in_(("open", "answered"))
            )
        )
        return {r[0] for r in result.all()}

    async def visited_topic_ids(self, session_id: str) -> set[str]:
        """Get all topic IDs visited in a session."""
        result = await self._s.execute(
            sa.select(S.topic_visit.c.topic_id).where(
                S.topic_visit.c.session_id == session_id
            )
        )
        return {r[0] for r in result.all()}

    async def for_session(self, session_id: str) -> list[dict[str, Any]]:
        """Get all visits for a session in order."""
        result = await self._s.execute(
            sa.select(S.topic_visit)
            .where(S.topic_visit.c.session_id == session_id)
            .order_by(S.topic_visit.c.visit_index)
        )
        return [dict(r._mapping) for r in result.all()]

    async def abandon(self, topic_visit_id: str) -> None:
        """Abandon an open/answered visit."""
        await self._s.execute(
            sa.update(S.topic_visit)
            .where(
                S.topic_visit.c.topic_visit_id == topic_visit_id,
                S.topic_visit.c.state.in_(("open", "answered")),
            )
            .values(state="abandoned")
        )