"""The Session record — ours, and outliving its checkpoint (SPEC-0002 §1)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

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

    def park(self, session_id: str, reason: str) -> None:
        with self._e.begin() as c:
            c.execute(
                sa.update(S.session)
                .where(S.session.c.session_id == session_id)
                .values(state="parked", parked_reason=reason)
            )

    def resume(self, session_id: str) -> None:
        with self._e.begin() as c:
            c.execute(
                sa.update(S.session)
                .where(S.session.c.session_id == session_id)
                .values(state="running", parked_reason=None)
            )

    def end(self, session_id: str, reason: str) -> None:
        with self._e.begin() as c:
            c.execute(
                sa.update(S.session)
                .where(S.session.c.session_id == session_id)
                .values(state="ended", ended_reason=reason, ended_at=sa.func.now())
            )
