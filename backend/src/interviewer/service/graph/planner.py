"""The Session plan — decided once, before the first question (ISSUE-0041).

Until now the next Topic was drawn from the sampler after every Visit, so the
shape of a Session was an emergent property nobody could see in advance — not
the Candidate, not the report, not the Session itself. Here the Topics are
ranked once, the questions are planned once, the plan is written down, and it is
never changed.

Thompson sampling did not die; it moved. ADR-0005 put the sampler *inside* the
loop, where it needed a posterior updated after every Visit — and that in-loop
position is the only reason grading had to happen mid-Session. The same sampler
now runs once, before the first question, over what previous Sessions
established. The Candidate gets a legible plan instead of an invisible sampler,
and the same distribution decides it.

Two rules hold this module up.

**The plan may not fail.** Planning is the first thing that happens in a
Session, so a model that answers in prose, or with eleven items when asked for
five, or with a Topic that is not in scope, must not produce a 500. Every
validation failure falls back to deterministic contiguous chunking of the ranked
list and records `planner_fallback` on the row, so a fallback plan is visible in
the record rather than indistinguishable from a good one.

**The plan is fixed.** `trg_plan_item_fixed` refuses an UPDATE of a plan item's
Topics, order or focus, and fixedness survives a restart because the plan is in
Postgres rather than only in the checkpointer — `build_plan` reads a stored plan
instead of making a second one.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from ...db import schema as S
from .pacing import MAX_TOPICS_PER_QUESTION, budget_questions, suggested_seconds

__all__ = ["PlanItem", "SessionPlan", "PlanStore", "SessionPlanner"]


@dataclass(frozen=True, slots=True)
class PlanItem:
    """One question, and the one to three Topics it will span."""

    item_order: int
    topic_ids: tuple[str, ...]
    focus: str
    plan_item_id: str = ""
    state: str = "planned"


@dataclass(frozen=True, slots=True)
class SessionPlan:
    """What the Session will ask, in the order it will ask it.

    `suggested_seconds` and `chosen_seconds` are both kept because they are two
    different readings of one scope: a plan built for forty minutes and run in
    twenty is a Session that examined less, and the report has to be able to
    say so.
    """

    session_id: str
    budget_questions: int
    suggested_seconds: int
    chosen_seconds: int
    breadth: str
    items: tuple[PlanItem, ...]
    planner_provider: str | None = None
    planner_fallback: bool = False


# -- persistence -------------------------------------------------------------


class PlanStore:
    """Writes a plan once, in one transaction, and reads it back.

    There is no `update`. The trigger would refuse one, and an API that offered
    the call would be inviting the refusal.
    """

    def __init__(self, engine: Engine) -> None:
        self._e = engine

    def save(self, plan: SessionPlan) -> SessionPlan:
        """The header and its items together, or neither.

        A `session_plan` row with no items is a Session that believes it has a
        plan and cannot run it, which is worse than no plan at all.
        """
        items = tuple(
            PlanItem(
                item_order=i.item_order,
                topic_ids=i.topic_ids,
                focus=i.focus,
                plan_item_id=i.plan_item_id or f"item_{uuid.uuid4().hex[:22]}",
                state=i.state,
            )
            for i in plan.items
        )
        with self._e.begin() as c:
            c.execute(sa.insert(S.session_plan).values(
                session_id=plan.session_id,
                budget_questions=plan.budget_questions,
                suggested_seconds=plan.suggested_seconds,
                chosen_seconds=plan.chosen_seconds,
                breadth=plan.breadth,
                planner_provider=plan.planner_provider,
                planner_fallback=plan.planner_fallback,
            ))
            for item in items:
                c.execute(sa.insert(S.plan_item).values(
                    plan_item_id=item.plan_item_id,
                    session_id=plan.session_id,
                    item_order=item.item_order,
                    topic_ids=list(item.topic_ids),
                    focus=item.focus,
                    state=item.state,
                ))
        return replace(plan, items=items)

    def next_planned(self, session_id: str) -> PlanItem | None:
        """The first item still waiting to be asked, in plan order.

        The plan is the queue. Asking the database rather than carrying a
        cursor in the checkpointer means a restart resumes where the Session
        actually got to, not where a copy of the plan thought it had.
        """
        with self._e.connect() as c:
            r = c.execute(
                sa.select(S.plan_item)
                .where(S.plan_item.c.session_id == session_id,
                       S.plan_item.c.state == "planned")
                .order_by(S.plan_item.c.item_order)
                .limit(1)
            ).first()
        if r is None:
            return None
        m = r._mapping
        return PlanItem(
            item_order=m["item_order"],
            topic_ids=tuple(m["topic_ids"]),
            focus=m["focus"],
            plan_item_id=m["plan_item_id"],
            state=m["state"],
        )

    def mark_asked(self, plan_item_id: str) -> None:
        """The item has been opened. `state` is the one column the trigger lets
        move, which is exactly the difference between the plan and what happened
        to it."""
        with self._e.begin() as c:
            c.execute(
                sa.update(S.plan_item)
                .where(S.plan_item.c.plan_item_id == plan_item_id)
                .values(state="asked")
            )

    def mark_unreached(self, session_id: str) -> int:
        """Everything still `planned` when the Session ended.

        A Session that ran out of clock leaves questions unasked, and the
        difference between "asked and answered badly" and "never reached" is
        the whole reason `unreached` is a state rather than an absence.
        """
        with self._e.begin() as c:
            return c.execute(
                sa.update(S.plan_item)
                .where(S.plan_item.c.session_id == session_id,
                       S.plan_item.c.state == "planned")
                .values(state="unreached")
            ).rowcount

    def get(self, session_id: str) -> SessionPlan | None:
        with self._e.connect() as c:
            head = c.execute(
                sa.select(S.session_plan)
                .where(S.session_plan.c.session_id == session_id)
            ).first()
            if head is None:
                return None
            rows = c.execute(
                sa.select(S.plan_item)
                .where(S.plan_item.c.session_id == session_id)
                .order_by(S.plan_item.c.item_order)
            ).all()
        h = head._mapping
        return SessionPlan(
            session_id=session_id,
            budget_questions=h["budget_questions"],
            suggested_seconds=h["suggested_seconds"],
            chosen_seconds=h["chosen_seconds"],
            breadth=h["breadth"],
            planner_provider=h["planner_provider"],
            planner_fallback=h["planner_fallback"],
            items=tuple(
                PlanItem(
                    item_order=r._mapping["item_order"],
                    topic_ids=tuple(r._mapping["topic_ids"]),
                    focus=r._mapping["focus"],
                    plan_item_id=r._mapping["plan_item_id"],
                    state=r._mapping["state"],
                )
                for r in rows
            ),
        )


# -- the model call ----------------------------------------------------------

SYSTEM = (
    "You are planning an interview. You group topics into questions and say what "
    "each question would test. You do not write the questions, you do not greet, "
    "and you output nothing but the requested lines."
)

#: `ITEM: <ids> | <focus>`. One line per question, and a line the model cannot
#: half-produce: an id list without a focus, or a focus without ids, fails the
#: match and the whole reply falls back rather than yielding a partial plan.
_ITEM = re.compile(r"^\s*ITEM:\s*(?P<ids>[^|]+?)\s*\|\s*(?P<focus>.*\S)\s*$")

#: Long enough for a Topic id in any of the shapes the Corpus mints. Anything
#: else on the line is not an id and is dropped before validation sees it.
_ID = re.compile(r"[A-Za-z0-9_.:-]+")

#: A focus is one line, and a model asked for one line sometimes writes a
#: paragraph. Truncating is kinder than falling back over a verbose reply.
FOCUS_LIMIT = 240


class PlanRejected(ValueError):
    """The model's reply is not a plan. Carries why, for the record."""


