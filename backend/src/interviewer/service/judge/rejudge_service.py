"""Re-judging stored exchanges (PRD-0002 §29).

Every Evidence row stores the question, the answer, the grounding reference,
the Grading Mode, the grader and the rubric version — so any score can be
re-taken later by any grader. This is what makes mis-weighted history
rebuildable rather than written off, and it is why no provider normaliser is
invented in advance.

**It writes nothing.** Evidence is append-only and permanent; a re-judgement is
a measurement of the grader, not a correction of the record.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...model.corpus_models import GradingMode
from ...service.corpus.loader_service import DossierLoader
from ...service.graph.ports import ModelClient
from .judge_service import Judge


@dataclass(frozen=True, slots=True)
class Comparison:
    evidence_id: str
    topic_visit_id: str
    topic_id: str
    original_score: float
    original_provider: str | None
    original_grader: str
    reference_score: float
    delta: float


@dataclass(frozen=True, slots=True)
class BatchResult:
    compared: list[Comparison]

    @property
    def mean_delta(self) -> float:
        return (
            sum(c.delta for c in self.compared) / len(self.compared)
            if self.compared else 0.0
        )

    def by_provider(self) -> dict[str, float]:
        """The measurement a future normaliser would be derived from — if the
        data ever supports one."""
        buckets: dict[str, list[float]] = {}
        for c in self.compared:
            buckets.setdefault(c.original_provider or "none", []).append(c.delta)
        return {k: round(sum(v) / len(v), 4) for k, v in buckets.items()}


class ReJudge:
    def __init__(self, loader: DossierLoader, judge: Judge | None = None) -> None:
        self._loader = loader
        self._judge = judge or Judge()

    def run(self, rows: list[dict], *, reference: ModelClient) -> BatchResult:
        out: list[Comparison] = []
        for row in rows:
            turns = (row.get("exchange_snapshot") or {}).get("turns", [])
            if not turns:
                continue
            question = next(
                (t["text"] for t in turns if t.get("kind") == "question"), ""
            )
            dossier = self._loader.load(row["topic_id"])
            verdict = self._judge.grade(
                question=question, exchange=turns, dossier=dossier,
                mode=GradingMode(row["grading_mode"]),
                topic_visit_id=row["topic_visit_id"], model=reference,
            )
            original = float(row["score"])
            out.append(Comparison(
                evidence_id=row["evidence_id"],
                topic_visit_id=row["topic_visit_id"],
                topic_id=row["topic_id"],
                original_score=original,
                original_provider=row.get("provider"),
                original_grader=row["grader_kind"],
                reference_score=verdict.score,
                delta=round(verdict.score - original, 4),
            ))
        return BatchResult(out)
