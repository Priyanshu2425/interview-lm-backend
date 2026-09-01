"""MCP Mode — the tool surface, and the two invariants that survive it.

The host is a ReAct agent we do not control. Prompts steer it; they do not
constrain it. So every invariant that matters is enforced here, never asked for
in a prompt:

1. **Evidence is written once per Topic Visit** — the write is idempotent on a
   server-issued topic_visit_id, and the Session will not advance while a Visit
   is unresolved.
2. **No Answer Key enters the interviewing context.** The host holds its context
   in front of the Candidate, so an Answer Key reaching the host is leaked by
   construction and no prompt can unsee it. Grading material is redeemed
   directly by the Judge Subagent against a Visit id, and never passes through
   the host.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from ...service.confidence.store import EvidenceLedger, VisitLifecycle
from ...model.corpus import GradingMode
from ...service.corpus.loader import DossierLoader
from ...service.corpus import CorpusService
from ...service.graph.sessions import RUBRIC_VERSION, SessionConfig, SessionStore

REDEMPTION_TTL_TURNS = 1     # single-use


class ScopeViolation(PermissionError):
    """The host asked for a Topic outside the Session's chosen Modules."""


class VisitUnresolved(RuntimeError):
    """The Session will not advance while a Visit is open."""


class RedemptionRefused(PermissionError):
    """A grading ticket that was already used, or never issued."""


@dataclass
class _Ticket:
    topic_visit_id: str
    uses_left: int


@dataclass
class McpServer:
    """Plain methods. The MCP protocol binding over these is deliberately thin —
    every guarantee lives at this layer, not in the transport."""

    loader: DossierLoader
    corpus: CorpusService
    sessions: SessionStore
    visits: VisitLifecycle
    evidence: EvidenceLedger
    reading: object | None = None   # SessionReadingService; None returns no summary
    _tickets: dict[str, _Ticket] = field(default_factory=dict)

    # -- tools the host may call ------------------------------------------

    def start_session(
        self, *, candidate_id: str, module_ids: list[str], duration_seconds: int
    ) -> dict:
        self.sessions.ensure_candidate(candidate_id)
        sid = self.sessions.create(
            candidate_id,
            SessionConfig(
                scope_module_ids=tuple(module_ids),
                duration_seconds=duration_seconds,
                provider=None,
                payment_route="mcp",
                mode="mcp",
            ),
        )
        return {"session_id": sid, "topics_in_scope": len(
            self.corpus.topic_ids_for(module_ids))}

    def next_topic(self, *, session_id: str) -> dict:
        """Opens a Topic Visit and hands back a dossier with **no grading
        material in it**."""
        row = self._session(session_id)
        if self.visits.unresolved(session_id):
            raise VisitUnresolved(
                "the current Topic Visit must be graded before another opens"
            )

        visited = self.visits.visited_topic_ids(session_id)
        in_scope = self.corpus.topic_ids_for(list(row["scope_module_ids"]))
        remaining = [t for t in in_scope if t not in visited]
        if not remaining:
            return {"done": True, "reason": "scope_exhausted"}

        topic_id = remaining[0]
        vid = self.visits.open(
            session_id=session_id, candidate_id=row["candidate_id"],
            topic_id=topic_id, visit_index=len(visited) + 1,
        )
        d = self.loader.load(topic_id)
        return {
            "topic_visit_id": vid,
            "topic_id": topic_id,
            "topic_title": d.topic_title,
            "module_title": d.module_title,
            # Withheld: the host's context sits in front of the Candidate.
            "material": d.text_for_prompt(include_ground_truth=False),
            "grading_mode_ceiling": d.grading_mode_ceiling.value,
            "syllabus": list(d.syllabus),
        }

    def load_topic(self, *, session_id: str, topic_id: str) -> dict:
        """Scope enforcement is the server's job, not something the host is
        trusted with."""
        row = self._session(session_id)
        if topic_id not in self.corpus.topic_ids_for(list(row["scope_module_ids"])):
            raise ScopeViolation(f"{topic_id} is outside this Session's scope")
        d = self.loader.load(topic_id)
        return {
            "topic_id": topic_id,
            "topic_title": d.topic_title,
            "material": d.text_for_prompt(include_ground_truth=False),
        }

    def submit_answer(
        self, *, topic_visit_id: str, question: str, answer: str,
        grading_mode: str, turn_count: int = 1,
    ) -> dict:
        """Records the exchange and issues a grading ticket.

        The ticket is what the Judge Subagent redeems. The host receives only
        the ticket, never the material behind it.
        """
        visit = self.visits.get(topic_visit_id)
        if not visit:
            raise RedemptionRefused("unknown topic_visit_id")
        mode = GradingMode(grading_mode)
        d = self.loader.load(visit["topic_id"])
        if mode is GradingMode.GROUND_TRUTH and not d.ground_truth_pairs:
            mode = (GradingMode.TEXT_GROUNDED if d.content
                    else GradingMode.MODEL_JUDGMENT)

        self.visits.record_answer(
            topic_visit_id,
            exchange={"turns": [
                {"role": "interviewer", "kind": "question", "text": question},
                {"role": "candidate", "kind": "answer", "text": answer},
            ]},
            turn_count=turn_count,
            mode=mode,
        )
        ticket = f"tkt_{secrets.token_urlsafe(18)}"
        self._tickets[ticket] = _Ticket(topic_visit_id, REDEMPTION_TTL_TURNS)
        return {
            "topic_visit_id": topic_visit_id,
            "grading_ticket": ticket,
            "grading_mode": mode.value,
            "instructions": (
                "Dispatch a subagent to grade this. The subagent calls "
                "redeem_grading_material with the ticket. Do not call it here."
            ),
        }

    # -- the Judge Subagent's own call, not the host's ---------------------

    def redeem_grading_material(self, *, grading_ticket: str) -> dict:
        """Single-use. A leaked ticket therefore has a bounded blast radius."""
        t = self._tickets.get(grading_ticket)
        if not t or t.uses_left <= 0:
            raise RedemptionRefused("this grading ticket is spent or unknown")
        t.uses_left -= 1

        visit = self.visits.get(t.topic_visit_id)
        d = self.loader.load(visit["topic_id"])
        mode = GradingMode(visit["grading_mode"])
        turns = (visit["exchange"] or {}).get("turns", [])

        material = ""
        if mode is GradingMode.GROUND_TRUTH and d.ground_truth_pairs:
            material = d.ground_truth_pairs[0][1].text or ""
        elif mode is GradingMode.TEXT_GROUNDED:
            material = d.text_for_prompt(include_ground_truth=False)

        return {
            "topic_visit_id": t.topic_visit_id,
            "question": next((x["text"] for x in turns
                              if x.get("kind") == "question"), ""),
            "answer": next((x["text"] for x in turns
                            if x.get("role") == "candidate"), ""),
            "grounding": material,
            "grading_mode": mode.value,
            "rubric_version": RUBRIC_VERSION,
        }

    def record_score(
        self, *, topic_visit_id: str, score: float, rationale: str,
    ) -> dict:
        """Idempotent on the Visit id — the invariant that survives a host we do
        not control."""
        visit = self.visits.get(topic_visit_id)
        if not visit:
            raise RedemptionRefused("unknown topic_visit_id")
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be in 0..1")

        written = self.evidence.write(
            topic_visit_id=topic_visit_id,
            candidate_id=visit["candidate_id"],
            topic_id=visit["topic_id"],
            session_id=visit["session_id"],
            score=score,
            mode=GradingMode(visit["grading_mode"]),
            grader_kind="judge_subagent",
            provider=None,                 # the host's own subscription paid
            rubric_version=RUBRIC_VERSION,
            rationale=rationale,
            exchange_snapshot=visit["exchange"],
        )
        p = written.posterior
        return {
            "recorded": not written.already_existed,
            "band": p.band.value,
            "coverage": p.coverage,
            "mastery": p.mastery_or_none,
        }

    def end_session(self, *, session_id: str) -> dict:
        """Ends the Session and returns the same readings Managed Mode gives.

        Soft, like every other end: an unresolved Visit finishes first.
        """
        row = self._session(session_id)
        open_visit = self.visits.unresolved(session_id)
        if open_visit:
            return {
                "ended": False,
                "note": "this Topic Visit must be graded before the Session ends",
                "topic_visit_id": open_visit["topic_visit_id"],
            }
        self.sessions.end(session_id, "candidate_ended")
        if self.reading is not None:
            from dataclasses import asdict

            summary = self.reading.summary_of(self.reading.of_row(row))
            return {"ended": True, "summary": asdict(summary)}
        return {"ended": True}

    def record_grading_unreachable(
        self, *, topic_visit_id: str, detail: str = ""
    ) -> dict:
        """A subagent that could not reach the server is a fact worth recording.

        No Evidence is written — the Visit simply stays unresolved, which is what
        stops the Session advancing and what resumption later picks up.
        """
        visit = self.visits.get(topic_visit_id)
        if not visit:
            raise RedemptionRefused("unknown topic_visit_id")
        self.sessions.park(visit["session_id"], "grading_unreachable")
        return {
            "recorded": True,
            "session_state": "parked",
            "topic_visit_state": visit["state"],
            "detail": detail,
            "note": "no Evidence was written; resume to grade the stored exchange",
        }

    def _session(self, session_id: str) -> dict:
        row = self.sessions.get(session_id)
        if not row:
            raise RedemptionRefused("unknown session")
        return row


