"""The Judge — a separate call, blind to the conversation (ADR-0002).

It receives the question, the answer, and the grounding. It is not given
conversation history, and anyone later tempted to hand it history "for nuance"
is reintroducing the exact failure this exists to prevent.

The model that has just spent twenty minutes building rapport is the worst
available grader of that conversation. Sycophancy here is not a prompt defect —
it is conversational context working as intended.

Since ISSUE-0043 it reads two dimensions rather than one. "This answer covered
the material" and "this answer was right" are different questions, and a single
number answers whichever one the grader happened to weigh. A Candidate who
explains the course faithfully and a Candidate who is correct from somewhere
else are both worth knowing about, and they are no longer the same row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...model.corpus import GradingMode
from ...service.corpus.loader import Dossier
from ...service.graph.ports import ModelClient

RUBRIC_VERSION = "v2"

# The scale is one scale, applied twice. Two wordings would drift apart, and a
# SOURCE of 0.7 that meant something different from a TRUTH of 0.7 would make
# the combination below arithmetic on incommensurable numbers.
_SCALE = """Scale, for each number:
  1.0  correct, complete, and correctly reasoned
  0.7  correct with a gap or an imprecision
  0.5  the right idea reached with help, or half the answer
  0.3  a relevant fact, but the mechanism is wrong
  0.0  wrong, or no answer

An answer reached after hints is a real answer. Score what was ultimately
demonstrated. Judge the reasoning, not the confidence or the fluency."""

RUBRIC = """You are grading one interview answer. Return exactly three lines:

SOURCE: <a number from 0.0 to 1.0>
TRUTH: <a number from 0.0 to 1.0>
WHY: <one or two sentences, addressed to the candidate>

SOURCE is how much of the supplied material the answer explained. TRUTH is how
close to correct the answer is on the subject. They are separate readings and
one does not imply the other: an answer can be right and owe nothing to the
material, or faithful to the material and wrong.

""" + _SCALE

# Grading on the model's own knowledge asks for one number, because there is no
# material to have explained. Asking for SOURCE anyway would invite a figure
# about nothing, and a figure about nothing is worse than a missing one.
RUBRIC_UNGROUNDED = """You are grading one interview answer. Return exactly two lines:

TRUTH: <a number from 0.0 to 1.0>
WHY: <one or two sentences, addressed to the candidate>

TRUTH is how close to correct the answer is on the subject.

""" + _SCALE

_NO_SOURCE = "No source material. Grade on your own knowledge of the subject."


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

        `evidence_delta` receives this exactly as it received a score before,
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


class Judge:
    """Grades against Ground Truth where it exists, and against the dossier
    excerpt where it does not — so Grading Mode is a fact about the grounding
    rather than a setting."""

    def grade(
        self,
        *,
        question: str,
        exchange: list[dict],
        dossier: Dossier,
        mode: GradingMode,
        topic_visit_id: str,
        model: ModelClient,
    ) -> Verdict:
        answer = self._answer_only(exchange)
        grounding = self._grounding(dossier, mode)
        grounded = grounding != _NO_SOURCE

        # Note what is NOT here: the exchange, the hints, the probing, or any
        # signal about how the candidate came across.
        user = (
            f"QUESTION\n{question}\n\n"
            f"ANSWER\n{answer or '(no answer given)'}\n\n"
            f"{grounding}"
        )
        reply = model.complete(
            topic_visit_id=topic_visit_id, role="judge",
            system=RUBRIC if grounded else RUBRIC_UNGROUNDED, user=user,
        )
        return self._parse(reply.text, grounded=grounded)

    @staticmethod
    def _answer_only(exchange: list[dict]) -> str:
        """Only the candidate's words, and only as the final answer.

        Hints and probes shaped the answer; they are not evidence about it, and
        the Judge must not see who needed help.
        """
        return "\n\n".join(
            t["text"] for t in exchange
            if t.get("role") == "candidate" and t.get("text")
        ).strip()

    @staticmethod
    def _grounding(d: Dossier, mode: GradingMode) -> str:
        if mode is GradingMode.GROUND_TRUTH and d.ground_truth_pairs:
            _, key = d.ground_truth_pairs[0]
            return f"AUTHORITATIVE ANSWER\n{(key.text or '')[:6000]}"
        if mode is GradingMode.TEXT_GROUNDED and d.content:
            excerpt = d.text_for_prompt(include_ground_truth=False)[:6000]
            return f"COURSE MATERIAL\n{excerpt}"
        return _NO_SOURCE

    @staticmethod
    def _parse(text: str, *, grounded: bool = True) -> Verdict:
        """`grounded` is what the call actually sent, not what the mode is
        named. The two agree wherever a Verdict is written — the grounded modes
        supply material and `MODEL_JUDGMENT` does not — and where a dossier has
        lost the material its mode claims, the answer was still graded against
        nothing, so there is still no SOURCE to record."""
        truth = _sub_score(text, "TRUTH")
        if truth is None:
            # Raised rather than defaulted. A grade with no TRUTH line is a
            # grader that did not answer the question, and inventing a number
            # for it writes a measurement nobody made into a permanent record.
            raise ValueError(f"Judge returned no parseable TRUTH: {text[:120]!r}")
        source = _sub_score(text, "SOURCE") if grounded else None
        if grounded and source is None:
            raise ValueError(f"Judge returned no parseable SOURCE: {text[:120]!r}")
        why = re.search(r"WHY:\s*(.+)", text, re.I | re.S)
        return Verdict(source, truth, (why.group(1).strip() if why else "").strip())


def _sub_score(text: str, label: str) -> float | None:
    m = re.search(rf"{label}:\s*([0-9]*\.?[0-9]+)", text, re.I)
    if not m:
        return None
    value = float(m.group(1))
    if not 0.0 <= value <= 1.0:
        # Rejected rather than clamped: a score outside the unit interval means
        # the grader misunderstood, and silently squashing it would write that
        # misunderstanding into a permanent record.
        raise ValueError(f"{label.lower()} score outside 0..1: {value}")
    return value
