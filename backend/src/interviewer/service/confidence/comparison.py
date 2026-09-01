"""Where a Candidate stands on one Topic — never where they stand overall.

> **PRODUCT.md, Principle 4** — *Refuse the number you cannot justify. No
> difficulty label, no fused Coverage-and-Mastery percentage.*

A leaderboard needs one figure per Candidate. Ranking on Mastery alone puts
somebody who answered two questions perfectly above somebody who answered two
hundred at ninety percent; ranking on Coverage alone rewards volume over
understanding; fusing them is the refusal, verbatim. So the comparison happens
**inside a Topic**, where Mastery means one thing and needs no fusing.

Three rules hold it honest, and two are existing rules applied again.

**Only tested Candidates are in the cohort.** A Candidate whose Band is
`UNTESTED` is not counted as zero — that is the fabrication *untested is not
zero* exists to prevent, and it would drag every reading down in proportion to
how many people had not got there yet.

**A Cohort Floor.** Below it there is no rank at all: it reads *not enough
Candidates yet* and shows no number, the same shape and the same reasoning as
*Untested*.

**Coverage is compared as Coverage**, separately, by a different function
returning a different shape. Nothing here combines the two, and nothing here
returns a Candidate's overall position.

## Why a rank can be shared

Mastery is the mean of a Beta posterior and carries a spread, so 0.82 and 0.81
may be the same measurement twice. A Candidate is ranked by how many others are
**definitely** above them — whose credible interval sits entirely above theirs —
so two Candidates the mathematics cannot separate hold the same position.

Overlap is not transitive, and this definition is what makes that harmless: a
rank counts Candidates who are unambiguously higher, which is well defined
whether or not the middle of the field forms a chain.
"""

from __future__ import annotations

from dataclasses import dataclass

from .math import Posterior

#: Fewest tested Candidates a Topic needs before any rank is shown.
#:
#: **Provisional, and derived from nothing.** Unlike the Evidence Floor this is
#: a privacy judgement rather than a measurement: `#1 of 2` discloses the other
#: Candidate completely and `#3 of 4` nearly so, and ten is the smallest cohort
#: in which one person's position does not describe everybody else's. It should
#: be revisited once there is data on how thinly Candidates spread across 71
#: Topics — a floor that is never reached is the same as a feature that does not
#: exist (SPEC-0006 §Still open).
COHORT_FLOOR = 10


@dataclass(frozen=True, slots=True)
class Standing:
    """Where one Candidate sits on one Topic, or why they do not sit anywhere.

    `rank` is None whenever the reading is unavailable, and `reason` always says
    which of the several reasons it is. A surface that has to guess between
    "not enough people" and "you have not been examined here" will guess wrong
    in the direction that flatters.
    """

    topic_id: str
    rank: int | None = None
    cohort: int = 0
    #: Whether other Candidates hold this same position because the mathematics
    #: cannot separate them — `#7= of 340` rather than `#7 of 340`.
    shared: bool = False
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.rank is not None


def rank_within_topic(
    topic_id: str,
    *,
    candidate_id: str,
    posteriors: dict[str, Posterior],
    cohort_floor: int = COHORT_FLOOR,
) -> Standing:
    """A rank inside one Topic, over the Candidates the Evidence Floor admits.

    `posteriors` is every Candidate's posterior on this Topic, tested or not.
    The filtering happens here rather than at the query, so the rule that
    excludes an untested Candidate is in the same place as the rule that ranks
    a tested one.
    """
    tested = {
        cid: p for cid, p in posteriors.items() if p.band.reportable
    }
    if candidate_id not in tested:
        # Not "you are last": there is no measurement of them to compare, and
        # counting the absence as zero is the fabrication this product refuses.
        return Standing(
            topic_id,
            cohort=len(tested),
            reason=(
                "this Topic reads Untested for you, so there is nothing to "
                "compare — an untested Topic is not a zero"
            ),
        )
    if len(tested) < cohort_floor:
        return Standing(
            topic_id,
            cohort=len(tested),
            reason=(
                f"not enough Candidates yet — {len(tested)} of the "
                f"{cohort_floor} a comparison needs have been examined here"
            ),
        )

    mine = tested[candidate_id]
    my_low, my_high = mine.interval
    above = 0
    shared = False
    for cid, other in tested.items():
        if cid == candidate_id:
            continue
        low, high = other.interval
        if low > my_high:
            # Definitely above: their whole credible interval clears mine.
            above += 1
        elif high >= my_low:
            # Overlapping. Not separable, so not separated.
            shared = True
    return Standing(
        topic_id,
        rank=above + 1,
        cohort=len(tested),
        shared=shared,
    )


@dataclass(frozen=True, slots=True)
class CoverageStanding:
    """How much of the material a Candidate has been examined on, compared.

    A second, separate reading. It is never combined with `Standing` into a
    position, and there is no function anywhere that takes both.
    """

    topics_examined: int
    topics_available: int
    cohort: int = 0
    #: The share of the cohort this Candidate has examined more Topics than.
    #: Deliberately not a rank: Coverage is a count of classes opened, and a
    #: position in a list of counts reads as a standing it is not.
    percentile: int | None = None
    reason: str | None = None


def coverage_percentile(
    *,
    candidate_id: str,
    examined: dict[str, int],
    topics_available: int,
    cohort_floor: int = COHORT_FLOOR,
) -> CoverageStanding:
    """Coverage against the cohort's Coverage, and nothing else.

    `examined` counts, per Candidate, the Topics whose Band is reportable — the
    same gate the rank uses, for the same reason.
    """
    mine = examined.get(candidate_id, 0)
    tested = {cid: n for cid, n in examined.items() if n > 0}
    if mine == 0:
        return CoverageStanding(
            topics_examined=0,
            topics_available=topics_available,
            cohort=len(tested),
            reason="no Topic reads above the Evidence Floor for you yet",
        )
    if len(tested) < cohort_floor:
        return CoverageStanding(
            topics_examined=mine,
            topics_available=topics_available,
            cohort=len(tested),
            reason=(
                f"not enough Candidates yet — {len(tested)} of the "
                f"{cohort_floor} a comparison needs have been examined"
            ),
        )
    below = sum(1 for cid, n in tested.items() if cid != candidate_id and n < mine)
    return CoverageStanding(
        topics_examined=mine,
        topics_available=topics_available,
        cohort=len(tested),
        percentile=round(100 * below / (len(tested) - 1)),
    )
