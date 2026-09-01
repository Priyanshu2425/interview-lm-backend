"""The Session's transcript — one row per turn, in the order it happened.

Until now the record of an exchange was a JSON blob hanging off the question
that produced it (`topic_visit.exchange`). That was fine while a question was
the unit of grading; it is not fine once the Session is graded as a whole,
because a blob per question is a transcript nobody can read in order without
reassembling it.

Two properties make this the record rather than a convenience copy.

**It is append-only in the database.** `trg_message_append_only` refuses an
UPDATE or a DELETE, so a turn cannot be edited into something the Candidate
never said. Correcting a transcript means appending, and appending is visible.

**Its labels are the plan's, not a model's.** Every message carries the
`topic_ids` of the plan item that produced it and the `kind` the loop already
knew — question, probe, hint, answer. Nothing here asks a model what a message
was about, because a grader that trusted such a label would be grading the
labeller.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from ...db import schema as S
from ..confidence.store import new_id

__all__ = ["Turn", "Transcript"]


@dataclass(frozen=True, slots=True)
class Turn:
    """One thing that was said, and what it was said about."""

    role: str          # interviewer | candidate
    kind: str          # question | probe | hint | answer
    text: str
    topic_ids: tuple[str, ...] = ()
    topic_visit_id: str = ""
    plan_item_id: str = ""


class Transcript:
    """Appends turns and reads them back in order. There is no update."""

    def __init__(self, engine: Engine) -> None:
        self._e = engine

    def append(self, session_id: str, turns: list[Turn]) -> int:
        """Add these turns after whatever is already there.

        The whole question's worth of turns lands in one transaction, so a
        transcript never holds an answer whose question is missing. `seq` is
        taken under that transaction rather than counted in Python, and
        `uq_message_session_seq` is what makes that a fact rather than a hope.
        """
        if not turns:
            return 0
        with self._e.begin() as c:
            start = c.execute(
                sa.select(sa.func.coalesce(sa.func.max(S.message.c.seq), -1) + 1)
                .where(S.message.c.session_id == session_id)
            ).scalar()
            for offset, t in enumerate(turns):
                c.execute(sa.insert(S.message).values(
                    message_id=new_id("msg"),
                    session_id=session_id,
                    seq=start + offset,
                    role=t.role,
                    kind=t.kind,
                    text=t.text,
                    topic_ids=list(t.topic_ids) or None,
                    topic_visit_id=t.topic_visit_id or None,
                    plan_item_id=t.plan_item_id or None,
                ))
        return len(turns)

    def of(self, session_id: str) -> list[dict]:
        """The whole transcript, in order."""
        with self._e.connect() as c:
            rows = c.execute(
                sa.select(S.message)
                .where(S.message.c.session_id == session_id)
                .order_by(S.message.c.seq)
            ).all()
        return [dict(r._mapping) for r in rows]

    def has_question(self, topic_visit_id: str) -> bool:
        """Whether this question's turns are already written down.

        The loop appends once per question, but a graph node may be replayed
        after a park — and `message` is append-only, so a replay that wrote a
        second copy could never be tidied away.
        """
        with self._e.connect() as c:
            return bool(c.execute(
                sa.select(S.message.c.message_id)
                .where(S.message.c.topic_visit_id == topic_visit_id)
                .limit(1)
            ).scalar())
