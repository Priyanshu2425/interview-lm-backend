"""Reading a Session: assembled once, projected four ways.

`GET /sessions/{id}`, `/plan`, `/report` and `/summary` are four questions about
one finished Session, and each of them used to assemble its own answer. That is
how the same Session came to disagree with itself: the report called a Topic
*reached* when it had an Evidence row, the summary called it *examined* when it
had an answered Visit, the plan was shaped three different ways, and the rule
that a retired Topic keeps its id as its title was written out three times.

None of those were disagreements about the Session. They were disagreements
about how to read it. So the read happens here, once, and the endpoints select
from it.

What stays out of here, deliberately: the *live* state of a running Session —
what the graph is parked on — which is the runner's to answer and nobody
else's.
"""

from __future__ import annotations

from dataclasses import dataclass

from .reporting import TopicReading, coverage, mastery, read_topic

__all__ = [
    "SessionFacts",
    "SessionReading",
    "SessionReadingService",
    "reached_topic_ids",
    "title_of",
    "topic_reading",
]


# -- the facts a Session row carries -----------------------------------------


@dataclass(frozen=True, slots=True)
class SessionFacts:
    """The Session row, named.

    Every reader of a Session used to take the raw row and reach into it for
    six keys, one of which — `provider_chosen` — is the database's name and not
    the domain's. An undeclared dict is an interface nobody can typo-check, and
    each reader had its own idea of which keys were required.
    """

    session_id: str
    candidate_id: str
    state: str
    parked_reason: str | None
    ended_reason: str | None
    duration_seconds: int
    provider: str | None
    payment_route: str | None

    @classmethod
    def of(cls, row: dict) -> "SessionFacts":
        return cls(
            session_id=row["session_id"],
            candidate_id=row["candidate_id"],
            state=row["state"],
            parked_reason=row.get("parked_reason"),
            ended_reason=row.get("ended_reason"),
            duration_seconds=row["duration_seconds"],
            provider=row.get("provider_chosen"),
            payment_route=row.get("payment_route"),
        )


# -- the rules that were written more than once ------------------------------


def title_of(loader, topic_id: str) -> str:
    """A retired Topic keeps its place under its id rather than vanishing.

    The plan is fixed on `topic_ids` — the identity — not on how they were
    captioned, so a Topic that has left the Corpus since still has somewhere to
    be shown. Written here once; it was written three times.
    """
    try:
        return loader.load(topic_id).topic_title
    except LookupError:
        return topic_id


def reached_topic_ids(visits=(), evidence=()) -> frozenset[str]:
    """The Topics this Session actually examined.

    One definition, because two endpoints reading the same Session must not
    disagree about which Topics it got to. A Topic is reached when the
    Candidate answered a Visit on it — an Evidence row implies one, and is
    counted too, because MCP Mode writes Evidence against Visits this loop did
    not open.

    Reached is not the same as graded. A Session parked for want of Credits
    reached Topics it has no Evidence for, and saying it never reached them
    would be a lie the Candidate can see through.
    """
    ids = {v["topic_id"] for v in visits if v["state"] in ("answered", "graded")}
    ids |= {e["topic_id"] for e in evidence}
    return frozenset(ids)


def topic_reading(r: TopicReading, *, with_posterior: bool = False) -> dict:
    """One Topic's reading, in the shape everything reads it in.

    `mastery` and `interval` are absent below the Evidence Floor rather than
    small: a Topic asked once is unknown, not weak, and a 0 there would be read
    as "answered nothing right". `coverage` and `mastery` sit side by side and
    are never fused — there is no third key here and there is not going to be.
    """
    out = {
        "topic_id": r.topic_id,
        "band": r.band.value,
        "label": r.label,
        "coverage": round(r.coverage, 4),
        "mastery": None if r.mastery is None else round(r.mastery, 4),
        "interval": (
            None if r.interval is None else [round(x, 4) for x in r.interval]
        ),
    }
    if with_posterior:
        # The two numbers themselves, for a caller that means to show the
        # evidence behind the band rather than the band.
        out["alpha"] = round(r.alpha, 4)
        out["beta"] = round(r.beta, 4)
    return out


def _number(value) -> float | None:
    """A stored sub-score on its way out. Absent stays absent."""
    return None if value is None else round(float(value), 3)


