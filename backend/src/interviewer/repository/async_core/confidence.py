"""Async Confidence Store — reads and writes Topic Confidence posteriors."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import schema as S
from ...service.confidence.math import Posterior, PRIOR


class AsyncConfidenceStore:
    """Async version of ConfidenceStore for API services."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, candidate_id: str, topic_id: str) -> Posterior:
        """Get posterior for a candidate on a topic."""
        result = await self._s.execute(
            sa.select(
                S.topic_confidence.c.alpha, S.topic_confidence.c.beta
            ).where(
                S.topic_confidence.c.candidate_id == candidate_id,
                S.topic_confidence.c.topic_id == topic_id,
            )
        )
        row = result.first()
        return PRIOR if row is None else Posterior(float(row[0]), float(row[1]))

    async def get_many(
        self, candidate_id: str, topic_ids: list[str]
    ) -> dict[str, Posterior]:
        """Get posteriors for multiple topics."""
        if not topic_ids:
            return {}
        result = await self._s.execute(
            sa.select(
                S.topic_confidence.c.topic_id,
                S.topic_confidence.c.alpha,
                S.topic_confidence.c.beta,
            ).where(
                S.topic_confidence.c.candidate_id == candidate_id,
                S.topic_confidence.c.topic_id.in_(topic_ids),
            )
        )
        stored = {r[0]: Posterior(float(r[1]), float(r[2])) for r in result.all()}
        return {tid: stored.get(tid, PRIOR) for tid in topic_ids}

    async def all_on_topic(self, topic_id: str) -> dict[str, Posterior]:
        """Get all candidates' posteriors on one topic."""
        result = await self._s.execute(
            sa.select(
                S.topic_confidence.c.candidate_id,
                S.topic_confidence.c.alpha,
                S.topic_confidence.c.beta,
            ).where(S.topic_confidence.c.topic_id == topic_id)
        )
        return {r[0]: Posterior(float(r[1]), float(r[2])) for r in result.all()}

    async def examined_counts(self, topic_ids: list[str]) -> dict[str, int]:
        """Count examined topics per candidate (above Evidence Floor)."""
        if not topic_ids:
            return {}
        result = await self._s.execute(
            sa.select(
                S.topic_confidence.c.candidate_id,
                S.topic_confidence.c.alpha,
                S.topic_confidence.c.beta,
            ).where(S.topic_confidence.c.topic_id.in_(topic_ids))
        )
        counts: dict[str, int] = {}
        for candidate_id, alpha, beta in result.all():
            if Posterior(float(alpha), float(beta)).band.reportable:
                counts[candidate_id] = counts.get(candidate_id, 0) + 1
            else:
                counts.setdefault(candidate_id, 0)
        return counts

    async def all_for(self, candidate_id: str) -> dict[str, Posterior]:
        """Get all posteriors for a candidate."""
        result = await self._s.execute(
            sa.select(
                S.topic_confidence.c.topic_id,
                S.topic_confidence.c.alpha,
                S.topic_confidence.c.beta,
            ).where(S.topic_confidence.c.candidate_id == candidate_id)
        )
        return {r[0]: Posterior(float(r[1]), float(r[2])) for r in result.all()}