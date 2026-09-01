"""The Judge — a separate call, blind to the conversation (ADR-0002).

It receives the question, the answer, and the grounding. It is not given
conversation history, and anyone later tempted to hand it history "for nuance"
is reintroducing the exact failure this exists to prevent.

The model that has just spent twenty minutes building rapport is the worst
available grader of that conversation. Sycophancy here is not a prompt defect —
it is conversational context working as intended.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...model.corpus import GradingMode
from ...service.corpus.loader import Dossier
from ...service.graph.ports import ModelClient

RUBRIC_VERSION = "v1"

RUBRIC = """You are grading one interview answer. Return exactly two lines:

SCORE: <a number from 0.0 to 1.0>
WHY: <one or two sentences, addressed to the candidate>

Scale:
  1.0  correct, complete, and correctly reasoned
  0.7  correct with a gap or an imprecision
  0.5  the right idea reached with help, or half the answer
  0.3  a relevant fact, but the mechanism is wrong
  0.0  wrong, or no answer

An answer reached after hints is a real answer. Score what was ultimately
demonstrated. Judge the reasoning, not the confidence or the fluency."""


@dataclass(frozen=True, slots=True)
class Verdict:
    score: float
    rationale: str
    rubric_version: str = RUBRIC_VERSION


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

        # Note what is NOT here: the exchange, the hints, the probing, or any
        # signal about how the candidate came across.
        user = (
            f"QUESTION\n{question}\n\n"
            f"ANSWER\n{answer or '(no answer given)'}\n\n"
            f"{grounding}"
        )
        reply = model.complete(
            topic_visit_id=topic_visit_id, role="judge", system=RUBRIC, user=user
        )
        return self._parse(reply.text)

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
        return "No source material. Grade on your own knowledge of the subject."

    @staticmethod
    def _parse(text: str) -> Verdict:
        m = re.search(r"SCORE:\s*([0-9]*\.?[0-9]+)", text, re.I)
        if not m:
            raise ValueError(f"Judge returned no parseable score: {text[:120]!r}")
        score = float(m.group(1))
        if not 0.0 <= score <= 1.0:
            # Rejected rather than clamped: a score outside the unit interval
            # means the grader misunderstood, and silently squashing it would
            # write that misunderstanding into a permanent record.
            raise ValueError(f"score outside 0..1: {score}")
        why = re.search(r"WHY:\s*(.+)", text, re.I | re.S)
        return Verdict(score, (why.group(1).strip() if why else "").strip())
