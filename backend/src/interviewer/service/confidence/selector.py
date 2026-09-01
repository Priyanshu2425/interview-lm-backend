"""Topic Selector — Thompson sampling over the in-scope Topics.

Draw one sample from each posterior and examine the weakest-or-least-known.
Untested Topics sample widely, so they are explored without a separate
exploration rule — which is the whole reason Topic Confidence is a distribution
rather than a score.

Two exemptions, both explicit:
  * the Session's opening Topic is chosen by curriculum order;
  * Topics already visited in this Session are excluded from the draw.

Randomness is injected, not called, so a Session replays exactly.

Since ISSUE-0041 the sampler answers a wider question than it used to. `rank`
orders every Topic in scope from one round of draws, and `choose` is its first
element — one implementation, consulted once before the first question rather
than after every Visit. That move is what let grading leave the loop, and it
did not change the distribution doing the deciding.
"""

from __future__ import annotations

from dataclasses import dataclass

from .store import ConfidenceStore


@dataclass(frozen=True, slots=True)
class TopicSelector:
    confidence: ConfidenceStore

    def rank(self, *, candidate_id: str, topic_ids: list[str], rng) -> list[str]:
        """Every Topic in scope, weakest-or-least-known first.

        One draw per Topic, in the order given, and the order of the draws is
        the order of the sort — so a ranking and a single choice consume the
        same randomness and a tie is broken by curriculum order in both.

        Every Topic comes back. A ranking that dropped the ones it thought
        uninteresting would be a plan deciding what is out of scope, and scope
        is the Candidate's to set.
        """
        if not topic_ids:
            raise ValueError("nothing in scope to choose from")
        posteriors = self.confidence.get_many(candidate_id, topic_ids)
        # Lowest sample first: we examine what looks weakest-or-least-known.
        draws = [
            (posteriors[tid].sample(rng), position, tid)
            for position, tid in enumerate(topic_ids)
        ]
        draws.sort()
        return [tid for _, _, tid in draws]

    def choose(self, *, candidate_id: str, topic_ids: list[str], rng) -> str:
        """The single weakest-looking Topic. The head of the ranking, so there
        is one sampler and not two that drift."""
        return self.rank(candidate_id=candidate_id, topic_ids=topic_ids, rng=rng)[0]
