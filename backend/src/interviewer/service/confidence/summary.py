"""Session and Candidate readings.

Coverage and Mastery are separate outputs and there is no combined figure — the
rule is an absent API rather than a review comment.

A Session's summary is assembled by `SessionReadingService`, beside the report
it has to agree with; what is left here is the shape it arrives in, and the
readings that are about a **Candidate** rather than about one Session.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ...model.corpus import Corpus
from .math import Band
from .reading import topic_reading
from .reporting import coverage, mastery, read_topic
from .store import ConfidenceStore

__all__ = ["SessionSummary", "CandidateReadings"]


@dataclass(frozen=True, slots=True)
class SessionSummary:
    session_id: str
    duration_seconds: int
    provider: str | None
    topics_examined: int
    ground_truth_visits: int
    text_grounded_visits: int
    model_judgment_visits: int
    coverage: dict
    mastery: dict
    per_topic: list[dict]
    untested_modules: list[dict]
    spend: dict


class CandidateReadings:
    """What is true of a Candidate across every Session they have sat.

    Kept apart from the Session reading because it answers a different
    question: a Session's summary is about one sitting, and these are about a
    person. Nothing here takes a `session_id`.
    """

    def __init__(self, corpus: Corpus, confidence: ConfidenceStore) -> None:
        self._c = corpus
        self._conf = confidence

    def rebind(self, corpus: Corpus) -> None:
        """Swap the Corpus in place — see `DossierLoader.rebind`."""
        self._c = corpus

    def weakest(self, candidate_id: str, limit: int = 10) -> list[dict]:
        """Topics that look weakest, among those with enough evidence to say.

        Untested Topics are excluded rather than sorted to the bottom: they are
        not weak, they are unknown, and mixing them in is exactly the conflation
        the whole model exists to prevent.
        """
        titles = {t.id: t.title for t in self._c.topics}
        readings = [
            read_topic(tid, p) for tid, p in self._conf.all_for(candidate_id).items()
        ]
        judged = [r for r in readings if r.band is not Band.UNTESTED]
        judged.sort(key=lambda r: (r.mastery if r.mastery is not None else 1.0))
        return [
            {
                **topic_reading(r, with_posterior=True),
                "title": titles.get(r.topic_id, r.topic_id),
            }
            for r in judged[:limit]
        ]

    def candidate_readings(self, candidate_id: str) -> dict:
        """Coverage and Mastery for everything, as two separate readings."""
        stored = self._conf.all_for(candidate_id)
        readings = [read_topic(tid, p) for tid, p in stored.items()]
        titles = {t.id: t.title for t in self._c.topics}
        return {
            "coverage": asdict(coverage(readings, topics_total=len(self._c.topics))),
            "mastery": asdict(mastery(readings)),
            "topics": [
                {
                    **topic_reading(r, with_posterior=True),
                    "title": titles.get(r.topic_id, r.topic_id),
                }
                for r in sorted(readings, key=lambda x: -x.coverage)
            ],
        }
