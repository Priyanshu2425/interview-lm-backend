"""Drives the compiled graph and exposes exactly one operation to a surface:
supply an Answer Turn, get back whatever the graph parked on next (ADR-0011).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ..ending import EndReason, SessionEnding
from .machine import Deps, build_graph
from .sessions import SessionConfig


@dataclass(frozen=True, slots=True)
class TurnResult:
    """What the graph parked on.

    Since ISSUE-0042 a turn carries the next question and nothing else. There
    is no score, no band and no `last_visit`, because there is no per-question
    grade to carry: the Session is graded once, at the end.
    """

    kind: str          # question | probe | hint | session_ended | session_parked
    payload: dict


class SessionRunner:
    def __init__(self, deps: Deps, checkpointer=None) -> None:
        self._d = deps
        self._cp = checkpointer or InMemorySaver()
        # The same ending the graph closes through, so the resumption path
        # cannot grade a Session on terms the graph would have refused.
        self._ending = deps.ending or SessionEnding(
            sessions=deps.sessions, grader=deps.grader, plans=deps.planner
        )
        self._graph = build_graph(deps).compile(checkpointer=self._cp)

    # -- lifecycle ---------------------------------------------------------

    def start(
        self, *, candidate_id: str, cfg: SessionConfig,
        byok_key_id: str | None = None,
    ) -> tuple[str, TurnResult]:
        self._d.sessions.ensure_candidate(candidate_id)
        sid = self._d.sessions.create(candidate_id, cfg)
        state = {
            "session_id": sid,
            "candidate_id": candidate_id,
            "scope_module_ids": list(cfg.scope_module_ids),
            "duration_seconds": cfg.duration_seconds,
            "started_at": self._d.ports.clock.now(),
            "payment_route": cfg.payment_route,
            "provider": cfg.provider or "deepseek",
            "byok_key_id": byok_key_id or "",
            "exchange": [],
        }
        try:
            out = self._graph.invoke(state, self._cfg(sid))
        except Exception as e:
            # The opening question is a model call like any other, so it fails
            # the same way — parked and recoverable, never a 500 at the surface.
            parked = self._park_on_provider_failure(sid, e)
            if parked is None:
                raise
            return sid, parked
        return sid, self._interpret(sid, out)

    def submit(self, session_id: str, answer: str) -> TurnResult:
        try:
            out = self._graph.invoke(
                Command(resume={"answer": answer}), self._cfg(session_id)
            )
        except Exception as e:
            parked = self._park_on_provider_failure(session_id, e)
            if parked is None:
                raise
            return parked
        return self._interpret(session_id, out)

    def _park_on_provider_failure(self, session_id: str, e: BaseException):
        """A Provider failure parks rather than failing over: a switch would
        split one score across two graders and corrupt the provenance record.
        The retry runs on whichever Provider is live when the next Visit opens.

        Returns None when this was not a Provider failure, so the caller raises.
        """
        failure = self._as_provider_failure(e)
        if failure is None:
            return None
        from ...service.metering.failures import Cause, Route, classify

        self._ending.close(session_id, EndReason.PROVIDER_FAILURE.value)
        row = self._d.sessions.get(session_id) or {}
        route = Route(row.get("payment_route") or self._d.payment_route)
        cause = (Cause.PROVIDER_TIMEOUT if failure.cause == "provider_timeout"
                 else Cause(failure.cause))
        event = classify(route=route, cause=cause, provider=failure.provider)
        return TurnResult("session_parked", {
            "session_id": session_id,
            "code": event.code.value,
            "message": event.message,
            "provider": failure.provider,
            "recoverable": event.recoverable,
        })

    @staticmethod
    def _as_provider_failure(e: BaseException):
        from ...service.metering.client import ProviderFailure

        seen = set()
        while e is not None and id(e) not in seen:
            seen.add(id(e))
            if isinstance(e, ProviderFailure):
                return e
            e = e.__cause__ or e.__context__
        return None

    def resume_after_interruption(self, session_id: str) -> TurnResult | None:
        """Pick a Session up from where it stopped.

        The Answer Turn is already a park, so resumption is another caller of
        resume rather than bespoke machinery.

        ISSUE-0042 removed the grade-the-stored-exchange branch that used to sit
        in front of this. There is nothing left for it to do: an answer that
        landed is already in the transcript, and grading no longer happens
        between questions, so an interrupted Session owes a grade to the end of
        itself rather than to the question it was in the middle of.
        """
        snap = self._graph.get_state(self._cfg(session_id))
        if snap.next and snap.tasks and snap.tasks[0].interrupts:
            self._d.sessions.resume(session_id)
            payload = dict(snap.tasks[0].interrupts[0].value)
            return TurnResult(payload.get("kind") or "question", payload)

        # A Session parked at a Visit boundary — credits exhausted, or a
        # provider failure — has no interrupt to resume into, because the run
        # ended cleanly rather than mid-question. Continuing it means opening
        # the next Visit, which is exactly what the loop does from the top.
        row = self._d.sessions.get(session_id)
        if row and row["state"] == "parked":
            return self._continue_from_boundary(session_id, row)
        if row and row["state"] == "ended":
            # The graph reached its end and the process died before the grade
            # landed — the one gap an in-graph node cannot close by itself.
            # Grading is idempotent, so a Session that was graded is untouched
            # and one that was not is graded now. There is still nothing to
            # resume into: the Session is over, and saying so is the answer.
            self._ending.grade_finished(session_id)
        return None

    def _continue_from_boundary(self, session_id: str, row: dict) -> TurnResult | None:
        self._d.sessions.resume(session_id)
        state = {
            "session_id": session_id,
            "candidate_id": row["candidate_id"],
            "scope_module_ids": list(row["scope_module_ids"]),
            "duration_seconds": row["duration_seconds"],
            "started_at": self._d.ports.clock.now(),
            "payment_route": row["payment_route"],
            "provider": row["provider_chosen"] or "deepseek",
            "exchange": [],
            "finished": False,
            "end_reason": "",
        }
        out = self._graph.invoke(state, self._cfg(session_id))
        return self._interpret(session_id, out)

    def pending(self, session_id: str) -> dict | None:
        snap = self._graph.get_state(self._cfg(session_id))
        if snap.tasks and snap.tasks[0].interrupts:
            return dict(snap.tasks[0].interrupts[0].value)
        return None

    # -- internals ---------------------------------------------------------

    def _cfg(self, sid: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": sid}}

    def _interpret(self, sid: str, out: dict) -> TurnResult:
        """What the graph did, said as a turn. It does not decide anything.

        The Session was already parked or ended by the `grade_session` node on
        the way out, through the one module that knows the difference. This
        used to repeat that judgement here as a second `startswith` on the end
        reason, and a Session could be ended by one copy of the rule and graded
        against the other.
        """
        pend = self.pending(sid)
        if out.get("finished"):
            reason = out.get("end_reason", "duration")
            payload = {"session_id": sid, "reason": reason}
            if "balance" in out:
                payload["balance"] = out["balance"]
            return TurnResult("session_ended", payload)
        if pend:
            # The kind is whatever the graph parked on: an opening question, or
            # a probe or hint inside the question already running.
            return TurnResult(pend.get("kind") or "question", dict(pend))
        # The graph came back neither parked nor finished. It has nowhere left
        # to go, so the Session is over however it got here.
        return TurnResult("session_ended",
                          {"session_id": sid, "reason": out.get("end_reason", "")})
