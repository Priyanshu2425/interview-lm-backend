"""Turns stored posteriors into the readings a Candidate or a Session sees.

Coverage and Mastery are separate outputs. There is no combined figure, and no
function here returns one — the rule is an absent API rather than a review
comment.
"""

from __future__ import annotations

from dataclasses import dataclass

from .confidence_models import Band, Posterior


@dataclass(frozen=True, slots=True)
class TopicReading:
    topic_id: str
    band: Band
    label: str
    coverage: float
    mastery: float | None          # None below the floor. Never 0.
    interval: tuple[float, float] | None
    alpha: float
    beta: float

    @classmethod
    def of(cls, topic_id: str, p: Posterior) -> "TopicReading":
        reportable = p.band.reportable
        return cls(
            topic_id=topic_id,
            band=p.band,
            label=p.band.label,
            coverage=p.coverage,
            mastery=p.mastery_or_none,
            interval=p.interval if reportable else None,
            alpha=p.alpha,
            beta=p.beta,
        )




@dataclass(frozen=True, slots=True)
class CoverageReading:
    """How much of the Corpus a Candidate has been examined on."""

    topics_examined: int
    topics_total: int
    effective_visits: float

    @classmethod
    def of(
        cls, readings: list[TopicReading], topics_total: int
    ) -> "CoverageReading":
        return cls(
            topics_examined=sum(1 for r in readings if r.coverage > 0),
            topics_total=topics_total,
            effective_visits=round(sum(r.coverage for r in readings), 4),
        )


@dataclass(frozen=True, slots=True)
class MasteryReading:
    """How well, among the Topics with enough evidence to say."""

    reportable_topics: int
    looks_solid: int
    looks_weak: int
    early_signal: int

    @classmethod
    def of(cls, readings: list[TopicReading]) -> "MasteryReading":
        return cls(
            reportable_topics=sum(
                1 for r in readings if r.band is not Band.UNTESTED
            ),
            looks_solid=sum(1 for r in readings if r.band is Band.FIRM_STRONG),
            looks_weak=sum(1 for r in readings if r.band is Band.FIRM_WEAK),
            early_signal=sum(1 for r in readings if r.band is Band.EARLY),
        )





