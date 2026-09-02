"""The Topic Visit Lifecycle — one Visit, one Evidence row.

Tables we own (ADR-0003), read and written by graph nodes but owned by neither
the graph nor a framework abstraction. Reading Topic Confidence must not require
instantiating a graph, so nothing here imports one.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from ...db import schema as S
from ...model.corpus_models import GradingMode
from ...util.ids_utils import new_id

__all__ = ["VisitLifecycle"]


class VisitLifecycle:
    """Opens a Visit, holds it open until graded, closes it on the Evidence write.

    The single place where "one Visit, one Evidence row" is enforced — and the
    partial unique index on (session_id) WHERE state IN ('open','answered') is
    what stops a Session advancing while a Visit is unresolved.
    """

    def __init__(self, engine: Engine) -> None:
        self._e = engine

    def open(
        self, *, session_id: str, candidate_id: str, topic_id: str, visit_index: int,
        topic_ids: tuple[str, ...] | list[str] | None = None,
        plan_item_id: str | None = None,
    ) -> str:
        """Open one question.

        `topic_id` is the owning Topic and stays scalar — `open_topic_ids()` and
        the refund path both need one. `topic_ids` is what the question actually
        spans, which since ISSUE-0042 is whatever the plan item said, and
        `plan_item_id` is the item that scheduled it.
        """
        vid = new_id("visit")
        with self._e.begin() as c:
            c.execute(
                sa.insert(S.topic_visit).values(
                    topic_visit_id=vid,
                    session_id=session_id,
                    candidate_id=candidate_id,
                    topic_id=topic_id,
                    visit_index=visit_index,
                    state="open",
                    topic_ids=list(topic_ids) if topic_ids else [topic_id],
                    plan_item_id=plan_item_id,
                )
            )
        return vid

    def record_answer(
        self, topic_visit_id: str, *, exchange: dict, turn_count: int,
        mode: GradingMode, grounding_ref: dict | None = None,
    ) -> None:
        """Store the exchange at the Answer Turn, before grading.

        This is what makes resumption work: an interrupted Session whose answer
        was submitted but not graded already has the exchange, so resumption
        grades it rather than discarding the Candidate's work.
        """
        with self._e.begin() as c:
            c.execute(
                sa.update(S.topic_visit)
                .where(S.topic_visit.c.topic_visit_id == topic_visit_id)
                .values(
                    state="answered",
                    exchange=exchange,
                    turn_count=turn_count,
                    grading_mode=mode.value,
                    grounding_ref=grounding_ref,
                    answered_at=sa.func.now(),
                )
            )

    def close_question(
        self, topic_visit_id: str, *, turn_count: int,
        mode: GradingMode, grounding_ref: dict | None = None,
    ) -> None:
        """The question is finished. Nothing about it is graded (ISSUE-0042).

        `record_answer` above still exists and still writes the `exchange`
        blob, because MCP Mode grades per Visit against exactly that blob. The
        managed loop no longer does: its record is `message`, and writing a
        second copy here would leave two transcripts that can disagree.

        The state it lands in is `answered`, and that is now a terminal state
        for the loop rather than a queue for the grader — the Session moves on
        immediately, and the grade arrives once, at the end.
        """
        with self._e.begin() as c:
            c.execute(
                sa.update(S.topic_visit)
                .where(S.topic_visit.c.topic_visit_id == topic_visit_id)
                .values(
                    state="answered",
                    turn_count=turn_count,
                    grading_mode=mode.value,
                    grounding_ref=grounding_ref,
                    answered_at=sa.func.now(),
                )
            )

    def mark_graded(self, session_id: str) -> int:
        """Every answered Visit in a Session that has now been graded.

        ISSUE-0042 left `answered` terminal for the managed loop, because
        nothing graded a question any more. ISSUE-0044 grades the Session, and
        a question inside a graded Session owes nothing further — so it lands
        where a graded Visit always landed, and the material it examined can be
        withdrawn again (`open_topic_ids` reads open and answered).

        Session-wide rather than per Evidence row on purpose: a spanning
        question belongs to three Topics and is finished when all of them are.
        """
        with self._e.begin() as c:
            return c.execute(
                sa.update(S.topic_visit)
                .where(S.topic_visit.c.session_id == session_id,
                       S.topic_visit.c.state == "answered")
                .values(state="graded", graded_at=sa.func.now())
            ).rowcount

    def get(self, topic_visit_id: str) -> dict | None:
        with self._e.connect() as c:
            r = c.execute(
                sa.select(S.topic_visit).where(
                    S.topic_visit.c.topic_visit_id == topic_visit_id
                )
            ).first()
        return dict(r._mapping) if r else None

    def unresolved(self, session_id: str) -> dict | None:
        """Open or answered — MCP Mode's reading, where a grade is still owed.

        The managed loop asks `being_asked` instead: since ISSUE-0042 an
        answered question owes nothing until the Session ends.
        """
        with self._e.connect() as c:
            r = c.execute(
                sa.select(S.topic_visit).where(
                    S.topic_visit.c.session_id == session_id,
                    S.topic_visit.c.state.in_(("open", "answered")),
                )
            ).first()
        return dict(r._mapping) if r else None

    def being_asked(self, session_id: str) -> dict | None:
        """The question this Session is in the middle of, if it is in one."""
        with self._e.connect() as c:
            r = c.execute(
                sa.select(S.topic_visit).where(
                    S.topic_visit.c.session_id == session_id,
                    S.topic_visit.c.state == "open",
                )
            ).first()
        return dict(r._mapping) if r else None

    def open_topic_ids(self) -> set[str]:
        """Topics with a Visit still in flight, anywhere.

        A Visit that has opened must be able to finish: it either produces
        Evidence or it corrupts the record it exists to build. So material it is
        being examined on cannot be withdrawn while it runs (ISSUE-0027).
        """
        with self._e.connect() as c:
            return {
                r[0] for r in c.execute(
                    sa.select(S.topic_visit.c.topic_id).where(
                        S.topic_visit.c.state.in_(("open", "answered"))
                    )
                )
            }

    def visited_topic_ids(self, session_id: str) -> set[str]:
        with self._e.connect() as c:
            return {
                r[0]
                for r in c.execute(
                    sa.select(S.topic_visit.c.topic_id).where(
                        S.topic_visit.c.session_id == session_id
                    )
                ).all()
            }

    def for_session(self, session_id: str) -> list[dict]:
        with self._e.connect() as c:
            return [
                dict(r._mapping)
                for r in c.execute(
                    sa.select(S.topic_visit)
                    .where(S.topic_visit.c.session_id == session_id)
                    .order_by(S.topic_visit.c.visit_index)
                ).all()
            ]

    def abandon(self, topic_visit_id: str) -> None:
        with self._e.begin() as c:
            c.execute(
                sa.update(S.topic_visit)
                .where(
                    S.topic_visit.c.topic_visit_id == topic_visit_id,
                    S.topic_visit.c.state.in_(("open", "answered")),
                )
                .values(state="abandoned")
            )
