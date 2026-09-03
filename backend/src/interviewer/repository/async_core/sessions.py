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

    async def ensure_candidate(self, candidate_id: str, name: str | None = None) -> str:
        """The Candidate row exists after this, whoever created it.

        It built this statement and returned without executing it, and was a
        sync `def` on an async store — so awaiting it was impossible and calling
        it did nothing. Harmless only because `IdentityStore.resolve` inserts the
        row first, which meant the one place that could write a name was a no-op
        nobody had reason to notice. ISSUE-0048 gives the name a writer, so the
        statement has to run.

        Still an upsert that does nothing on conflict: a Candidate who has
        already answered must not have their answers reset by a later sign-in.
        """
        await self._s.execute(
            sa.dialects.postgresql.insert(S.candidate)
            .values(candidate_id=candidate_id, display_name=name)
            .on_conflict_do_nothing(index_elements=["candidate_id"])
        )
        return candidate_id

    async def profile(self, candidate_id: str) -> dict[str, Any] | None:
        """What this Candidate has told us. None if there is no row yet."""
        result = await self._s.execute(
            sa.select(S.candidate).where(S.candidate.c.candidate_id == candidate_id)
        )
        row = result.first()
        return dict(row._mapping) if row else None

    async def record_onboarding(
        self, candidate_id: str, answers: dict[str, Any]
    ) -> dict[str, Any]:
        """Write the answers given, and stamp `onboarded_at` only the first time.

        `answers` carries the fields the caller actually sent; the ones it omits
        are absent from the UPDATE rather than written as defaults, so a
        correction to one answer cannot erase the other three.

        The stamp is `COALESCE(onboarded_at, now())` rather than a read followed
        by a conditional write. Two requests arriving together would both read
        null and both stamp, and the second would move a date whose only job is
        to record when the person actually finished. Postgres settles it in the
        row, so there is no window in which it can be settled wrongly.
        """
        result = await self._s.execute(
            sa.update(S.candidate)
            .where(S.candidate.c.candidate_id == candidate_id)
            .values(
                **answers,
                onboarded_at=sa.func.coalesce(S.candidate.c.onboarded_at, sa.func.now()),
            )
            .returning(S.candidate)
        )
        return dict(result.first()._mapping)

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

    async def for_candidate(self, candidate_id: str) -> list[dict[str, Any]]:
        """Every Session this Candidate has sat, newest first.

        Three counts travel with each row because the alternative is the
        surface asking per Session and assembling the answer itself, which is
        the client deciding something the server owns (ADR-0009):

        * `budget_questions` — how many the plan fixed. Null for a Session
          that predates the planner, and for MCP Mode, which has no plan.
        * `asked` — plan items that have been put. A Session's position in its
          own plan, which is a fact about what happened.
        * `measured` — Evidence rows, one per Topic the Session measured.

        None of the three says how well it went, and there is nothing here
        that could: a Session has no reading. Coverage and Mastery are two
        readings of one Topic, and a Session is not a Topic.
        """
        asked = (
            sa.select(
                S.plan_item.c.session_id,
                sa.func.count().label("asked"),
            )
            .where(S.plan_item.c.state == "asked")
            .group_by(S.plan_item.c.session_id)
            .subquery()
        )
        measured = (
            sa.select(
                S.evidence.c.session_id,
                sa.func.count().label("measured"),
            )
            .group_by(S.evidence.c.session_id)
            .subquery()
        )
        result = await self._s.execute(
            sa.select(
                S.session,
                S.session_plan.c.budget_questions,
                sa.func.coalesce(asked.c.asked, 0).label("asked"),
                sa.func.coalesce(measured.c.measured, 0).label("measured"),
            )
            .select_from(S.session)
            .outerjoin(
                S.session_plan,
                S.session_plan.c.session_id == S.session.c.session_id,
            )
            .outerjoin(asked, asked.c.session_id == S.session.c.session_id)
            .outerjoin(measured, measured.c.session_id == S.session.c.session_id)
            .where(S.session.c.candidate_id == candidate_id)
            .order_by(S.session.c.started_at.desc(), S.session.c.session_id)
        )
        return [dict(r) for r in result.mappings()]

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
    # There is no `plan` here. It was a second hand-written reader of
    # `session_plan` + `plan_item`, shaped differently from the one the report
    # reads, and the two shapes drifted apart. `SessionReadingService` reads
    # the plan now, once, for `/plan` and `/report` alike.

    async def transcript(self, session_id: str) -> list[dict[str, Any]]:
        """Every turn of the Session, in the order it happened (ISSUE-0042).

        Read-only, like `plan` above and for the same reason: `message` is
        append-only at the database, and the one writer is the loop.
        """
        rows = (await self._s.execute(
            sa.select(S.message)
            .where(S.message.c.session_id == session_id)
            .order_by(S.message.c.seq)
        )).all()
        return [
            {
                "seq": r._mapping["seq"],
                "role": r._mapping["role"],
                "kind": r._mapping["kind"],
                "text": r._mapping["text"],
                "topic_ids": list(r._mapping["topic_ids"] or []),
                "topic_visit_id": r._mapping["topic_visit_id"],
                "plan_item_id": r._mapping["plan_item_id"],
            }
            for r in rows
        ]
