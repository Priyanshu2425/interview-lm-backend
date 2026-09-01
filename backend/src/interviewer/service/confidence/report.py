"""The report a Candidate reads when the Session ends (ISSUE-0045).

No turn carries a score any more. The plan is fixed before the first question,
the transcript is what happened to it, and the whole reading arrives at once —
so this is the one place a Session's result is shown, and the only place it is
assembled.

Three refusals shape every field here, and each is enforced by an **absent**
one rather than by a comment asking the next reader to be careful:

* **Coverage and Mastery do not fuse.** They are two readings of one posterior
  and there is no third field holding a headline figure for the Topic, let
  alone for the Session.
* **`source_score` and `truth_score` are shown apart.** The Judge reads two
  dimensions (ISSUE-0043) and the number the two were combined into is an
  input to the posterior, not a reading — so `evidence.score` is deliberately
  not carried out of this module. Showing it would be the same fusion under a
  quieter name.
* **A Topic the Session never reached is named, never scored.** It gets the
  word and nothing else: no band, no mastery, no interval, not a zero. That is
  what ISSUE-0044 bought by writing no Evidence row for it, and an absent row
  is easy to render as a nought by accident — so unreached Topics are built
  into their own list, out of the shape that carries numbers at all.

Reached is read off the Evidence, not off the transcript or the plan: the
Evidence row *is* the measurement, and a Topic without one was not measured
whatever else happened around it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .reporting import read_topic
from .store import ConfidenceStore, EvidenceLedger

__all__ = ["ReportService", "SessionReport"]


@dataclass(frozen=True, slots=True)
class SessionReport:
    """What one finished Session is, as the Candidate reads it.

    `plan` is None for a Session that never had one — MCP Mode's, and anything
    started before ISSUE-0041. The reading still answers; a report is what a
    Session gets even when there is nothing much to say about it.
    """

    session_id: str
    state: str
    ended_reason: str | None
    duration_seconds: int
    provider: str | None
    plan: dict | None
    topics: list[dict]
    planned_not_reached: list[dict]


class ReportService:
    """Assembles the report. Reads only — the same Session reads the same twice.

    The Corpus arrives through the `DossierLoader`, which `refresh_corpus`
    already swaps in place, rather than as a second reference this would have
    to remember to rebind.
    """

    def __init__(
        self,
        loader,
        confidence: ConfidenceStore,
        evidence: EvidenceLedger,
        plans,
    ) -> None:
        self._loader = loader
        self._conf = confidence
        self._ev = evidence
        self._plans = plans

    # -- the whole of it ---------------------------------------------------

    def for_session(self, session_row: dict) -> SessionReport:
        sid = session_row["session_id"]
        cid = session_row["candidate_id"]

        graded = {row["topic_id"]: row for row in self._ev.for_session(sid)}
        plan = self._plans.get(sid)

        topics = [
            self._reading(cid, topic_id, row) for topic_id, row in graded.items()
        ]
        planned = _planned_topic_ids(plan)
        return SessionReport(
            session_id=sid,
            state=session_row["state"],
            ended_reason=session_row["ended_reason"],
            duration_seconds=session_row["duration_seconds"],
            provider=session_row["provider_chosen"],
            plan=self._plan_dict(plan, graded),
            topics=topics,
            planned_not_reached=[
                {"topic_id": tid, "title": self._title(tid)}
                for tid in planned
                if tid not in graded
            ],
        )

    # -- one reached Topic -------------------------------------------------

    def _reading(self, candidate_id: str, topic_id: str, row: dict) -> dict:
        """Everything measured about one Topic, and nothing derived across two.

        `mastery` is `Posterior.mastery_or_none` — absent below the Evidence
        Floor rather than small, because a Topic asked once is unknown and not
        weak. `interval` goes with it: an interval is a claim about a figure,
        and there is no figure.

        Titles come from the Evidence's own snapshot first. The row outlives
        the material it was taken against (ADR-0003), so a Topic retired since
        the Session still reports under the name it was examined by.
        """
        reading = read_topic(topic_id, self._conf.get(candidate_id, topic_id))
        return {
            "topic_id": topic_id,
            "title": row.get("topic_title_snapshot") or self._title(topic_id),
            "module_title": row.get("module_title_snapshot") or "",
            "band": reading.band.value,
            "label": reading.label,
            "coverage": round(reading.coverage, 4),
            # None below the floor, never 0 — see `Posterior.mastery_or_none`.
            "mastery": (
                None if reading.mastery is None else round(reading.mastery, 4)
            ),
            "interval": (
                None if reading.interval is None
                else [round(x, 4) for x in reading.interval]
            ),
            # The two dimensions, apart. Either may be absent: MODEL_JUDGMENT
            # has no Answer Key to check against, so `source_score` is None
            # there and a zero would read as "explained none of the material".
            "source_score": _number(row.get("source_score")),
            "truth_score": _number(row.get("truth_score")),
            "graded_by": row.get("grading_mode"),
            "question_count": row.get("question_count") or 0,
            "citations": row.get("citations") or [],
        }

    # -- the plan, and what became of it -----------------------------------

    def _plan_dict(self, plan, graded: dict) -> dict | None:
        """The plan as it was fixed, with each item's fate beside it.

        `state` is the item's own — `asked` or `unreached` once the Session has
        ended, `planned` while it is still running. It is passed through rather
        than recomputed: the plan is fixed at the database and what happened to
        it is one column, so a second derivation here could only disagree.
        """
        if plan is None:
            return None
        return {
            "budget_questions": plan.budget_questions,
            "suggested_seconds": plan.suggested_seconds,
            "chosen_seconds": plan.chosen_seconds,
            "breadth": plan.breadth,
            "items": [
                {
                    "plan_item_id": item.plan_item_id,
                    "item_order": item.item_order,
                    "focus": item.focus,
                    "state": item.state,
                    "topics": [
                        {
                            "topic_id": tid,
                            "title": self._title(tid),
                            "reached": tid in graded,
                        }
                        for tid in item.topic_ids
                    ],
                }
                for item in plan.items
            ],
        }

    def _title(self, topic_id: str) -> str:
        """A retired Topic keeps its place under its id rather than vanishing —
        the same rule `GET /sessions/{id}/plan` follows, for the same reason."""
        try:
            return self._loader.load(topic_id).topic_title
        except LookupError:
            return topic_id


def _planned_topic_ids(plan) -> list[str]:
    """Every Topic the plan named, once, in plan order."""
    if plan is None:
        return []
    seen: list[str] = []
    for item in plan.items:
        for tid in item.topic_ids:
            if tid not in seen:
                seen.append(tid)
    return seen


def _number(value) -> float | None:
    """A stored sub-score on its way out. Absent stays absent."""
    return None if value is None else round(float(value), 3)
