"""Writes a question, and records the Grading Mode it was actually grounded in.

The dossier's ceiling *bounds* the mode; it does not set it. A Topic with an
Answer Key may still yield a text-grounded question, and the Visit records what
happened rather than what was possible.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...model.corpus import GradingMode
from ...service.corpus.loader import Dossier
from ...service.graph.ports import ModelClient

SYSTEM = (
    "You are interviewing a candidate. Ask exactly one question, in one or two "
    "sentences. Do not greet, do not preamble, do not answer it yourself. "
    "Never state or hint at the expected answer."
)


@dataclass(frozen=True, slots=True)
class WrittenQuestion:
    question: str
    mode: GradingMode
    grounding_ref: dict | None


class QuestionWriter:
    def write(
        self, *, dossier: Dossier, topic_visit_id: str, model: ModelClient
    ) -> WrittenQuestion:
        mode, grounding, prompt = self._ground(dossier)
        reply = model.complete(
            topic_visit_id=topic_visit_id,
            role="question_writer",
            system=SYSTEM,
            user=prompt,
        )
        return WrittenQuestion(reply.text.strip(), mode, grounding)

    def _ground(self, d: Dossier) -> tuple[GradingMode, dict | None, str]:
        # 1. An Assignment with its Answer Key — a ready-made question with a rubric.
        if d.ground_truth_pairs:
            prompt_leaf, key_leaf = d.ground_truth_pairs[0]
            return (
                GradingMode.GROUND_TRUTH,
                {"kind": "ground_truth", "prompt_leaf_id": prompt_leaf.id,
                 "ground_truth_leaf_id": key_leaf.id},
                f"Topic: {d.topic_title}\n\n"
                f"Below is assessment material with a worked solution. Turn ONE of "
                f"its questions into a spoken interview question.\n\n"
                f"{(prompt_leaf.text or '')[:6000]}",
            )
        # 2. Topic text, no Answer Key — a real examination, at reduced weight.
        if d.content:
            return (
                GradingMode.TEXT_GROUNDED,
                {"kind": "text", "leaf_ids": [l.id for l in d.content[:3]]},
                f"Topic: {d.topic_title}\n\n"
                f"Ask one interview question answerable from this material.\n\n"
                f"{d.text_for_prompt(include_ground_truth=False)[:6000]}",
            )
        # 3. No text at all — the interviewer's own knowledge, anchored to the
        #    syllabus and Module order so scope still holds.
        return (
            GradingMode.MODEL_JUDGMENT,
            {"kind": "syllabus", "syllabus": list(d.syllabus)},
            f"Topic: {d.topic_title} (Module: {d.module_title})\n"
            f"Syllabus: {', '.join(d.syllabus) or d.topic_title}\n\n"
            f"Ask one interview question on this topic.",
        )