# -- one read ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SessionReading:
    """Everything one Session is, read once.

    Nothing here is derived across two Topics and nothing is a headline: this
    is the material the projections select from, and the refusals live in the
    projections' shapes.
    """

    facts: SessionFacts
    plan: object | None                     # SessionPlan, or None where none was made
    visits: tuple[dict, ...]
    evidence: tuple[dict, ...]
    reached: frozenset[str]

    @property
    def evidence_by_topic(self) -> dict[str, dict]:
        """Keyed by Topic, not by Visit: one spanning question produces three
        rows sharing a `topic_visit_id`, and keying by that drops two of them."""
        return {row["topic_id"]: row for row in self.evidence}

    @property
    def planned_topic_ids(self) -> list[str]:
        """Every Topic the plan named, once, in plan order."""
        if self.plan is None:
            return []
        seen: list[str] = []
        for item in self.plan.items:
            for tid in item.topic_ids:
                if tid not in seen:
                    seen.append(tid)
        return seen


class SessionReadingService:
    """Reads a Session. Reads only — the same Session reads the same twice.

    The Corpus arrives through the `DossierLoader`, which `refresh_corpus`
    swaps in place, rather than as a second reference this would have to
    remember to rebind.
    """

    def __init__(
        self, *, sessions, visits, evidence, plans, loader, confidence,
        corpus=None, credits=None,
    ) -> None:
        self._sessions = sessions
        self._visits = visits
        self._ev = evidence
        self._plans = plans
        self._loader = loader
        self._conf = confidence
        self._corpus = corpus
        self._credits = credits

    def rebind(self, corpus) -> None:
        """Swap the Corpus in place — see `DossierLoader.rebind`."""
        self._corpus = corpus

    # -- the read ----------------------------------------------------------

    def read(self, session_id: str) -> SessionReading | None:
        """The Session, or None where there is no such Session."""
        row = self._sessions.get(session_id)
        if row is None:
            return None
        return self.of_row(row)

    def of_row(self, row: dict) -> SessionReading:
        """The same read, for a caller that already holds the row."""
        sid = row["session_id"]
        visits = tuple(self._visits.for_session(sid))
        evidence = tuple(self._ev.for_session(sid))
        return SessionReading(
            facts=SessionFacts.of(row),
            plan=self._plans.get(sid) if self._plans is not None else None,
            visits=visits,
            evidence=evidence,
            reached=reached_topic_ids(visits, evidence),
        )

    # -- the projections ---------------------------------------------------

    def plan_view(self, session_id: str) -> dict | None:
        """The plan as it was fixed, with each item's fate beside it.

        Read twice, this returns the same bytes: the plan is fixed at the
        database (`trg_plan_item_fixed`), the items come back in `item_order`,
        and there is no writer on this path.

        `state` is the item's own — `asked` or `unreached` once the Session has
        ended, `planned` while it is still running. It is passed through rather
        than recomputed: the plan is fixed at the database and what happened to
        it is one column, so a second derivation here could only disagree.

        Titles are resolved rather than stored. A stored title is a copy of the
        Corpus that goes stale when a Topic is renamed.
        """
        reading = self.read(session_id)
        return None if reading is None else self.plan_of(reading)

    def plan_of(self, reading: SessionReading) -> dict | None:
        plan = reading.plan
        if plan is None:
            return None
        return {
            "session_id": plan.session_id,
            "budget_questions": plan.budget_questions,
            "suggested_seconds": plan.suggested_seconds,
            "chosen_seconds": plan.chosen_seconds,
            "breadth": plan.breadth,
            # Which planner produced this, and whether it had to fall back. A
            # fallback plan is still a plan; it is not the same claim, and a
            # reading that hid the difference would make the two identical.
            "planner_provider": plan.planner_provider,
            "planner_fallback": plan.planner_fallback,
            "items": [
                {
                    "plan_item_id": item.plan_item_id,
                    "item_order": item.item_order,
                    "focus": item.focus,
                    "state": item.state,
                    "topic_ids": list(item.topic_ids),
                    "topics": [
                        {
                            "topic_id": tid,
                            "title": title_of(self._loader, tid),
                            "reached": tid in reading.reached,
                        }
                        for tid in item.topic_ids
                    ],
                }
                for item in plan.items
            ],
        }

    def report(self, session_id: str):
        reading = self.read(session_id)
        return None if reading is None else self.report_of(reading)

    def report_of(self, reading: SessionReading):
        """The Session's result, as the Candidate reads it (ISSUE-0045)."""
        from .report import SessionReport

        f = reading.facts
        graded = reading.evidence_by_topic
        return SessionReport(
            session_id=f.session_id,
            state=f.state,
            ended_reason=f.ended_reason,
            duration_seconds=f.duration_seconds,
            provider=f.provider,
            plan=self.plan_of(reading),
            topics=[
                self._reading(f.candidate_id, topic_id, row)
                for topic_id, row in graded.items()
            ],
            planned_not_reached=[
                {"topic_id": tid, "title": title_of(self._loader, tid)}
                for tid in reading.planned_topic_ids
                if tid not in reading.reached
            ],
        )

    def summary(self, session_id: str):
        reading = self.read(session_id)
        return None if reading is None else self.summary_of(reading)

    def summary_of(self, reading: SessionReading):
        """The same Session, counted rather than narrated."""
        from .summary import SessionSummary

        f = reading.facts
        # Answered *or* graded. Since ISSUE-0042 the loop stops at `answered`:
        # a question that was asked and answered examined its Topic whether or
        # not the Session has been graded yet.
        rows = [v for v in reading.visits if v["state"] in ("answered", "graded")]
        by_mode = {"ground_truth": 0, "text_grounded": 0, "model_judgment": 0}
        for v in rows:
            if v["grading_mode"]:
                by_mode[v["grading_mode"]] += 1

        by_topic = reading.evidence_by_topic
        module_of = {t.id: m for m in self._corpus.modules for t in m.topics}
        per_topic = [
            {
                **topic_reading(
                    read_topic(v["topic_id"], self._conf.get(f.candidate_id,
                                                             v["topic_id"])),
                    with_posterior=True,
                ),
                # Evidence carries its own titles and citations, snapshotted at
                # grading time, and they are preferred over the live Corpus
                # because the Evidence outlives the material (ADR-0003).
                "title": (
                    by_topic.get(v["topic_id"], {}).get("topic_title_snapshot")
                    or title_of(self._loader, v["topic_id"])
                ),
                "module_title": (
                    by_topic.get(v["topic_id"], {}).get("module_title_snapshot")
                    or getattr(module_of.get(v["topic_id"]), "title", "")
                ),
                "graded_by": v["grading_mode"],
                "citations": by_topic.get(v["topic_id"], {}).get("citations") or [],
            }
            for v in rows
        ]

        all_readings = [
            read_topic(tid, p)
            for tid, p in self._conf.all_for(f.candidate_id).items()
        ]
        examined = {r.topic_id for r in all_readings if r.coverage > 0}
        untested = [
            {
                "module_id": m.id,
                "title": m.title,
                "topics_total": len(m.topics),
                "topics_untested": sum(1 for t in m.topics if t.id not in examined),
                "has_ground_truth": m.ground_truth_topic_count > 0,
            }
            for m in self._corpus.modules
        ]

        from dataclasses import asdict

        return SessionSummary(
            session_id=f.session_id,
            duration_seconds=f.duration_seconds,
            provider=f.provider,
            topics_examined=len(rows),
            ground_truth_visits=by_mode["ground_truth"],
            text_grounded_visits=by_mode["text_grounded"],
            model_judgment_visits=by_mode["model_judgment"],
            coverage=asdict(coverage(all_readings,
                                     topics_total=len(self._corpus.topics))),
            mastery=asdict(mastery(all_readings)),
            per_topic=per_topic,
            untested_modules=[u for u in untested if u["topics_untested"] > 0],
            spend=self._spend(f, rows),
        )

    # -- one reached Topic -------------------------------------------------

    def _reading(self, candidate_id: str, topic_id: str, row: dict) -> dict:
        """Everything measured about one Topic, and nothing derived across two.

        Titles come from the Evidence's own snapshot first. The row outlives
        the material it was taken against (ADR-0003), so a Topic retired since
        the Session still reports under the name it was examined by.
        """
        r = read_topic(topic_id, self._conf.get(candidate_id, topic_id))
        return {
            **topic_reading(r),
            "title": row.get("topic_title_snapshot")
                     or title_of(self._loader, topic_id),
            "module_title": row.get("module_title_snapshot") or "",
            # The two dimensions, apart. Either may be absent: MODEL_JUDGMENT
            # has no Answer Key to check against, so `source_score` is None
            # there and a zero would read as "explained none of the material".
            "source_score": _number(row.get("source_score")),
            "truth_score": _number(row.get("truth_score")),
            "graded_by": row.get("grading_mode"),
            "question_count": row.get("question_count") or 0,
            "citations": row.get("citations") or [],
        }

    def _spend(self, f: SessionFacts, rows: list[dict]) -> dict:
        if self._credits is None or f.payment_route != "credits":
            # BYOK carries null, never 0 — zero reads as "it was free".
            return {"credits": None, "per_topic": None}
        total = sum(self._credits.visit_cost(v["topic_visit_id"]) for v in rows)
        return {
            "credits": total,
            "per_topic": round(total / len(rows)) if rows else 0,
            "balance": self._credits.balance(f.candidate_id),
        }
