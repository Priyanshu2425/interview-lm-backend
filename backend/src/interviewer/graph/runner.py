"""Drives the compiled graph and exposes exactly one operation to a surface:
supply an Answer Turn, get back whatever the graph parked on next (ADR-0011).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from .machine import Deps, build_graph
from .sessions import SessionConfig, SessionStore


@dataclass(frozen=True, slots=True)
class TurnResult:
    kind: str          # question | visit_closed | session_ended
    payload: dict


class SessionRunner:
    def __init__(self, deps: Deps, checkpointer=None) -> None:
        self._d = deps
        self._cp = checkpointer or InMemorySaver()
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
        from ..metering.failures import Cause, Route, classify

        self._d.sessions.park(session_id, "provider_failure")
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
        from ..metering.client import ProviderFailure

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
        resume rather than bespoke machinery. Where the answer was submitted but
        grading did not complete, the exchange is already stored — so we grade
        it and close the Visit rather than discarding the Candidate's work.
        """
        pending_visit = self._d.visits.unresolved(session_id)
        if pending_visit and pending_visit["state"] == "answered":
            return self._grade_stored_exchange(session_id, pending_visit)

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

    def _grade_stored_exchange(self, session_id: str, visit: dict) -> TurnResult:
        """No Evidence is ever written for a Visit that was not graded — but an
        answered Visit already holds everything grading needs."""
        from ..corpus.contract import GradingMode
        from .sessions import RUBRIC_VERSION

        turns = (visit.get("exchange") or {}).get("turns", [])
        question = next(
            (t["text"] for t in turns if t.get("kind") == "question"), ""
        )
        dossier = self._d.loader.load(visit["topic_id"])
        mode = GradingMode(visit["grading_mode"])
        verdict = self._d.judge.grade(
            question=question, exchange=turns, dossier=dossier, mode=mode,
            topic_visit_id=visit["topic_visit_id"], model=self._d.ports.model,
        )
        written = self._d.evidence.write(
            topic_visit_id=visit["topic_visit_id"],
            candidate_id=visit["candidate_id"],
            topic_id=visit["topic_id"],
            session_id=session_id,
            score=verdict.score,
            mode=mode,
            grader_kind="server_judge",
            provider=(self._d.sessions.get(session_id) or {}).get("provider_chosen")
                     or self._d.provider,
            rubric_version=RUBRIC_VERSION,
            rationale=verdict.rationale,
            exchange_snapshot={"turns": turns},
        )
        self._d.sessions.resume(session_id)
        p = written.posterior
        return TurnResult("visit_closed", {
            "kind": "visit_closed",
            "topic_visit_id": visit["topic_visit_id"],
            "topic_id": visit["topic_id"],
            "score": verdict.score,
            "rationale": verdict.rationale,
            "band": p.band.value,
            "coverage": p.coverage,
            "mastery": p.mastery_or_none,
            "recovered": True,
            "already_existed": written.already_existed,
        })

    def pending(self, session_id: str) -> dict | None:
        snap = self._graph.get_state(self._cfg(session_id))
        if snap.tasks and snap.tasks[0].interrupts:
            return dict(snap.tasks[0].interrupts[0].value)
        return None

    # -- internals ---------------------------------------------------------

    def _cfg(self, sid: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": sid}}

    def _interpret(self, sid: str, out: dict) -> TurnResult:
        pend = self.pending(sid)
        if out.get("finished"):
            reason = out.get("end_reason", "duration")
            if reason.startswith("credits_exhausted"):
                # Exhaustion at the boundary is a clean park, not an error.
                # Topping up resumes this Session rather than starting a new one.
                self._d.sessions.park(sid, reason)
            else:
                self._d.sessions.end(sid, reason)
            payload = {"session_id": sid, "reason": reason}
            if "balance" in out:
                payload["balance"] = out["balance"]
            if out.get("last_result"):
                payload["last_visit"] = out["last_result"]
            return TurnResult("session_ended", payload)
        if pend:
            # A closed Visit and the next question can arrive together.
            payload = dict(pend)
            if out.get("last_result"):
                payload["last_visit"] = out["last_result"]
            # The kind is whatever the graph parked on: an opening question, or
            # a probe or hint inside the Visit already running.
            return TurnResult(payload.get("kind") or "question", payload)
        return TurnResult("visit_closed", out.get("last_result", {}))
