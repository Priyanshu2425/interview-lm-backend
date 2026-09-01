"""The report a Candidate reads when the Session ends (ISSUE-0045).

No turn carries a score any more. The plan is fixed before the first question,
the transcript is what happened to it, and the whole reading arrives at once —
so this is the one place a Session's result is shown.

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

What *reached* means is not decided here. It is one definition, shared with
the summary and with the plan, and it lives in `reading.py` — the two used to
each have their own, and the same Session could be read as having examined a
Topic by one endpoint and not by the other.

The assembly lives in `SessionReadingService.report_of`. This module holds the
shape it arrives in: the refusals above are properties of these fields, and
they are easiest to keep where the fields are.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["SessionReport"]


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
