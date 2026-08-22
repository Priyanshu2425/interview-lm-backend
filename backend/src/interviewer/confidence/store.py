"""Topic Confidence Store, Evidence Ledger, Topic Visit Lifecycle.

Tables we own (ADR-0003), read and written by graph nodes but owned by neither
the graph nor a framework abstraction. Reading Topic Confidence must not require
instantiating a graph, so nothing here imports one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from ..corpus.contract import GradingMode
from ..db import schema as S
from .math import PRIOR, Posterior, evidence_delta


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:22]}"


@dataclass(frozen=True, slots=True)
class EvidenceWrite:
    evidence_id: str
    already_existed: bool
    posterior: Posterior


class ConfidenceStore:
    """Read and write posteriors. Five columns, one mutable table."""

    def __init__(self, engine: Engine) -> None:
        self._e = engine

    def get(self, candidate_id: str, topic_id: str) -> Posterior:
        """A missing row and a prior row are the same thing to every reader."""
        with self._e.connect() as c:
            row = c.execute(
                sa.select(S.topic_confidence.c.alpha, S.topic_confidence.c.beta).where(
                    S.topic_confidence.c.candidate_id == candidate_id,
                    S.topic_confidence.c.topic_id == topic_id,
                )
            ).first()
        return PRIOR if row is None else Posterior(float(row[0]), float(row[1]))

    def get_many(self, candidate_id: str, topic_ids: list[str]) -> dict[str, Posterior]:
        with self._e.connect() as c:
            rows = c.execute(
                sa.select(
                    S.topic_confidence.c.topic_id,
                    S.topic_confidence.c.alpha,
                    S.topic_confidence.c.beta,
                ).where(
                    S.topic_confidence.c.candidate_id == candidate_id,
                    S.topic_confidence.c.topic_id.in_(topic_ids),
                )
            ).all()
        stored = {r[0]: Posterior(float(r[1]), float(r[2])) for r in rows}
        return {tid: stored.get(tid, PRIOR) for tid in topic_ids}

    def all_for(self, candidate_id: str) -> dict[str, Posterior]:
        with self._e.connect() as c:
            rows = c.execute(
                sa.select(
                    S.topic_confidence.c.topic_id,
                    S.topic_confidence.c.alpha,
                    S.topic_confidence.c.beta,
                ).where(S.topic_confidence.c.candidate_id == candidate_id)
            ).all()
        return {r[0]: Posterior(float(r[1]), float(r[2])) for r in rows}


class EvidenceLedger:
    """Append-only, idempotent on topic_visit_id.

    The write is a constraint, not a check: a second write for the same Visit is
    a no-op that returns the existing row. That is what survives MCP Mode, where
    the caller is a ReAct agent we do not control.
    """

    def __init__(self, engine: Engine) -> None:
        self._e = engine

    def write(
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
        """Close a Topic Visit. One transaction (SPEC-0002 §6).

        Evidence insert, posterior update and Visit close commit together. A
        conflict on topic_visit_id aborts the whole transaction, leaving the
        posterior untouched — which is the correct behaviour for a repeated
        grade and is what makes the write idempotent in fact.
        """
        d = evidence_delta(score, mode.weight)
        ev_id = new_id("ev")

        with self._e.begin() as c:
            existing = c.execute(
                sa.select(S.evidence.c.evidence_id).where(
                    S.evidence.c.topic_visit_id == topic_visit_id
                )
            ).scalar()
            if existing:
                post = _read_posterior(c, candidate_id, topic_id)
                return EvidenceWrite(existing, True, post)

            c.execute(
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
            # Never read-modify-write: a concurrent Visit would be lost.
            c.execute(
                text(
                    """
                    INSERT INTO core.topic_confidence
                        (candidate_id, topic_id, alpha, beta, updated_at)
                    VALUES (:cid, :tid, :a, :b, now())
                    ON CONFLICT (candidate_id, topic_id) DO UPDATE
                       SET alpha = core.topic_confidence.alpha + EXCLUDED.alpha - 1.0,
                           beta  = core.topic_confidence.beta  + EXCLUDED.beta  - 1.0,
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
            c.execute(
                sa.update(S.topic_visit)
                .where(S.topic_visit.c.topic_visit_id == topic_visit_id)
                .values(state="graded", grading_mode=mode.value, graded_at=sa.func.now())
            )
            post = _read_posterior(c, candidate_id, topic_id)

        return EvidenceWrite(ev_id, False, post)

    def rejudgeable(self, *, limit: int = 500, mode: str | None = None) -> list[dict]:
        """Stored exchanges, ready to be re-scored by a reference grader.

        This is what makes a provider normaliser derivable from production data
        rather than guessed — and it is why no normaliser is built now.
        """
        q = sa.select(
            S.evidence.c.evidence_id, S.evidence.c.topic_visit_id,
            S.evidence.c.candidate_id, S.evidence.c.topic_id,
            S.evidence.c.score, S.evidence.c.grading_mode,
            S.evidence.c.provider, S.evidence.c.grader_kind,
            S.evidence.c.rubric_version, S.evidence.c.exchange_snapshot,
        ).order_by(S.evidence.c.created_at).limit(limit)
        if mode:
            q = q.where(S.evidence.c.grading_mode == mode)
        with self._e.connect() as c:
            return [dict(r._mapping) for r in c.execute(q).all()]

    def for_session(self, session_id: str) -> list[dict]:
        with self._e.connect() as c:
            return [
                dict(r._mapping)
                for r in c.execute(
                    sa.select(S.evidence)
                    .where(S.evidence.c.session_id == session_id)
                    .order_by(S.evidence.c.created_at)
                ).all()
            ]

    def rows_for(self, candidate_id: str) -> list[dict]:
        with self._e.connect() as c:
            return [
                dict(r._mapping)
                for r in c.execute(
                    sa.select(S.evidence)
                    .where(S.evidence.c.candidate_id == candidate_id)
                    .order_by(S.evidence.c.created_at)
                ).all()
            ]


