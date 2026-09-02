"""How a Session ends — one module, one order, three callers.

A Session stops in three places: the graph reaches its last node, `/end` is
posted, or the resumption path finds a Session whose process died after the
graph finished and before the grade landed. Each of them used to carry its own
copy of what ending means, and they did not carry the same copy:

* whether a reason is gradable was `reason.startswith("credits_exhausted")`,
  written in the graph and again in the runner, and missing from `/end` and
  from the resumption path;
* whether ending marks the plan's unasked items `unreached` was the grader's
  job when there was a grader and the graph's when there wasn't;
* and `/end` marked the Session ended on the routes' engine and then graded it
  on the graph's, which is two transactions and the wrong order — the grader
  read the row before the end was committed.

So the decision lives here as a value rather than a string test, and the order
lives here as a method rather than as a convention. A caller says *the Session
is over, for this reason*; what follows from that is not its business.
"""


from __future__ import annotations

from ..model.ending_models import EndReason, Ending

__all__ = ["EndReason", "Ending", "SessionEnding"]


class SessionEnding:
    """Ends a Session: marks the row, then grades it, in that order.

    Safe to call more than once and from anywhere, which is what lets the
    graph, `/end` and the resumption path all call it without coordinating —
    `SessionGrader.grade` is idempotent on `UNIQUE(session_id, topic_id)`, so
    the second call writes nothing and returns nothing.
    """

    def __init__(self, *, sessions, grader=None, plans=None) -> None:
        self._sessions = sessions
        self._grader = grader
        self._plans = plans

    def close(self, session_id: str, reason: str | None) -> Ending:
        """The Session is over. Record why, and grade it if it is gradable."""
        end = EndReason.of(reason)
        if end.parks:
            self._sessions.park(session_id, end.value)
            return Ending(session_id, "parked", end.value)
        self._sessions.end(session_id, end.value)
        return Ending(session_id, "ended", end.value, self._grade(session_id))

    def grade_finished(self, session_id: str) -> list:
        """Grade a Session whose row already says `ended`.

        The one gap a node inside the graph cannot close by itself: the graph
        reached its end and the process died before the grade landed. Grading
        is idempotent, so a Session that was graded is untouched.
        """
        return self._grade(session_id)

    def _grade(self, session_id: str) -> list:
        if self._grader is not None:
            return self._grader.grade(session_id)
        if self._plans is not None:
            # Without a grader there is still a plan whose unasked items are
            # unreached rather than merely unfinished. The grader does this
            # itself, so the two paths do not both do it.
            self._plans.mark_unreached(session_id)
        return []
