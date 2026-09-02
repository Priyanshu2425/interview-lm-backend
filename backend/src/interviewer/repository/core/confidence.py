"""Topic Confidence, on the graph's synchronous engine.

Tables we own (ADR-0003), read and written by graph nodes but owned by neither
the graph nor a framework abstraction. Reading Topic Confidence must not require
instantiating a graph, so nothing here imports one.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from ...db import schema as S
from ...model.confidence_models import PRIOR, Posterior

__all__ = ["ConfidenceStore"]


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
        `model.standing_models.Standing.of`), not in a WHERE clause where the next
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

    def posteriors_on(self, topic_ids: list[str]) -> dict[str, list[Posterior]]:
        """Every Candidate's posteriors across these Topics, unfiltered.

        Rows, not a count. Which of them read above the Evidence Floor is a
        property of the posterior's spread and is decided in `model.standing_models`,
        beside the cohort rules that use it — a WHERE clause approximating it
        with `alpha + beta > n` would be a second implementation of the rule,
        and a Python count in here would be the rule living in a repository.
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
        out: dict[str, list[Posterior]] = {}
        for candidate_id, alpha, beta in rows:
            out.setdefault(candidate_id, []).append(
                Posterior(float(alpha), float(beta))
            )
        return out

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
