"""The Evidence Ledger — append-only, idempotent, one writer.

Tables we own (ADR-0003), read and written by graph nodes but owned by neither
the graph nor a framework abstraction. Reading Topic Confidence must not require
instantiating a graph, so nothing here imports one.
"""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from ...db import schema as S
from ...db.evidence_reads import (
    for_session_stmt,
    rejudgeable_stmt,
    rows_for_stmt,
)
from ...model.confidence_models import PRIOR, EvidenceDelta, Posterior
from ...model.corpus_models import GradingMode
from ...model.evidence_models import EvidenceWrite
from ...util.ids_utils import new_id

__all__ = ["EvidenceLedger"]


def _unit(value: float | None) -> Decimal | None:
    """A sub-score on its way into the row. Absent stays absent — a reading
    nobody took is not a zero, and the column is nullable so it can say so."""
    return None if value is None else Decimal(str(round(value, 3)))

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
        # The two readings behind `score`, recorded beside it (ISSUE-0043).
        # Both default to None because a grader that reads one dimension — MCP
        # Mode's subagent, and every row written before rubric v2 — has neither,
        # and a zero there would read as "explained none of the material".
        source_score: float | None = None,
        truth_score: float | None = None,
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
        d = EvidenceDelta.of(score, mode.weight)
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

            _insert_evidence(
                c,
                values=dict(
                    evidence_id=ev_id,
                    topic_visit_id=topic_visit_id,
                    candidate_id=candidate_id,
                    topic_id=topic_id,
                    session_id=session_id,
                    score=Decimal(str(round(score, 3))),
                    source_score=_unit(source_score),
                    truth_score=_unit(truth_score),
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
                ),
            )
            _bump_posterior(c, candidate_id, topic_id, d)
            c.execute(
                sa.update(S.topic_visit)
                .where(S.topic_visit.c.topic_visit_id == topic_visit_id)
                .values(state="graded", grading_mode=mode.value, graded_at=sa.func.now())
            )
            post = _read_posterior(c, candidate_id, topic_id)

        return EvidenceWrite(ev_id, False, post)

    def write_topic(
        self,
        *,
        session_id: str,
        candidate_id: str,
        topic_id: str,
        score: float,
        mode: GradingMode,
        source_score: float | None = None,
        truth_score: float | None = None,
        question_count: int = 0,
        topic_visit_id: str | None = None,
        grader_kind: str,
        provider: str | None,
        rubric_version: str,
        rationale: str = "",
        exchange_snapshot: dict | None = None,
        citations: list[dict] | None = None,
        topic_title: str = "",
        module_title: str = "",
    ) -> EvidenceWrite:
        """One Beta observation for a Topic within a Session (ISSUE-0044).

        The same transaction as `write` above, keyed on the other unique
        constraint. `uq_evidence_session_topic` *is* ADR-0004 as amended: the
        count is unchanged, one observation per Topic per Session, and what
        moved is the unit — an observation may be assembled from several
        questions, and one spanning question may contribute to several.

        Idempotent on that constraint rather than on a prior read, so grading
        a Session twice — from the graph, from `/end`, from a resumption —
        writes nothing the second time even if the two calls race.

        `topic_visit_id` is the last question that examined the Topic, kept so
        the row stays traceable. It is not what makes the write unique: a
        spanning question produces one row per Topic and they share it.
        """
        d = EvidenceDelta.of(score, mode.weight)
        ev_id = new_id("ev")

        with self._e.begin() as c:
            inserted = _insert_evidence(
                c,
                values=dict(
                    evidence_id=ev_id,
                    topic_visit_id=topic_visit_id,
                    candidate_id=candidate_id,
                    topic_id=topic_id,
                    session_id=session_id,
                    score=Decimal(str(round(score, 3))),
                    source_score=_unit(source_score),
                    truth_score=_unit(truth_score),
                    question_count=question_count,
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
                ),
                on_conflict=("session_id", "topic_id"),
            )
            if not inserted:
                existing = c.execute(
                    sa.select(S.evidence.c.evidence_id).where(
                        S.evidence.c.session_id == session_id,
                        S.evidence.c.topic_id == topic_id,
                    )
                ).scalar()
                return EvidenceWrite(
                    existing, True, _read_posterior(c, candidate_id, topic_id)
                )
            _bump_posterior(c, candidate_id, topic_id, d)
            post = _read_posterior(c, candidate_id, topic_id)

        return EvidenceWrite(ev_id, False, post)

    def rejudgeable(self, *, limit: int = 500, mode: str | None = None) -> list[dict]:
        """Stored exchanges, ready to be re-scored by a reference grader."""
        return self._read(rejudgeable_stmt(limit=limit, mode=mode))

    def for_session(self, session_id: str) -> list[dict]:
        return self._read(for_session_stmt(session_id))

    def rows_for(self, candidate_id: str) -> list[dict]:
        return self._read(rows_for_stmt(candidate_id))

    def _read(self, stmt) -> list[dict]:
        """The projections come from `db.evidence_reads`, which the routes'
        engine reads through as well — one shape of an Evidence row, whichever
        engine fetched it."""
        with self._e.connect() as c:
            return [dict(r._mapping) for r in c.execute(stmt).all()]


def _insert_evidence(
    c: Connection, *, values: dict, on_conflict: tuple[str, ...] | None = None
) -> bool:
    """The row. `on_conflict` names the constraint a repeat write is allowed to
    lose to, and losing it is the whole of idempotency — returning False rather
    than raising, so the caller leaves the posterior alone.

    Whether it landed is read from RETURNING rather than from `rowcount`, which
    a plain INSERT reports as -1 — and -1 is truthy, so the cheap-looking check
    would call every conflict a write.
    """
    if on_conflict is None:
        c.execute(sa.insert(S.evidence).values(**values))
        return True

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    landed = c.execute(
        pg_insert(S.evidence)
        .values(**values)
        .on_conflict_do_nothing(index_elements=list(on_conflict))
        .returning(S.evidence.c.evidence_id)
    ).scalar()
    return landed is not None


def _bump_posterior(c: Connection, candidate_id: str, topic_id: str, d) -> None:
    """Never read-modify-write: a concurrent Visit would be lost."""
    c.execute(
        text(
            # Schema from the constant, never spelled out: the name is a
            # deployment's to choose, and a literal here is a table this
            # statement cannot find on a database that chose differently.
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


def _read_posterior(c: Connection, candidate_id: str, topic_id: str) -> Posterior:
    row = c.execute(
        sa.select(S.topic_confidence.c.alpha, S.topic_confidence.c.beta).where(
            S.topic_confidence.c.candidate_id == candidate_id,
            S.topic_confidence.c.topic_id == topic_id,
        )
    ).first()
    return PRIOR if row is None else Posterior(float(row[0]), float(row[1]))
