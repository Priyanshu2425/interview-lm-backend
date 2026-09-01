"""Session and Candidate readings.

Coverage and Mastery are separate outputs and there is no combined figure — the
rule is an absent API rather than a review comment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ...model.corpus import Corpus
from .math import Band, Posterior
from .reporting import TopicReading, coverage, mastery, read_topic
from .store import ConfidenceStore, EvidenceLedger, VisitLifecycle


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


class SummaryService:
    def __init__(
        self,
        corpus: Corpus,
        confidence: ConfidenceStore,
        visits: VisitLifecycle,
        evidence: EvidenceLedger,
        credits=None,
    ) -> None:
        self._c = corpus
        self._conf = confidence
        self._visits = visits
        self._ev = evidence
        self._credits = credits

    def rebind(self, corpus: Corpus) -> None:
        """Swap the Corpus in place — see `DossierLoader.rebind`."""
        self._c = corpus

    def for_session(self, session_row: dict) -> SessionSummary:
        sid = session_row["session_id"]
        cid = session_row["candidate_id"]
        # Answered *or* graded. Since ISSUE-0042 the loop stops at `answered`:
        # a question that was asked and answered examined its Topic whether or
        # not the Session has been graded yet, and counting only graded ones
        # would report a Session mid-flight as having examined nothing.
        rows = [
            v for v in self._visits.for_session(sid)
            if v["state"] in ("answered", "graded")
        ]
        by_mode = {"ground_truth": 0, "text_grounded": 0, "model_judgment": 0}
        for v in rows:
            if v["grading_mode"]:
                by_mode[v["grading_mode"]] += 1

        titles = {t.id: t.title for t in self._c.topics}
        module_of = {t.id: m for m in self._c.modules for t in m.topics}
        # Evidence carries its own titles and its own citations, snapshotted at
        # grading time. They are preferred over the live Corpus because the
        # Evidence outlives the material (ADR-0003, ISSUE-0025).
        #
        # Keyed by Topic, not by Visit (ISSUE-0044, ISSUE-0045). The unit of
        # Evidence is the Topic within a Session, so one spanning question
        # produces three rows that share a `topic_visit_id` — keyed by that,
        # two of the three would be dropped and the survivor would be read
        # against the wrong Topic.
        by_topic = {e["topic_id"]: e for e in self._ev.for_session(sid)}

        per_topic = []
        for v in rows:
            p = self._conf.get(cid, v["topic_id"])
            r = read_topic(v["topic_id"], p)
            row = by_topic.get(v["topic_id"], {})
            per_topic.append(
                {
                    **_reading_dict(r),
                    "title": (
                        row.get("topic_title_snapshot")
                        or titles.get(v["topic_id"], v["topic_id"])
                    ),
                    "module_title": (
                        row.get("module_title_snapshot")
                        or getattr(module_of.get(v["topic_id"]), "title", "")
                    ),
                    "graded_by": v["grading_mode"],
                    "citations": row.get("citations") or [],
                }
            )

        all_readings = [
            read_topic(tid, p) for tid, p in self._conf.all_for(cid).items()
        ]
        cov = coverage(all_readings, topics_total=len(self._c.topics))
        mas = mastery(all_readings)

        examined = {r.topic_id for r in all_readings if r.coverage > 0}
        untested = [
            {
                "module_id": m.id,
                "title": m.title,
                "topics_total": len(m.topics),
                "topics_untested": sum(1 for t in m.topics if t.id not in examined),
                "has_ground_truth": m.ground_truth_topic_count > 0,
            }
            for m in self._c.modules
        ]
        untested = [u for u in untested if u["topics_untested"] > 0]

        spend = {"credits": None, "per_topic": None}
        if self._credits is not None and session_row["payment_route"] == "credits":
            total = sum(self._credits.visit_cost(v["topic_visit_id"]) for v in rows)
            spend = {
                "credits": total,
                "per_topic": round(total / len(rows)) if rows else 0,
                "balance": self._credits.balance(cid),
            }

        return SessionSummary(
            session_id=sid,
            duration_seconds=session_row["duration_seconds"],
            provider=session_row["provider_chosen"],
            topics_examined=len(rows),
            ground_truth_visits=by_mode["ground_truth"],
            text_grounded_visits=by_mode["text_grounded"],
            model_judgment_visits=by_mode["model_judgment"],
            coverage=asdict(cov),
            mastery=asdict(mas),
            per_topic=per_topic,
            untested_modules=untested,
            spend=spend,
        )

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
            {**_reading_dict(r), "title": titles.get(r.topic_id, r.topic_id)}
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
                {**_reading_dict(r), "title": titles.get(r.topic_id, r.topic_id)}
                for r in sorted(readings, key=lambda x: -x.coverage)
            ],
        }


def _reading_dict(r: TopicReading) -> dict:
    return {
        "topic_id": r.topic_id,
        "band": r.band.value,
        "label": r.label,
        "coverage": round(r.coverage, 4),
        # None below the floor. Never 0 — that would read as "answered nothing
        # right" rather than "we have not asked".
        "mastery": None if r.mastery is None else round(r.mastery, 4),
        "interval": None if r.interval is None else [round(x, 4) for x in r.interval],
        "alpha": round(r.alpha, 4),
        "beta": round(r.beta, 4),
    }
