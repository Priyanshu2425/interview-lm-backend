"""Async Evidence Ledger — append-only evidence records."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import schema as S
from ...model.corpus import GradingMode
from ...service.confidence.math import Posterior, PRIOR, evidence_delta
from ...service.confidence.store import new_id


@dataclass(frozen=True, slots=True)
class EvidenceWrite:
    evidence_id: str
    already_existed: bool
    posterior: Posterior


class AsyncEvidenceLedger:
    """Async version of EvidenceLedger for API services."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def write(
        self,
        *,
        topic_visit_id: str,
        candidate_id: str,
        topic_id: str,
        session_id: str,
        score: float,
        mode: GradingMode,
        grader_kind: str,
        provider: str | None,
        rubric_version: str,
        rationale: str = "",
        exchange_snapshot: dict | None = None,
        citations: list[dict] | None = None,
        topic_title: str = "",
        module_title: str = "",
    ) -> EvidenceWrite:
        """Write evidence and update posterior in one transaction."""
        d = evidence_delta(score, mode.weight)
        ev_id = new_id("ev")

        # Check if already exists
        existing = await self._s.execute(
            sa.select(S.evidence.c.evidence_id).where(
                S.evidence.c.topic_visit_id == topic_visit_id
            )
        )
        if existing.scalar():
            # Read existing posterior
            post_result = await self._s.execute(
                sa.select(S.topic_confidence.c.alpha, S.topic_confidence.c.beta).where(
                    S.topic_confidence.c.candidate_id == candidate_id,
                    S.topic_confidence.c.topic_id == topic_id,
                )
            )
            row = post_result.first()
            post = PRIOR if row is None else Posterior(float(row[0]), float(row[1]))
            return EvidenceWrite(ev_id, True, post)

        # Insert evidence
        await self._s.execute(
            sa.insert(S.evidence).values(
                evidence_id=ev_id,
                topic_visit_id=topic_visit_id,
                candidate_id=candidate_id,
                topic_id=topic_id,
                session_id=session_id,
                score=Decimal(str(round(score, 3))),
                grading_mode=mode.value,
                weight=Decimal(str(mode.weight)),
                alpha_delta=Decimal(str(round(d.alpha_delta, 4))),
                beta_delta=Decimal(str(round(d.beta_delta, 4))),
                grader_kind=grader_kind,
                provider=provider,
                rubric_version=rubric_version,
                rationale=rationale,
                exchange_snapshot=exchange_snapshot,
                citations=citations,
                topic_title_snapshot=topic_title,
                module_title_snapshot=module_title,
            )
        )

        # Update posterior (upsert)
        await self._s.execute(
            text(
                f"""
                INSERT INTO {S.CORE}.topic_confidence
                    (candidate_id, topic_id, alpha, beta, updated_at)
                VALUES (:cid, :tid, :a, :b, now())
                ON CONFLICT (candidate_id, topic_id) DO UPDATE
                   SET alpha = {S.CORE}.topic_confidence.alpha + EXCLUDED.alpha - 1.0,
                       beta  = {S.CORE}.topic_confidence.beta  + EXCLUDED.beta  - 1.0,
                       updated_at = now()
                """
            ),
            {
                "cid": candidate_id,
                "tid": topic_id,
                "a": 1.0 + d.alpha_delta,
                "b": 1.0 + d.beta_delta,
            },
        )

        # Close the visit
        await self._s.execute(
            sa.update(S.topic_visit)
            .where(S.topic_visit.c.topic_visit_id == topic_visit_id)
            .values(state="graded", grading_mode=mode.value, graded_at=sa.func.now())
        )

        # Read new posterior
        post_result = await self._s.execute(
            sa.select(S.topic_confidence.c.alpha, S.topic_confidence.c.beta).where(
                S.topic_confidence.c.candidate_id == candidate_id,
                S.topic_confidence.c.topic_id == topic_id,
            )
        )
        row = post_result.first()
        post = PRIOR if row is None else Posterior(float(row[0]), float(row[1]))

        return EvidenceWrite(ev_id, False, post)

    async def rejudgeable(
        self, *, limit: int = 500, mode: str | None = None
    ) -> list[dict[str, Any]]:
        """Get stored exchanges for re-scoring."""
        q = sa.select(
            S.evidence.c.evidence_id,
            S.evidence.c.topic_visit_id,
            S.evidence.c.candidate_id,
            S.evidence.c.topic_id,
            S.evidence.c.score,
            S.evidence.c.grading_mode,
            S.evidence.c.provider,
            S.evidence.c.grader_kind,
            S.evidence.c.rubric_version,
            S.evidence.c.exchange_snapshot,
        ).order_by(S.evidence.c.created_at).limit(limit)
        if mode:
            q = q.where(S.evidence.c.grading_mode == mode)
        result = await self._s.execute(q)
        return [dict(r._mapping) for r in result.all()]

    async def for_session(self, session_id: str) -> list[dict[str, Any]]:
        """Get all evidence for a session."""
        result = await self._s.execute(
            sa.select(S.evidence)
            .where(S.evidence.c.session_id == session_id)
            .order_by(S.evidence.c.created_at)
        )
        return [dict(r._mapping) for r in result.all()]

    async def rows_for(self, candidate_id: str) -> list[dict[str, Any]]:
        """Get all evidence for a candidate."""
        result = await self._s.execute(
            sa.select(S.evidence)
            .where(S.evidence.c.candidate_id == candidate_id)
            .order_by(S.evidence.c.created_at)
        )
        return [dict(r._mapping) for r in result.all()]