"""The Session record — ours, and outliving its checkpoint (SPEC-0002 §1)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from ...db import schema as S
# Re-exported, never redeclared. The rubric's version is the Judge's fact; a
# Session and an Evidence row only record which rubric graded them, and a second
# literal here is how a Session comes to claim a rubric the Judge never ran.
from ..judge.judge_service import RUBRIC_VERSION

__all__ = ["RUBRIC_VERSION", "SessionConfig", "SessionStore"]


@dataclass(frozen=True, slots=True)
class SessionConfig:
    """Chosen before the Session begins; immutable afterwards."""

    scope_module_ids: tuple[str, ...]
    duration_seconds: int
    provider: str | None = "deepseek"
    payment_route: str = "credits"
    mode: str = "managed"

    def __post_init__(self) -> None:
        if not self.scope_module_ids:
            raise ValueError("a Session must be scoped to at least one Module")
        if self.duration_seconds <= 0:
            raise ValueError("a Session must have a positive duration")


class SessionStore:
    def __init__(self, engine: Engine) -> None:
        self._e = engine

    def ensure_candidate(self, candidate_id: str, name: str | None = None) -> str:
        with self._e.begin() as c:
            c.execute(
                sa.dialects.postgresql.insert(S.candidate)
                .values(candidate_id=candidate_id, display_name=name)
                .on_conflict_do_nothing(index_elements=["candidate_id"])
            )
        return candidate_id

    def create(self, candidate_id: str, cfg: SessionConfig) -> str:
        sid = f"sess_{uuid.uuid4().hex[:22]}"
        with self._e.begin() as c:
            c.execute(
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

    def get(self, session_id: str) -> dict | None:
        with self._e.connect() as c:
            r = c.execute(
                sa.select(S.session).where(S.session.c.session_id == session_id)
            ).first()
        return dict(r._mapping) if r else None

    # -- when the deadline starts running -----------------------------------
    #
    # `started_at` is when the row was written, which is when the Candidate
    # *asked for* a Session — before the microphone was allowed, before the
    # surface was ready, and before they had seen a question. Running the
    # deadline from it charged them for setting up (ISSUE-0050).
    #
    # `clock_started_at` is when they said they were ready. Null until they do,
    # and a Session that is never begun has no deadline at all, because it was
    # never sat.

    def begin(self, session_id: str, at: float) -> float | None:
        """Stamp when this Session began, once. Returns the stamp either way.

        Idempotent on purpose rather than by accident: the surface calls this
        from a button, and a button is pressed twice. The second press must
        return the first answer, or a Candidate could win back the minutes they
        have already spent by pressing it again.

        `at` comes from the injected clock rather than from Postgres, so a test
        driving a `FrozenClock` sees the time it set.
        """
        stamp = datetime.fromtimestamp(at, tz=timezone.utc)
        with self._e.begin() as c:
            c.execute(
                sa.update(S.session)
                .where(
                    S.session.c.session_id == session_id,
                    S.session.c.clock_started_at.is_(None),
                )
                .values(clock_started_at=stamp)
            )
            return self._clock_started(c, session_id)

    def clock_started_at(self, session_id: str) -> float | None:
        """When the deadline started running, or None if it has not."""
        with self._e.connect() as c:
            return self._clock_started(c, session_id)

    @staticmethod
    def _clock_started(c, session_id: str) -> float | None:
        got = c.execute(
            sa.select(S.session.c.clock_started_at)
            .where(S.session.c.session_id == session_id)
        ).scalar()
        return got.timestamp() if got is not None else None

    def park(self, session_id: str, reason: str) -> None:
        with self._e.begin() as c:
            c.execute(
                sa.update(S.session)
                .where(S.session.c.session_id == session_id)
                .values(state="parked", parked_reason=reason)
            )

    def resume(self, session_id: str, at: float | None = None) -> None:
        """Carry on, and start the clock again from here.

        Re-stamping is not new behaviour: `_continue_from_boundary` has always
        put `clock.now()` into the graph's `started_at`, so every resume has
        always given the Session its full duration back. That is defensible —
        Credits running out is not the Candidate's fault, and neither is the
        hour they took to top up — and ISSUE-0050 is about the setup screen,
        not about park. Moving the origin into the record without re-stamping
        here would have quietly ended a Session the moment it resumed.
        """
        with self._e.begin() as c:
            values: dict = {"state": "running", "parked_reason": None}
            if at is not None and self._clock_started(c, session_id) is not None:
                values["clock_started_at"] = datetime.fromtimestamp(
                    at, tz=timezone.utc
                )
            c.execute(
                sa.update(S.session)
                .where(S.session.c.session_id == session_id)
                .values(**values)
            )

    def end(self, session_id: str, reason: str) -> None:
        with self._e.begin() as c:
            c.execute(
                sa.update(S.session)
                .where(S.session.c.session_id == session_id)
                .values(state="ended", ended_reason=reason, ended_at=sa.func.now())
            )