HOST_TOOLS = frozenset({
    "start_session", "next_topic", "load_topic", "submit_answer", "record_score",
    "end_session", "record_grading_unreachable",
})
SUBAGENT_TOOLS = frozenset({"redeem_grading_material"})

# Prompts steer the host; they do not constrain it. These descriptions state the
# intended loop so steering is available, while every invariant that matters is
# enforced by the methods above.
TOOL_DESCRIPTIONS = {
    "start_session": (
        "Start a mock interview. Give the Candidate's chosen Modules and a "
        "duration. Returns a session_id and how many Topics are in scope."
    ),
    "next_topic": (
        "Open the next Topic Visit. Returns interviewing material with no "
        "grading material in it, and a server-issued topic_visit_id. Refuses "
        "while a previous Visit is still unresolved."
    ),
    "load_topic": (
        "Re-read the material for a Topic already in scope. Refuses any Topic "
        "outside the Session's chosen Modules."
    ),
    "submit_answer": (
        "Record the Candidate's answer for a Topic Visit. Returns a "
        "single-use grading_ticket. Do NOT redeem it yourself — dispatch a "
        "subagent, which calls redeem_grading_material with the ticket. The "
        "grading material must never enter this conversation."
    ),
    "record_score": (
        "Write the subagent's score against the topic_visit_id. Idempotent: a "
        "second score for the same Visit is a no-op."
    ),
    "end_session": (
        "End the Session and return its summary. An unresolved Visit must be "
        "graded first."
    ),
    "record_grading_unreachable": (
        "Report that the grading subagent could not reach the server. Parks the "
        "Session; nothing is lost and it can be resumed."
    ),
    "redeem_grading_material": (
        "SUBAGENT ONLY. Exchange a grading_ticket for the question, the answer "
        "and the grounding for exactly that one Visit. Single-use."
    ),
}
