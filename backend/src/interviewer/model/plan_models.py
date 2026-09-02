"""The plan a Session fixes before it asks anything (ISSUE-0041).

The record only. `PlanStore` (which fixes it at the database) and
`SessionPlanner` (which makes it) stay in `service/graph/planner_service.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["PlanItem", "SessionPlan"]


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
