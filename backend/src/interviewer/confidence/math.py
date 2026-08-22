"""Confidence Math — pure functions over (alpha, beta).

The deepest module in the system and the one everything else depends on being
right. No storage, no clock, no randomness it does not receive.

One structure, three readings (CONTEXT.md):
  Mastery    is its mean,          alpha / (alpha + beta)
  Coverage   is its evidence,      alpha + beta  (reported net of the prior)
  Confidence is its spread,        the width of a credible interval

An untested Topic is not a zero. It is the prior, and it reads as *unknown*
rather than *weak*. There is deliberately no function here that returns a bare
Mastery number for a Topic below the Evidence Floor.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from scipy.stats import beta as _beta

# The uniform prior. One named constant; it is what makes an untested Topic read
# as unknown rather than as zero.
PRIOR_ALPHA: Final = 1.0
PRIOR_BETA: Final = 1.0

# CONTEXT.md requires the bands be "read off the posterior as a credible
# interval, not chosen by hand", so the boundaries are interval *widths*, not
# counts of answers. These two numbers are the only constants, and they are
# properties of how sure a reading must be before it is shown.
CI_MASS: Final = 0.80
BAND_UNKNOWN: Final = 0.70   # interval at least this wide: say nothing
BAND_FIRM: Final = 0.40      # interval narrower than this: say it plainly
WEAK_CEILING: Final = 0.60   # a firm reading whose upper bound sits below this


class Band(str, Enum):
    UNTESTED = "untested"
    EARLY = "early"
    FIRM_WEAK = "firm_weak"
    FIRM_STRONG = "firm_strong"

    @property
    def label(self) -> str:
        return {
            Band.UNTESTED: "Untested",
            Band.EARLY: "Early signal",
            Band.FIRM_WEAK: "Looks weak",
            Band.FIRM_STRONG: "Looks solid",
        }[self]

    @property
    def reportable(self) -> bool:
        """Whether a number may be shown at all."""
        return self is not Band.UNTESTED


class NotReportable(ValueError):
    """Asked for a figure the Evidence Floor does not permit."""


@dataclass(frozen=True, slots=True)
class Posterior:
    """A Topic Confidence, and every reading that can be taken from it."""

    alpha: float
    beta: float

    def __post_init__(self) -> None:
        if self.alpha < PRIOR_ALPHA or self.beta < PRIOR_BETA:
            raise ValueError(
                f"posterior below the prior floor: ({self.alpha}, {self.beta})"
            )

    # -- readings ----------------------------------------------------------

    @property
    def coverage(self) -> float:
        """Effective Topic Visits. Not a count of questions.

        Reported net of the prior so an untested Topic reads 0 rather than 2.
        Recorded as a deliberate divergence from CONTEXT.md's `alpha + beta`.
        """
        return (self.alpha + self.beta) - (PRIOR_ALPHA + PRIOR_BETA)

    @property
    def interval(self) -> tuple[float, float]:
        lo, hi = _beta.interval(CI_MASS, self.alpha, self.beta)
        return float(lo), float(hi)

    @property
    def width(self) -> float:
        lo, hi = self.interval
        return hi - lo

    @property
    def band(self) -> Band:
        w = self.width
        if w >= BAND_UNKNOWN:
            return Band.UNTESTED
        if w >= BAND_FIRM:
            return Band.EARLY
        return Band.FIRM_WEAK if self.interval[1] < WEAK_CEILING else Band.FIRM_STRONG

    @property
    def mastery(self) -> float:
        """The mean — only where the floor permits it.

        This raises rather than returning a number, because a Candidate shown
        "38%" after one bad answer will study to a figure that is barely a guess.
        """
        if not self.band.reportable:
            raise NotReportable(
                "this Topic is below the Evidence Floor; it reads as Untested"
            )
        return self.alpha / (self.alpha + self.beta)

    @property
    def mastery_or_none(self) -> float | None:
        return None if not self.band.reportable else self.mastery

    def sample(self, rng) -> float:
        """One draw, for Thompson sampling. Randomness is injected, not called."""
        return float(rng.beta(self.alpha, self.beta))


PRIOR: Final = Posterior(PRIOR_ALPHA, PRIOR_BETA)


@dataclass(frozen=True, slots=True)
class EvidenceDelta:
    """What one graded Topic Visit contributes."""

    alpha_delta: float
    beta_delta: float


def evidence_delta(score: float, weight: float) -> EvidenceDelta:
    """alpha += w*s and beta += w*(1-s).

    `s` and `w` measure different things and are never conflated. `w` is how far
    the Grading Mode is trusted; `s` is how good the answer was. Hint assistance
    lands in `s` — an answer reached after two hints is a real answer worth
    roughly half — and never as a reduced weight.
    """
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"score must be in 0..1, got {score}")
    if weight not in (1.0, 0.7, 0.5):
        raise ValueError(f"weight must be a known Grading Mode weight, got {weight}")
    return EvidenceDelta(weight * score, weight * (1.0 - score))


def apply_evidence(p: Posterior, score: float, weight: float) -> Posterior:
    d = evidence_delta(score, weight)
    return Posterior(p.alpha + d.alpha_delta, p.beta + d.beta_delta)