def _read_posterior(c: Connection, candidate_id: str, topic_id: str) -> Posterior:
    row = c.execute(
        sa.select(S.topic_confidence.c.alpha, S.topic_confidence.c.beta).where(
            S.topic_confidence.c.candidate_id == candidate_id,
            S.topic_confidence.c.topic_id == topic_id,
        )
    ).first()
    return PRIOR if row is None else Posterior(float(row[0]), float(row[1]))


class VisitLifecycle:
    """Opens a Visit, holds it open until graded, closes it on the Evidence write.

    The single place where "one Visit, one Evidence row" is enforced — and the
    partial unique index on (session_id) WHERE state IN ('open','answered') is
    what stops a Session advancing while a Visit is unresolved.
    """

    def __init__(self, engine: Engine) -> None:
        self._e = engine

    def open(
        self, *, session_id: str, candidate_id: str, topic_id: str, visit_index: int
    ) -> str:
        vid = new_id("visit")
        with self._e.begin() as c:
            c.execute(
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

    def record_answer(
        self, topic_visit_id: str, *, exchange: dict, turn_count: int,
        mode: GradingMode, grounding_ref: dict | None = None,
    ) -> None:
        """Store the exchange at the Answer Turn, before grading.

        This is what makes resumption work: an interrupted Session whose answer
        was submitted but not graded already has the exchange, so resumption
        grades it rather than discarding the Candidate's work.
        """
        with self._e.begin() as c:
            c.execute(
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

    def get(self, topic_visit_id: str) -> dict | None:
        with self._e.connect() as c:
            r = c.execute(
                sa.select(S.topic_visit).where(
                    S.topic_visit.c.topic_visit_id == topic_visit_id
                )
            ).first()
        return dict(r._mapping) if r else None

    def unresolved(self, session_id: str) -> dict | None:
        with self._e.connect() as c:
            r = c.execute(
                sa.select(S.topic_visit).where(
                    S.topic_visit.c.session_id == session_id,
                    S.topic_visit.c.state.in_(("open", "answered")),
                )
            ).first()
        return dict(r._mapping) if r else None

    def open_topic_ids(self) -> set[str]:
        """Topics with a Visit still in flight, anywhere.

        A Visit that has opened must be able to finish: it either produces
        Evidence or it corrupts the record it exists to build. So material it is
        being examined on cannot be withdrawn while it runs (ISSUE-0027).
        """
        with self._e.connect() as c:
            return {
                r[0] for r in c.execute(
                    sa.select(S.topic_visit.c.topic_id).where(
                        S.topic_visit.c.state.in_(("open", "answered"))
                    )
                )
            }

    def visited_topic_ids(self, session_id: str) -> set[str]:
        with self._e.connect() as c:
            return {
                r[0]
                for r in c.execute(
                    sa.select(S.topic_visit.c.topic_id).where(
                        S.topic_visit.c.session_id == session_id
                    )
                ).all()
            }

    def for_session(self, session_id: str) -> list[dict]:
        with self._e.connect() as c:
            return [
                dict(r._mapping)
                for r in c.execute(
                    sa.select(S.topic_visit)
                    .where(S.topic_visit.c.session_id == session_id)
                    .order_by(S.topic_visit.c.visit_index)
                ).all()
            ]

    def abandon(self, topic_visit_id: str) -> None:
        with self._e.begin() as c:
            c.execute(
                sa.update(S.topic_visit)
                .where(
                    S.topic_visit.c.topic_visit_id == topic_visit_id,
                    S.topic_visit.c.state.in_(("open", "answered")),
                )
                .values(state="abandoned")
            )
