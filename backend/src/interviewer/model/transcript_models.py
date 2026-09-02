"""One thing that was said, and what it was said about.

`Transcript` — which writes these to the database — stays in
`service/graph/transcript.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Turn"]


@dataclass(frozen=True, slots=True)
class Turn:
    """One thing that was said, and what it was said about."""

    role: str          # interviewer | candidate
    kind: str          # question | probe | hint | answer
    text: str
    topic_ids: tuple[str, ...] = ()
    topic_visit_id: str = ""
    plan_item_id: str = ""
