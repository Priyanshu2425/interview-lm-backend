"""Topic Selector — Thompson sampling over the in-scope Topics.

Draw one sample from each posterior and examine the highest. Untested Topics
sample widely, so they are explored without a separate exploration rule — which
is the whole reason Topic Confidence is a distribution rather than a score.

Two exemptions, both explicit:
  * the Session's opening Topic is chosen by curriculum order;
  * Topics already visited in this Session are excluded from the draw.

Randomness is injected, not called, so a Session replays exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

from .store import ConfidenceStore


@dataclass(frozen=True, slots=True)
class TopicSelector:
    confidence: ConfidenceStore

    def choose(self, *, candidate_id: str, topic_ids: list[str], rng) -> str:
        if not topic_ids:
            raise ValueError("nothing in scope to choose from")
        posteriors = self.confidence.get_many(candidate_id, topic_ids)
        best, best_draw = topic_ids[0], -1.0
        for tid in topic_ids:
            draw = posteriors[tid].sample(rng)
            # Lowest sample wins: we examine what looks weakest-or-least-known.
            if best_draw < 0 or draw < best_draw:
                best, best_draw = tid, draw
        return best