class SessionPlanner:
    """Ranks the scope, asks for a grouping, and refuses to trust the answer.

    The one model call here is advisory. Which Topics are in play, how many
    questions there are, and that no Topic is examined twice are all decided in
    Python before and after it — the model contributes the grouping and the one
    line of focus, and nothing else it says survives validation.
    """

    def __init__(self, *, loader, corpus, selector, plans: PlanStore) -> None:
        self._loader = loader
        self._corpus = corpus
        self._selector = selector
        self._plans = plans

    def stored(self, session_id: str) -> SessionPlan | None:
        """The plan this Session already has, if it has one.

        `build_plan` asks this before it plans, which is how fixedness survives
        a restart: the plan is in Postgres, not only in the checkpointer.
        """
        return self._plans.get(session_id)

    def next_item(self, session_id: str) -> PlanItem | None:
        """The next question this Session owes. `None` means the plan is done."""
        return self._plans.next_planned(session_id)

    def mark_asked(self, plan_item_id: str) -> None:
        self._plans.mark_asked(plan_item_id)

    def mark_unreached(self, session_id: str) -> int:
        return self._plans.mark_unreached(session_id)

    # -- the whole of it ---------------------------------------------------

    def plan(
        self,
        *,
        session_id: str,
        candidate_id: str,
        scope_module_ids: list[str],
        duration_seconds: int,
        rng,
        model=None,
        model_ref: str = "",
        provider: str | None = None,
    ) -> SessionPlan:
        """Rank, budget, group, validate, persist. In that order, once."""
        in_scope = self._corpus.topic_ids_for(list(scope_module_ids))
        if not in_scope:
            raise ValueError("a Session must be scoped to at least one Topic")

        # 1. Thompson sampling, over what *previous* Sessions established. This
        #    Session has written no Evidence yet, which is exactly the point:
        #    the ranking is a fact about the Candidate on arrival.
        ranked = self._selector.rank(
            candidate_id=candidate_id, topic_ids=in_scope, rng=rng
        )
        budget = budget_questions(duration_seconds)
        breadth = "full" if budget >= len(ranked) else "compressed"
        # No question may be about nothing, so there are never more questions
        # than Topics however long the clock is.
        wanted = min(budget, len(ranked))

        items: tuple[PlanItem, ...] | None = None
        fallback = True
        if model is not None:
            try:
                items = self._ask(
                    ranked=ranked, wanted=wanted, model=model,
                    model_ref=model_ref or session_id,
                )
                fallback = False
            except PlanRejected:
                # What the model *said*, and only that. A Provider failure is
                # not caught here and parks the Session the way every other
                # model call does — because the plan is fixed once written, and
                # a dropped connection must not lock a Candidate into a
                # fallback plan they can never replace by retrying.
                items = None

        if items is None:
            items = self.fallback_items(ranked, wanted)

        plan = SessionPlan(
            session_id=session_id,
            budget_questions=budget,
            suggested_seconds=suggested_seconds(len(in_scope)),
            chosen_seconds=duration_seconds,
            breadth=breadth,
            items=items,
            planner_provider=provider if not fallback else None,
            planner_fallback=fallback,
        )
        return self._plans.save(plan)

    # -- asking ------------------------------------------------------------

    def _ask(self, *, ranked: list[str], wanted: int, model, model_ref: str):
        reply = model.complete(
            topic_visit_id=model_ref,
            role="session_planner",
            system=SYSTEM,
            user=self.prompt(ranked, wanted),
        )
        return self.validate(self._parse(reply.text), ranked=ranked, wanted=wanted)

    def prompt(self, ranked: list[str], wanted: int) -> str:
        """The ranked Topics with their titles, the budget, and the shape.

        The ranking is given in order and said to be an order, because the model
        is grouping *this* list rather than choosing from it — the choosing has
        already happened.
        """
        lines = [f"- {tid}: {self._title(tid)}" for tid in ranked]
        return (
            f"There is time for exactly {wanted} question"
            f"{'' if wanted == 1 else 's'}.\n\n"
            f"These are the topics, most in need of examination first:\n"
            + "\n".join(lines)
            + f"\n\nGroup them into exactly {wanted} questions. Each question "
            f"covers one, two or three topics, and no topic appears in more than "
            f"one question. Group topics only where a single question could "
            f"honestly examine all of them.\n\n"
            f"Return exactly {wanted} lines and nothing else, in this form:\n"
            f"ITEM: <topic id>[, <topic id>...] | <one line saying what a single "
            f"question spanning these would test>"
        )

    def _title(self, topic_id: str) -> str:
        try:
            return self._loader.load(topic_id).topic_title
        except LookupError:
            # A Topic in scope that will not load is the Corpus's problem, not
            # the planner's. It stays in the plan under its id.
            return topic_id

    @staticmethod
    def _parse(text: str) -> list[tuple[list[str], str]]:
        out: list[tuple[list[str], str]] = []
        for line in (text or "").splitlines():
            m = _ITEM.match(line)
            if not m:
                continue
            ids = _ID.findall(m.group("ids"))
            out.append((ids, m.group("focus")[:FOCUS_LIMIT]))
        return out

    # -- refusing ----------------------------------------------------------

    @staticmethod
    def validate(
        parsed: list[tuple[list[str], str]], *, ranked: list[str], wanted: int
    ) -> tuple[PlanItem, ...]:
        """Hard, in Python, and every clause of it is a thing a model does.

        Nothing here is repaired. A reply that named four Topics in one question
        is not a plan with one long item, it is a reply that ignored the shape —
        and a planner that quietly trims it teaches nobody anything.
        """
        if len(parsed) != wanted:
            raise PlanRejected(f"expected {wanted} items, got {len(parsed)}")
        in_scope = set(ranked)
        seen: set[str] = set()
        items = []
        for order, (ids, focus) in enumerate(parsed):
            if not 1 <= len(ids) <= MAX_TOPICS_PER_QUESTION:
                raise PlanRejected(f"item {order} spans {len(ids)} topics")
            if len(set(ids)) != len(ids):
                raise PlanRejected(f"item {order} repeats a topic")
            for tid in ids:
                if tid not in in_scope:
                    raise PlanRejected(f"{tid} is not in scope")
                if tid in seen:
                    raise PlanRejected(f"{tid} appears in two items")
                seen.add(tid)
            items.append(
                PlanItem(item_order=order, topic_ids=tuple(ids), focus=focus)
            )
        return tuple(items)

    # -- falling back ------------------------------------------------------

    @staticmethod
    def fallback_items(ranked: list[str], wanted: int) -> tuple[PlanItem, ...]:
        """Contiguous chunks of the ranked list, largest chunks first.

        Deterministic and dependency-free: the same ranking always produces the
        same plan, so a Session planned by the fallback still replays. It keeps
        the ranking's order, which means the Topics most in need of examination
        are asked about first and are the ones a short clock keeps.

        A clock too short even to group — under `minimum_seconds` — leaves the
        tail of the ranking unplanned rather than packing more than three Topics
        into one question. Those Topics are unexamined, and a Session that says
        so is more honest than a question that spans nine.
        """
        wanted = max(1, min(wanted, len(ranked)))
        base, remainder = divmod(len(ranked), wanted)
        items = []
        cursor = 0
        for order in range(wanted):
            size = min(base + (1 if order < remainder else 0),
                       MAX_TOPICS_PER_QUESTION)
            group = ranked[cursor:cursor + max(1, size)]
            cursor += len(group)
            if not group:
                break
            items.append(PlanItem(
                item_order=order,
                topic_ids=tuple(group),
                focus="",
            ))
        return tuple(items)
