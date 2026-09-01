"""The Session graph (ADR-0001).

    build_plan -> next_planned_item -> load_dossiers -> generate_question
               -> answer_turn -> interviewer_move  ^(probe/hint)
               -> record_exchange -> decide_next   -> next_planned_item
                                                    | grade_session -> END

`build_plan` arrived with ISSUE-0041 and runs once, before anything else: the
Session decides what it will ask before it asks anything, and writes the plan
down. ISSUE-0042 made the rest of the loop *execute* that plan.

The two nodes that graded per Visit are gone from here, and their absence is the
point rather than an omission. In-loop grading existed because selection was
adaptive: the sampler needed a posterior updated after every Visit before it
could pick the next Topic. Fixing the plan up front removed that dependency,
and removing it is what let grading move to the end (ISSUE-0044). While a
Session is running it writes questions, answers and a transcript, and no
Evidence at all.

`grade_session` is where the Evidence arrives, and it is on the edge to END
rather than inside the loop — an edge cannot not run, so a Session that reaches
its end is graded however it got there.

What the loop still owes the record it writes as it goes: one `message` row per
turn, labelled with the `kind` the loop already knew and the `topic_ids` the
plan already fixed. Nothing asks a model what a message was about.

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

from ...service.confidence.store import ConfidenceStore, EvidenceLedger, VisitLifecycle
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

    # The question currently in flight. `topic_id` is the owning Topic and
    # stays scalar because the metering and refund paths need one; `topic_ids`
    # is what the plan item actually spans.
    topic_id: str
    topic_ids: list[str]
    plan_item_id: str
    item_focus: str
    topic_visit_id: str
    visit_index: int
    dossier_title: str
    dossier_titles: list[str]
    question: str
    grading_mode: str
    grounding_ref: dict | None

    exchange: list[dict]
    turn_count: int
    move: str
    follow_up: str

    finished: bool
    end_reason: str
    balance: int
    byok_key_id: str


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
    transcript: Any = None    # Transcript; None writes no messages
    selector: Any = None
    planner: Any = None       # SessionPlanner; without one there is no plan to run
    grader: Any = None        # SessionGrader; None grades nothing at the end
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
                # Nothing examinable in scope. `next_planned_item` ends the
                # Session for want of a plan already; planning nothing would
                # only turn a clean ending into a constraint violation.
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

    def next_planned_item(state: SessionState) -> dict:
        """Take the next planned question and open it.

        The plan is the queue, and it is read from Postgres rather than carried
        in the checkpointer: a restart resumes where the Session actually got
        to. An item is marked `asked` as it opens, so a Session picked up after
        a park does not re-ask the question it was in the middle of — the plan
        is fixed, but what happened to it is allowed to move.
        """
        if d.planner is None:
            return {"finished": True, "end_reason": "no_plan"}
        sid = state["session_id"]
        item = d.planner.next_item(sid)
        if item is None:
            return {"finished": True, "end_reason": "plan_exhausted"}

        topic_ids = list(item.topic_ids)
        idx = item.item_order + 1
        vid = d.visits.open(
            session_id=sid,
            candidate_id=state["candidate_id"],
            topic_id=topic_ids[0],
            visit_index=idx,
            topic_ids=topic_ids,
            plan_item_id=item.plan_item_id,
        )
        d.planner.mark_asked(item.plan_item_id)
        # A Provider is bound once, here, and held for this question's
        # lifetime. It may change between questions and never inside one. The
        # block moved verbatim from the node this one replaces: metering is not
        # part of ISSUE-0042 and must not drift while the loop around it does.
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
        return {
            "topic_id": topic_ids[0],
            "topic_ids": topic_ids,
            "plan_item_id": item.plan_item_id,
            "item_focus": item.focus,
            "topic_visit_id": vid,
            "visit_index": idx,
        }

    def load_dossiers(state: SessionState) -> dict:
        """Every Topic the item spans, not just the first one.

        A Topic retired since the plan was fixed — a Candidate deleted the
        notebook it came from — is dropped from the question rather than
        failing it. The plan is fixed; what is left of the material is not.
        """
        titles, alive = [], []
        for topic_id in state["topic_ids"]:
            try:
                titles.append(d.loader.load(topic_id).topic_title)
            except LookupError:
                continue
            alive.append(topic_id)
        if not alive:
            raise LookupError(
                "every Topic this question spans has been retired"
            )
        return {
            "topic_ids": alive,
            "topic_id": alive[0],
            "dossier_titles": titles,
            # One string, because the Answer Turn's payload has always carried
            # one and a surface reading `topic_title` must keep working.
            "dossier_title": " · ".join(titles),
        }

    def generate_question(state: SessionState) -> dict:
        dossiers = [d.loader.load(t) for t in state["topic_ids"]]
        written = d.writer.write(
            dossiers=dossiers,
            focus=state.get("item_focus", ""),
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
                # What the question actually spans. `topic_id` and
                # `topic_title` stay beside them: the payload keys are the
                # surface's contract and ISSUE-0042 adds to them rather than
                # replacing them.
                "topic_ids": list(state.get("topic_ids") or [state["topic_id"]]),
                "topic_titles": list(state.get("dossier_titles") or []),
                "plan_item_id": state.get("plan_item_id", ""),
                "grading_mode": state["grading_mode"],
                "turn": state.get("turn_count", 0) + 1,
            }
        )
        answer = (payload or {}).get("answer", "")
        exchange = list(state.get("exchange", []))
        exchange.append({"role": "candidate", "kind": "answer", "text": answer})
        return {"exchange": exchange, "turn_count": state.get("turn_count", 0) + 1}

    def record_exchange(state: SessionState) -> dict:
        """Write the question down — every turn of it — and close it.

        One `message` row per turn: question, probe, hint, answer. The label on
        each is the `kind` the loop already knew and the `topic_ids` the plan
        already fixed, so the transcript is grounded in what was decided rather
        than in what a model would say about it afterwards.

        `message` is append-only, and a graph node may be replayed after a
        park — so a question already written down is not written twice. There
        would be no way to tidy up if it were.
        """
        vid = state["topic_visit_id"]
        if d.transcript is not None and not d.transcript.has_question(vid):
            from .transcript import Turn

            topic_ids = tuple(state.get("topic_ids") or [state["topic_id"]])
            d.transcript.append(state["session_id"], [
                Turn(
                    role=t["role"],
                    kind=t.get("kind") or (
                        "answer" if t["role"] == "candidate" else "question"
                    ),
                    text=t.get("text") or "",
                    topic_ids=topic_ids,
                    topic_visit_id=vid,
                    plan_item_id=state.get("plan_item_id", ""),
                )
                for t in state["exchange"]
            ])
        d.visits.close_question(
            vid,
            turn_count=state["turn_count"],
            mode=GradingMode(state["grading_mode"]),
            grounding_ref=state.get("grounding_ref"),
        )
        return {}

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

        item = (d.planner.next_item(state["session_id"])
                if d.planner is not None else None)
        if item is None:
            return {"finished": True, "end_reason": "plan_exhausted"}

        # The material can be withdrawn under a running Session (ISSUE-0027):
        # a Candidate deletes the notebook their Topics came from. The plan is
        # fixed and still names them, so scope is checked here rather than
        # assumed — and a Session with nothing left to ask about ends at the
        # boundary, exactly as it did when scope exhaustion was the test.
        in_scope = set(d.corpus.topic_ids_for(state["scope_module_ids"]))
        if not in_scope & set(item.topic_ids):
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

    def grade_session(state: SessionState) -> dict:
        """The Session is over. Grade it — once, here, on the way out.

        An edge cannot not run, which is the reason this is a node on the way
        to END rather than something the runner remembers to do: a Session that
        ends because the clock ran out, because the plan was exhausted or
        because the material was withdrawn all pass through here.

        A Session parked for want of Credits does *not* get graded. It reaches
        END the same way, but it is not finished — topping up resumes it, and
        grading it here would write a Beta observation for a Candidate who is
        about to be asked more questions about the same Topics.
        """
        if str(state.get("end_reason") or "").startswith("credits_exhausted"):
            return {}
        if d.grader is not None:
            d.grader.grade(state["session_id"])
        elif d.planner is not None:
            # Without a grader there is still a plan whose unasked items are
            # unreached rather than merely unfinished. The grader does this
            # itself, so the two paths do not both do it.
            d.planner.mark_unreached(state["session_id"])
        return {}

    def _after_item(state: SessionState) -> Literal["load_dossiers", "grade_session"]:
        return "grade_session" if state.get("finished") else "load_dossiers"

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

    def _after_move(state: SessionState) -> Literal["answer_turn", "record_exchange"]:
        return "record_exchange" if state.get("move") == "close" else "answer_turn"

    def _after_decide(state: SessionState) -> Literal["next_planned_item",
                                                      "grade_session"]:
        return "grade_session" if state.get("finished") else "next_planned_item"

    g = StateGraph(SessionState)
    g.add_node("build_plan", build_plan)
    g.add_node("next_planned_item", next_planned_item)
    g.add_node("load_dossiers", load_dossiers)
    g.add_node("generate_question", generate_question)
    g.add_node("answer_turn", answer_turn)
    g.add_node("interviewer_move", interviewer_move)
    g.add_node("record_exchange", record_exchange)
    g.add_node("decide_next", decide_next)
    g.add_node("grade_session", grade_session)

    g.add_edge(START, "build_plan")
    g.add_edge("build_plan", "next_planned_item")
    g.add_conditional_edges("next_planned_item", _after_item)
    g.add_edge("load_dossiers", "generate_question")
    g.add_edge("generate_question", "answer_turn")
    g.add_edge("answer_turn", "interviewer_move")
    g.add_conditional_edges("interviewer_move", _after_move)
    # Nothing between the transcript write and the decision is a decision.
    g.add_edge("record_exchange", "decide_next")
    g.add_conditional_edges("decide_next", _after_decide)
    g.add_edge("grade_session", END)
    return g
