"""What the Judge and the Interviewer produce.

Each shape carries the rules that are true of it — `Verdict.score` is the
fusion rule (ADR-0002 keeps it here, not in the posterior's maths). The calls
that produce these, and the model client they need, stay in `service/judge/`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .corpus_models import GradingMode

__all__ = ["RUBRIC_VERSION", "Verdict", "Move", "WrittenQuestion"]

# The rubric the Judge grades against. A Verdict records the version it was
# graded under, so a rubric change is findable in the Evidence (ADR-0002).
RUBRIC_VERSION = "v2"

Action = Literal["probe", "hint", "close"]


@dataclass(frozen=True, slots=True)
class Verdict:
    """Two readings, and the one number the posterior is allowed to see.

    `source_score` is None exactly where there was no source to explain, which
    is what `MODEL_JUDGMENT` means. It is not a zero: an answer graded against
    nothing did not fail to explain the material, it was never asked to.
    """

    source_score: float | None
    truth_score: float
    rationale: str
    rubric_version: str = RUBRIC_VERSION

    @property
    def score(self) -> float:
        """The combination, stated once and here rather than in `math.py`.

        `EvidenceDelta.of` receives this exactly as it received a score before,
        so Coverage, the bands and the Evidence Floor keep working without
        knowing the Judge learned to read twice.

        This is an input to the posterior, never a reading. `source_score` and
        `truth_score` are reported separately and are never shown fused —
        the refusal `AGENTS.md` already makes for Coverage and Mastery, for the
        same reason: the average of two different questions answers neither.
        """
        if self.source_score is None:
            return self.truth_score
        return 0.5 * self.source_score + 0.5 * self.truth_score


@dataclass(frozen=True, slots=True)
class Move:
    action: Action
    text: str


@dataclass(frozen=True, slots=True)
class WrittenQuestion:
    question: str
    mode: GradingMode
    grounding_ref: dict | None
