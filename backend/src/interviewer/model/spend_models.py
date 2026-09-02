"""What one Session cost, and the rules that are true of that.

There were two answers to this question and they disagreed. `/spend` billed the
planning call and summed every Visit; `/summary` billed neither the planning
call nor a Visit that had not reached `answered`. The same finished Session
therefore reported two different totals, and the smaller one was the one the
Candidate saw beside their result.

The arithmetic lives here so there is one of it. The I/O does not: the routes
read Credits on the async engine and the reading reads them on the graph's, so
each caller gathers the numbers and hands them over. Nothing here opens a
connection, which is what lets both callers share it.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["VisitCost", "SessionSpend"]


@dataclass(frozen=True, slots=True)
class VisitCost:
    """What one Topic Visit was charged."""

    topic_visit_id: str
    topic_id: str
    state: str
    credits: int | None


@dataclass(frozen=True, slots=True)
class SessionSpend:
    """One Session's charges, totalled once.

    `planning` is its own line and is never folded into a Visit. It is a model
    call and therefore a charge, and it belongs to no Visit — a total built
    only from Visits is smaller than what the ledger actually took
    (ISSUE-0041).
    """

    route: str
    planning: int | None
    visits: tuple[VisitCost, ...]
    balance: int | None

    @property
    def billable(self) -> bool:
        """BYOK and MCP pay their provider directly and spend no Credits."""
        return self.route == "credits"

    @property
    def credits(self) -> int | None:
        """Everything the ledger took for this Session.

        `None`, never 0, off the Credits route — a zero reads as "it was free",
        which is a different claim from "we did not bill you for this".
        """
        if not self.billable:
            return None
        return (self.planning or 0) + sum(v.credits or 0 for v in self.visits)

    @property
    def per_topic(self) -> int | None:
        """The Visit average, planning excluded.

        Planning is charged once for the Session, so dividing it across Topics
        would invent a per-Topic cost that no Topic incurred.
        """
        if not self.billable:
            return None
        if not self.visits:
            return 0
        return round(sum(v.credits or 0 for v in self.visits) / len(self.visits))
