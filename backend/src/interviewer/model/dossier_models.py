"""Everything the Interviewer holds to examine one Topic.

`DossierLoader` — which builds these from a Corpus and swaps it on refresh —
stays in `service/corpus/loader_service.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .corpus_models import GradingMode, Leaf

__all__ = ["Dossier"]


@dataclass(frozen=True, slots=True)
class Dossier:
    """Everything the Interviewer holds to examine one Topic."""

    topic_id: str
    topic_title: str
    module_id: str
    module_title: str
    module_order: int
    topic_order: int
    content: tuple[Leaf, ...]
    ground_truth_pairs: tuple[tuple[Leaf, Leaf], ...]
    syllabus: tuple[str, ...]
    grading_mode_ceiling: GradingMode

    @property
    def is_empty(self) -> bool:
        """True when the Topic exists but carries no retrievable text.

        A real state, distinguishable from not-found: the Topic is examinable
        under Model judgment, anchored to its syllabus.
        """
        return not self.content

    @property
    def approx_tokens(self) -> int:
        """A cheap, stable estimate. Used for budget reporting, never billing."""
        chars = sum(len(l.text or "") for l in self.content)
        return chars // 4

    def text_for_prompt(self, *, include_ground_truth: bool) -> str:
        """The dossier as the Interviewer sees it.

        `include_ground_truth` is False for the interviewing context whenever the
        question is not being written from that Assignment, and always False for
        anything the host holds in MCP Mode.
        """
        gt_ids = {gt.id for _, gt in self.ground_truth_pairs}
        parts = []
        for leaf in self.content:
            if leaf.id in gt_ids and not include_ground_truth:
                continue
            parts.append(f"## {leaf.title}\n\n{leaf.text}")
        return "\n\n".join(parts)
