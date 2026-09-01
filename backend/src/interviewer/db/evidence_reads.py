"""The Evidence projections, written once.

An Evidence row is read from two engines — the graph's synchronous one and the
routes' asynchronous one — and for a while each engine had its own hand-written
copy of the same three selects. Copies of a projection drift the way copies of
an invariant drift (ADR-0009), and this one drifted: the async copy was still
selecting the columns of the day before the Judge began reading two dimensions.

So the statement is built here and executed there. There is one shape of an
Evidence row leaving the database, whichever engine fetched it.
"""

from __future__ import annotations

import sqlalchemy as sa

from . import schema as S

__all__ = ["rejudgeable_stmt", "for_session_stmt", "rows_for_stmt"]


def rejudgeable_stmt(*, limit: int = 500, mode: str | None = None):
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
    return q


def for_session_stmt(session_id: str):
    """Every Evidence row this Session produced, in the order it produced them."""
    return (
        sa.select(S.evidence)
        .where(S.evidence.c.session_id == session_id)
        .order_by(S.evidence.c.created_at)
    )


def rows_for_stmt(candidate_id: str):
    """Every Evidence row this Candidate has ever been given."""
    return (
        sa.select(S.evidence)
        .where(S.evidence.c.candidate_id == candidate_id)
        .order_by(S.evidence.c.created_at)
    )
