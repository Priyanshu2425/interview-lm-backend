"""Why a Session stopped, and therefore what happens next.

The concept and the rule that is true of it. `SessionEnding` — the order in
which a Session is closed, and the stores it touches to do it — stays in
`service/ending_service.py`, because it needs collaborators and this does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = ["EndReason", "Ending"]

class EndReason(str, Enum):
    """Why a Session stopped, and therefore what happens next.

    A Session out of Credits is *parked*, not ended: topping up resumes it, and
    grading it would write a Beta observation for a Candidate who is about to
    be asked more questions about the same Topics. Everything else is over, and
    a Session that is over is graded.
    """

    DURATION = "duration"
    PLAN_EXHAUSTED = "plan_exhausted"
    SCOPE_EXHAUSTED = "scope_exhausted"
    CANDIDATE_ENDED = "candidate_ended"
    CREDITS_EXHAUSTED = "credits_exhausted"
    CREDITS_EXHAUSTED_MID_VISIT = "credits_exhausted_mid_visit"
    PROVIDER_FAILURE = "provider_failure"

    @classmethod
    def of(cls, reason: str | None) -> "EndReason":
        """An unrecognised reason ends the Session and grades it.

        Deliberately not an error: a reason nobody thought to name is still a
        Session that stopped, and refusing to grade one would silently lose the
        Evidence it had already earned. The parking reasons are the closed set,
        and they are the ones spelled out above.
        """
        try:
            return cls(str(reason or "").strip() or cls.DURATION.value)
        except ValueError:
            return cls.DURATION

    @property
    def parks(self) -> bool:
        """Parked rather than ended: the Session can be picked back up."""
        return self in (
            EndReason.CREDITS_EXHAUSTED,
            EndReason.CREDITS_EXHAUSTED_MID_VISIT,
            EndReason.PROVIDER_FAILURE,
        )

    @property
    def gradable(self) -> bool:
        """A Session is graded exactly when it is over. Parking is not over."""
        return not self.parks


@dataclass(frozen=True, slots=True)
class Ending:
    """What became of the Session. `state` is what the row now says."""

    session_id: str
    state: str                     # ended | parked
    reason: str
    graded: list = field(default_factory=list)

    @property
    def parked(self) -> bool:
        return self.state == "parked"

