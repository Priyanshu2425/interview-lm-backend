"""The Session graph (ADR-0001).

    build_plan -> select_topic -> load_dossier -> generate_question -> interrupt
               -> grade -> update_confidence -> decide_next

`build_plan` arrived with ISSUE-0041 and runs once, before anything else: the
Session decides what it will ask before it asks anything, and writes the plan
down. Everything after it is unchanged in this slice — running the plan is
ISSUE-0042 — but the plan exists, is fixed, and is served.

Model calls are made *inside* nodes; models do not decide which node runs next.
Everything that must happen exactly once is an edge, and a graph edge cannot not
run. Agency is confined to the region around the Answer Turn.

The deterministic skeleton is built first, on purpose: every guarantee here is a
property of the skeleton, and a hybrid grown from the start hides which half is
holding the guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ...service.confidence.math import Posterior
from ...service.confidence.store import ConfidenceStore, EvidenceLedger, VisitLifecycle
from ...service.corpus.citations import resolve
from ...model.corpus import GradingMode
from ...service.corpus.loader import DossierLoader
from ...service.corpus import CorpusService
from ...service.judge.interviewer import Interviewer
from ...service.judge.judge import Judge
from ...service.judge.question_writer import QuestionWriter
from .ports import Ports
from .sessions import RUBRIC_VERSION, SessionStore


class SessionState(TypedDict, total=False):
    session_id: str
    candidate_id: str
    scope_module_ids: list[str]
    duration_seconds: int
    started_at: float
    # What `build_plan` settled. Readings, not the plan itself: the plan is in
    # Postgres, and a copy carried in the checkpointer is a second one that can
    # disagree with it.
    plan_budget: int
    plan_breadth: str
    planner_fallback: bool
    # Chosen once, at start, and carried by the Session rather than read off
    # shared Deps — two Sessions running at once must not share a billing route.
    payment_route: str
    provider: str

    topic_id: str
    topic_visit_id: str
    visit_index: int
    dossier_title: str
    question: str
    grading_mode: str
    grounding_ref: dict | None

    exchange: list[dict]
    turn_count: int
    move: str
    follow_up: str

    score: float
    # The two readings the score combines (ISSUE-0043). Carried through the
    # state rather than recomputed at the write, so the row records what the
    # Judge actually returned.
    source_score: float | None
    truth_score: float
    rationale: str

    finished: bool
    end_reason: str
    balance: int
    byok_key_id: str
    last_result: dict


@dataclass
class Deps:
    """What the nodes are allowed to reach for. Nothing else."""

    ports: Ports
    loader: DossierLoader
    corpus: CorpusService
    sessions: SessionStore
    visits: VisitLifecycle
    evidence: EvidenceLedger
    confidence: ConfidenceStore
    judge: Judge
    writer: QuestionWriter
    selector: Any = None
    planner: Any = None       # SessionPlanner; None leaves the Session unplanned
    interviewer: Any = None   # the agentic region; None closes after one turn
    credits: Any = None       # CreditLedger; None disables the spend gate
    bindings: Any = None      # BindingStore
    metered: Any = None       # MeteredModelClient, bound per Visit
    payment_route: str = "credits"
    provider: str = "deepseek"
    max_turns_per_visit: int = 6


def build_graph(d: Deps):
    """Compile the machine. The shape is the contract."""

    def _route(state: SessionState) -> str:
        """The Session's route, falling back to the Deps default."""
        return state.get("payment_route") or d.payment_route

    def _provider(state: SessionState) -> str:
        return state.get("provider") or d.provider

    def build_plan(state: SessionState) -> dict:
        """Rank, group, write it down — once, and then never again.

        On resume this **reads** the stored plan rather than making a second
        one. That is what fixedness means across a restart: the checkpointer is
        not the record, the `session_plan` and `plan_item` rows are.

        The planner's model call is metered like every other, so it needs a
        Provider bound to something. It is bound to `plan_<session_id>`: the
        plan belongs to the Session rather than to any one question, and naming
        it after the Session keeps the call attributable without pretending a
        Topic Visit existed before the plan that schedules them.
        """
        if d.planner is None:
            return {}
        sid = state["session_id"]
        plan = d.planner.stored(sid)
        if plan is None:
            if not d.corpus.topic_ids_for(state["scope_module_ids"]):
                # Nothing examinable in scope. `select_topic` ends the Session
                # for this reason already; planning nothing would only turn a
                # clean ending into a constraint violation.
                return {}
            ref = f"plan_{sid}"
            if d.bindings is not None:
                from ...service.metering.client import Binding

                b = d.bindings.bind(
                    Binding(ref, _provider(state), _route(state),
                            state.get("byok_key_id"))
                )
                if d.metered is not None:
                    d.metered.bind(
                        b, session_id=sid, candidate_id=state["candidate_id"]
                    )
            plan = d.planner.plan(
                session_id=sid,
                candidate_id=state["candidate_id"],
                scope_module_ids=list(state["scope_module_ids"]),
                duration_seconds=state["duration_seconds"],
                rng=d.ports.rng,
                model=d.ports.model,
                model_ref=ref,
                provider=_provider(state),
            )
        return {
            "plan_budget": plan.budget_questions,
            "plan_breadth": plan.breadth,
            "planner_fallback": plan.planner_fallback,
        }

    def select_topic(state: SessionState) -> dict:
        visited = d.visits.visited_topic_ids(state["session_id"])
        in_scope = d.corpus.topic_ids_for(state["scope_module_ids"])
        remaining = [t for t in in_scope if t not in visited]
        if not remaining:
            return {"finished": True, "end_reason": "scope_exhausted"}

        if d.selector is None or not visited:
            # The opening Topic follows curriculum order — an explicit exemption
            # from selection, so a Session never opens on the hardest thing.
            topic_id = remaining[0]
        else:
            topic_id = d.selector.choose(
                candidate_id=state["candidate_id"],
                topic_ids=remaining,
                rng=d.ports.rng,
            )

        idx = len(visited) + 1
        vid = d.visits.open(
            session_id=state["session_id"],
            candidate_id=state["candidate_id"],
            topic_id=topic_id,
            visit_index=idx,
        )
        # A Provider is bound once, here, and held for this Visit's lifetime.
        # It may change between Visits and never inside one.
        if d.bindings is not None:
            from ...service.metering.client import Binding

            b = d.bindings.bind(
                Binding(vid, _provider(state), _route(state),
                        state.get("byok_key_id"))
            )
            if d.metered is not None:
                d.metered.bind(
                    b,
                    session_id=state["session_id"],
                    candidate_id=state["candidate_id"],
                )
        return {"topic_id": topic_id, "topic_visit_id": vid, "visit_index": idx}

    def load_dossier(state: SessionState) -> dict:
        dossier = d.loader.load(state["topic_id"])
        return {"dossier_title": dossier.topic_title}

    def generate_question(state: SessionState) -> dict:
        dossier = d.loader.load(state["topic_id"])
        written = d.writer.write(
            dossier=dossier,
            topic_visit_id=state["topic_visit_id"],
            model=d.ports.model,
        )
        return {
            "question": written.question,
            "grading_mode": written.mode.value,
            "grounding_ref": written.grounding_ref,
            "exchange": [{"role": "interviewer", "kind": "question",
                          "text": written.question}],
            "turn_count": 0,
            "move": "question",
            "follow_up": "",
        }

    def answer_turn(state: SessionState) -> dict:
        """The Answer Turn. The graph parks here and a surface resumes it.

        It waits for an *event*, never a read from a kind of input — which is
        why voice or a code editor changes who calls resume rather than changing
        the loop.
        """
        follow_up = state.get("follow_up")
        payload = interrupt(
            {
                "kind": state.get("move") or "question",
                "question": follow_up or state["question"],
                "opening_question": state["question"],
                "topic_visit_id": state["topic_visit_id"],
                "topic_id": state["topic_id"],
                "topic_title": state.get("dossier_title", ""),
                "grading_mode": state["grading_mode"],
                "turn": state.get("turn_count", 0) + 1,
            }
        )
        answer = (payload or {}).get("answer", "")
        exchange = list(state.get("exchange", []))
        exchange.append({"role": "candidate", "kind": "answer", "text": answer})
        return {"exchange": exchange, "turn_count": state.get("turn_count", 0) + 1}

    def record_answer(state: SessionState) -> dict:
        """Store the exchange before grading, so an interruption here is
        recoverable rather than lost."""
        d.visits.record_answer(
            state["topic_visit_id"],
            exchange={"turns": state["exchange"]},
            turn_count=state["turn_count"],
            mode=GradingMode(state["grading_mode"]),
            grounding_ref=state.get("grounding_ref"),
        )
        return {}

    def grade(state: SessionState) -> dict:
        dossier = d.loader.load(state["topic_id"])
        verdict = d.judge.grade(
            question=state["question"],
            exchange=state["exchange"],
            dossier=dossier,
            mode=GradingMode(state["grading_mode"]),
            topic_visit_id=state["topic_visit_id"],
            model=d.ports.model,
        )
        return {
            "score": verdict.score,
            "source_score": verdict.source_score,
            "truth_score": verdict.truth_score,
            "rationale": verdict.rationale,
        }

    def update_confidence(state: SessionState) -> dict:
        """The Evidence write. An edge, not a tool call — it cannot not run."""
        dossier = d.loader.load(state["topic_id"])
        citations = resolve(dossier, state.get("grounding_ref"))
        written = d.evidence.write(
            topic_visit_id=state["topic_visit_id"],
            candidate_id=state["candidate_id"],
            topic_id=state["topic_id"],
            session_id=state["session_id"],
            score=state["score"],
            source_score=state.get("source_score"),
            truth_score=state.get("truth_score"),
            mode=GradingMode(state["grading_mode"]),
            grader_kind="server_judge",
            provider=_provider(state),
            rubric_version=RUBRIC_VERSION,
            rationale=state["rationale"],
            exchange_snapshot={"turns": state["exchange"]},
            citations=citations,
            topic_title=dossier.topic_title,
            module_title=dossier.module_title,
        )
        p: Posterior = written.posterior
        return {
            "last_result": {
                "kind": "visit_closed",
                "topic_visit_id": state["topic_visit_id"],
                "topic_id": state["topic_id"],
                "topic_title": state.get("dossier_title", ""),
                "score": state["score"],
                # Reported beside each other and never fused into a headline
                # figure. `score` is what the posterior consumed, not a third
                # reading standing over these two.
                "source_score": state.get("source_score"),
                "truth_score": state.get("truth_score"),
                "rationale": state["rationale"],
                "grading_mode": state["grading_mode"],
                "weight": GradingMode(state["grading_mode"]).weight,
                "band": p.band.value,
                "band_label": p.band.label,
                "coverage": p.coverage,
                "mastery": p.mastery_or_none,
                "alpha": p.alpha,
                "beta": p.beta,
                "grader": "server_judge",
                "provider": _provider(state),
                "rubric_version": RUBRIC_VERSION,
                "citations": citations,
            }
        }

    def decide_next(state: SessionState) -> dict:
        """The only place a Session may legally end, and the only place a spend
        check runs.

        The deadline is soft: the Session ends *after* the Visit that just
        closed, never inside one. And the balance is checked here rather than
        inside a Visit, because a Visit cut off mid-exchange corrupts a
        permanent write while an overrun costs a few Credits.
        """
        elapsed = d.ports.clock.now() - state["started_at"]
        if elapsed >= state["duration_seconds"]:
            return {"finished": True, "end_reason": "duration"}

        visited = d.visits.visited_topic_ids(state["session_id"])
        in_scope = d.corpus.topic_ids_for(state["scope_module_ids"])
        if not [t for t in in_scope if t not in visited]:
            return {"finished": True, "end_reason": "scope_exhausted"}

        # Credits meter our key only. Under BYOK the Candidate pays their
        # provider directly and spends none, so there is nothing to gate on.
        if d.credits is not None and _route(state) == "credits":
            from ...service.metering.credits import clears_headroom

            balance = d.credits.balance(state["candidate_id"])
            if not clears_headroom(balance):
                overran = balance < 0
                return {
                    "finished": True,
                    "end_reason": "credits_exhausted_mid_visit" if overran
                                  else "credits_exhausted",
                    "balance": balance,
                }
        return {"finished": False}

    def _after_select(state: SessionState) -> Literal["load_dossier", "__end__"]:
        return "__end__" if state.get("finished") else "load_dossier"

    def interviewer_move(state: SessionState) -> dict:
        """The agentic region: probe, hint, or close.

        This is the only node whose output changes what happens next, and the
        seam between it and the deterministic skeleton is deliberately visible.
        """
        if d.interviewer is None:
            return {"move": "close", "exchange": state["exchange"]}

        dossier = d.loader.load(state["topic_id"])
        move = d.interviewer.next_move(
            question=state["question"],
            exchange=state["exchange"],
            dossier=dossier,
            turn_count=state.get("turn_count", 0),
            topic_visit_id=state["topic_visit_id"],
            model=d.ports.model,
        )
        if move.action == "close":
            return {"move": "close"}
        exchange = list(state["exchange"])
        exchange.append(
            {"role": "interviewer", "kind": move.action, "text": move.text}
        )
        return {"move": move.action, "exchange": exchange, "follow_up": move.text}

    def _after_move(state: SessionState) -> Literal["answer_turn", "record_answer"]:
        return "record_answer" if state.get("move") == "close" else "answer_turn"

    def _after_decide(state: SessionState) -> Literal["select_topic", "__end__"]:
        return "__end__" if state.get("finished") else "select_topic"

    g = StateGraph(SessionState)
    g.add_node("build_plan", build_plan)
    g.add_node("select_topic", select_topic)
    g.add_node("load_dossier", load_dossier)
    g.add_node("generate_question", generate_question)
    g.add_node("answer_turn", answer_turn)
    g.add_node("interviewer_move", interviewer_move)
    g.add_node("record_answer", record_answer)
    g.add_node("grade", grade)
    g.add_node("update_confidence", update_confidence)
    g.add_node("decide_next", decide_next)

    g.add_edge(START, "build_plan")
    g.add_edge("build_plan", "select_topic")
    g.add_conditional_edges("select_topic", _after_select)
    g.add_edge("load_dossier", "generate_question")
    g.add_edge("generate_question", "answer_turn")
    g.add_edge("answer_turn", "interviewer_move")
    g.add_conditional_edges("interviewer_move", _after_move)
    # Nothing between record_answer and update_confidence is a decision.
    g.add_edge("record_answer", "grade")
    g.add_edge("grade", "update_confidence")
    g.add_edge("update_confidence", "decide_next")
    g.add_conditional_edges("decide_next", _after_decide)
    return g
