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

from ...model.corpus import GradingMode
from ...db import schema as S
from ...db.evidence_reads import (
    for_session_stmt,
    rejudgeable_stmt,
    rows_for_stmt,
)
from .math import PRIOR, Posterior, evidence_delta


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:22]}"


def _unit(value: float | None) -> Decimal | None:
    """A sub-score on its way into the row. Absent stays absent — a reading
    nobody took is not a zero, and the column is nullable so it can say so."""
    return None if value is None else Decimal(str(round(value, 3)))


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

    def all_on_topic(self, topic_id: str) -> dict[str, Posterior]:
        """Every Candidate's posterior on one Topic, tested or not.

        Unfiltered on purpose. The rule that excludes an untested Candidate from
        a cohort belongs beside the rule that ranks a tested one (see
        `comparison.rank_within_topic`), not in a WHERE clause where the next
        reader has to reconstruct it from arithmetic on alpha and beta.
        """
        with self._e.connect() as c:
            rows = c.execute(
                sa.select(
                    S.topic_confidence.c.candidate_id,
                    S.topic_confidence.c.alpha,
                    S.topic_confidence.c.beta,
                ).where(S.topic_confidence.c.topic_id == topic_id)
            ).all()
        return {r[0]: Posterior(float(r[1]), float(r[2])) for r in rows}

    def examined_counts(self, topic_ids: list[str]) -> dict[str, int]:
        """Per Candidate, how many of these Topics read above the Evidence Floor.

        Counted here rather than in SQL for the same reason: the Floor is a
        property of the posterior's spread, and a query that approximated it
        with `alpha + beta > n` would be a second implementation of the rule.
        """
        if not topic_ids:
            return {}
        with self._e.connect() as c:
            rows = c.execute(
                sa.select(
                    S.topic_confidence.c.candidate_id,
                    S.topic_confidence.c.alpha,
                    S.topic_confidence.c.beta,
                ).where(S.topic_confidence.c.topic_id.in_(topic_ids))
            ).all()
        counts: dict[str, int] = {}
        for candidate_id, alpha, beta in rows:
            if Posterior(float(alpha), float(beta)).band.reportable:
                counts[candidate_id] = counts.get(candidate_id, 0) + 1
            else:
                counts.setdefault(candidate_id, 0)
        return counts

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
        d = evidence_delta(score, mode.weight)
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


class VisitLifecycle:
    """Opens a Visit, holds it open until graded, closes it on the Evidence write.

    The single place where "one Visit, one Evidence row" is enforced — and the
    partial unique index on (session_id) WHERE state IN ('open','answered') is
    what stops a Session advancing while a Visit is unresolved.
    """

    def __init__(self, engine: Engine) -> None:
        self._e = engine

    def open(
        self, *, session_id: str, candidate_id: str, topic_id: str, visit_index: int,
        topic_ids: tuple[str, ...] | list[str] | None = None,
        plan_item_id: str | None = None,
    ) -> str:
        """Open one question.

        `topic_id` is the owning Topic and stays scalar — `open_topic_ids()` and
        the refund path both need one. `topic_ids` is what the question actually
        spans, which since ISSUE-0042 is whatever the plan item said, and
        `plan_item_id` is the item that scheduled it.
        """
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
                    topic_ids=list(topic_ids) if topic_ids else [topic_id],
                    plan_item_id=plan_item_id,
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

    def close_question(
        self, topic_visit_id: str, *, turn_count: int,
        mode: GradingMode, grounding_ref: dict | None = None,
    ) -> None:
        """The question is finished. Nothing about it is graded (ISSUE-0042).

        `record_answer` above still exists and still writes the `exchange`
        blob, because MCP Mode grades per Visit against exactly that blob. The
        managed loop no longer does: its record is `message`, and writing a
        second copy here would leave two transcripts that can disagree.

        The state it lands in is `answered`, and that is now a terminal state
        for the loop rather than a queue for the grader — the Session moves on
        immediately, and the grade arrives once, at the end.
        """
        with self._e.begin() as c:
            c.execute(
                sa.update(S.topic_visit)
                .where(S.topic_visit.c.topic_visit_id == topic_visit_id)
                .values(
                    state="answered",
                    turn_count=turn_count,
                    grading_mode=mode.value,
                    grounding_ref=grounding_ref,
                    answered_at=sa.func.now(),
                )
            )

    def mark_graded(self, session_id: str) -> int:
        """Every answered Visit in a Session that has now been graded.

        ISSUE-0042 left `answered` terminal for the managed loop, because
        nothing graded a question any more. ISSUE-0044 grades the Session, and
        a question inside a graded Session owes nothing further — so it lands
        where a graded Visit always landed, and the material it examined can be
        withdrawn again (`open_topic_ids` reads open and answered).

        Session-wide rather than per Evidence row on purpose: a spanning
        question belongs to three Topics and is finished when all of them are.
        """
        with self._e.begin() as c:
            return c.execute(
                sa.update(S.topic_visit)
                .where(S.topic_visit.c.session_id == session_id,
                       S.topic_visit.c.state == "answered")
                .values(state="graded", graded_at=sa.func.now())
            ).rowcount

    def get(self, topic_visit_id: str) -> dict | None:
        with self._e.connect() as c:
            r = c.execute(
                sa.select(S.topic_visit).where(
                    S.topic_visit.c.topic_visit_id == topic_visit_id
                )
            ).first()
        return dict(r._mapping) if r else None

    def unresolved(self, session_id: str) -> dict | None:
        """Open or answered — MCP Mode's reading, where a grade is still owed.

        The managed loop asks `being_asked` instead: since ISSUE-0042 an
        answered question owes nothing until the Session ends.
        """
        with self._e.connect() as c:
            r = c.execute(
                sa.select(S.topic_visit).where(
                    S.topic_visit.c.session_id == session_id,
                    S.topic_visit.c.state.in_(("open", "answered")),
                )
            ).first()
        return dict(r._mapping) if r else None

    def being_asked(self, session_id: str) -> dict | None:
        """The question this Session is in the middle of, if it is in one."""
        with self._e.connect() as c:
            r = c.execute(
                sa.select(S.topic_visit).where(
                    S.topic_visit.c.session_id == session_id,
                    S.topic_visit.c.state == "open",
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
