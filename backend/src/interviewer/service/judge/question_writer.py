"""Writes a question, and records the Grading Mode it was actually grounded in.

The dossier's ceiling *bounds* the mode; it does not set it. A Topic with an
Answer Key may still yield a text-grounded question, and the Visit records what
happened rather than what was possible.

Since ISSUE-0042 a question may span up to three Topics, because that is what a
plan item may schedule. The mode it records is then the **weakest** across its
dossiers: a composite question is only as grounded as its least-grounded part,
and recording a Ground-Truth grade for a question half of which has no answer
key would be claiming an authority the material does not have.
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


def weakest(modes) -> GradingMode:
    """The least authoritative of several. Weight is the ordering."""
    return min(modes, key=lambda m: m.weight)


class QuestionWriter:
    def write(
        self, *, topic_visit_id: str, model: ModelClient,
        dossiers=None, dossier: Dossier | None = None, focus: str = "",
    ) -> WrittenQuestion:
        """One question over one or more dossiers.

        `dossier=` is still accepted for the single-Topic callers that predate
        the plan — MCP Mode and the rejudge path both hold exactly one.
        """
        ds = list(dossiers) if dossiers is not None else [dossier]
        ds = [x for x in ds if x is not None]
        if not ds:
            raise ValueError("a question must be grounded in at least one dossier")

        grounds = [self._ground(x) for x in ds]
        mode = weakest(g[0] for g in grounds)
        reply = model.complete(
            topic_visit_id=topic_visit_id,
            role="question_writer",
            system=SYSTEM,
            user=self._prompt(ds, grounds, focus),
        )
        return WrittenQuestion(
            reply.text.strip(), mode, self._grounding_ref(ds, grounds, mode)
        )

    # -- the prompt --------------------------------------------------------

    def _prompt(self, ds, grounds, focus: str) -> str:
        if len(ds) == 1:
            body = grounds[0][2]
            return f"{body}\n\nWhat this should test: {focus}" if focus else body

        # A spanning question is asked *as* one question. The material arrives
        # per Topic because that is how it is grounded, and the instruction to
        # ask one thing is stated once, at the end, where it is last read.
        parts = "\n\n---\n\n".join(g[2] for g in grounds)
        titles = ", ".join(d.topic_title for d in ds)
        return (
            f"{parts}\n\n---\n\n"
            f"Ask ONE question that a candidate could answer only by connecting "
            f"all of these topics: {titles}."
            + (f"\nWhat it should test: {focus}" if focus else "")
        )

    def _grounding_ref(self, ds, grounds, mode: GradingMode) -> dict | None:
        """What the question was grounded in, per Topic.

        A single Topic keeps the shape it has always had, so every reader of an
        older row keeps working. A spanning question cannot: it is grounded in
        several places at once, and flattening that would lose which citation
        belongs to which Topic.
        """
        if len(ds) == 1:
            return grounds[0][1]
        return {
            "kind": "spanning",
            "mode": mode.value,
            "parts": [
                {"topic_id": d.topic_id, **(ref or {})}
                for d, (_, ref, _) in zip(ds, grounds)
            ],
        }

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
