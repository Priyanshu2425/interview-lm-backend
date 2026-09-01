"""ISSUE-0041 — the plan is made before the first question, and it is fixed.

The shape of a Session used to be an emergent property of a sampler consulted
after every Visit. Here it is decided once, written down, and served. Thompson
sampling still decides it; it just decides it earlier.

These tests are about the *plan*: how it is ranked, how it is validated, what
happens when the model will not cooperate, and that reading it twice gives the
same answer. Whether the loop executes it is ISSUE-0042.
"""

import uuid

import numpy as np
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from conftest import signed_in_client

from interviewer.db import schema as S
from interviewer.service.confidence.selector import TopicSelector
from interviewer.service.confidence.store import ConfidenceStore
from interviewer.service.graph.pacing import SECONDS_PER_QUESTION
from interviewer.service.graph.planner import (
    PlanRejected,
    PlanStore,
    SessionPlanner,
)
from interviewer.service.graph.ports import ModelReply
from interviewer.service.graph.runner import SessionRunner
from interviewer.service.graph.sessions import SessionConfig

CANDIDATE = "cand_plan"


# --- stand-ins --------------------------------------------------------------
#
# The planner needs a scope to rank and titles to show. Neither is what these
# tests are about, and the shipped Corpus has no Module with exactly twelve
# Topics — so the arithmetic is exercised against a scope of a stated size
# rather than against whichever size the material happens to have.


class _Scope:
    def __init__(self, topic_ids):
        self._ids = list(topic_ids)

    def topic_ids_for(self, module_ids):
        return list(self._ids)


class _Titles:
    def load(self, topic_id):
        return type("D", (), {"topic_title": f"Title of {topic_id}"})()


class _Replies:
    """A model that says one thing, and counts how often it was asked."""

    def __init__(self, text):
        self.text = text
        self.calls = []

    def complete(self, *, topic_visit_id, role, system, user, max_tokens=800):
        if not topic_visit_id:
            raise ValueError("a model call must carry a topic_visit_id")
        self.calls.append({"topic_visit_id": topic_visit_id, "role": role,
                           "user": user})
        return ModelReply(text=self.text, call_id="call_1", provider="deepseek")


def _topics(n: int) -> list[str]:
    return [f"t{i:02d}" for i in range(n)]


@pytest.fixture()
def a_session(clean_db):
    """A Candidate and a Session for the plan to hang off."""
    cand = f"cand_{uuid.uuid4().hex[:8]}"
    sess = f"sess_{uuid.uuid4().hex[:8]}"
    with clean_db.begin() as c:
        c.execute(sa.insert(S.candidate).values(candidate_id=cand))
        c.execute(sa.insert(S.session).values(
            session_id=sess, candidate_id=cand, mode="managed",
            payment_route="credits", scope_module_ids=["mod-1"],
            duration_seconds=900, rubric_version="v2",
        ))
    return clean_db, cand, sess


def _planner(engine, topic_ids):
    return SessionPlanner(
        loader=_Titles(),
        corpus=_Scope(topic_ids),
        selector=TopicSelector(ConfidenceStore(engine)),
        plans=PlanStore(engine),
    )


# --- the sampler learned to rank -------------------------------------------


def test_rank_returns_every_topic_in_scope_and_orders_it(deps):
    sel = TopicSelector(deps.confidence)
    ids = _topics(9)
    ranked = sel.rank(candidate_id=CANDIDATE, topic_ids=ids,
                      rng=np.random.default_rng(5))
    assert sorted(ranked) == sorted(ids)
    assert len(ranked) == len(ids)


def test_choose_is_the_head_of_the_ranking(deps):
    """One sampler, not two that drift."""
    sel = TopicSelector(deps.confidence)
    ids = _topics(9)
    ranked = sel.rank(candidate_id=CANDIDATE, topic_ids=ids,
                      rng=np.random.default_rng(7))
    chosen = sel.choose(candidate_id=CANDIDATE, topic_ids=ids,
                        rng=np.random.default_rng(7))
    assert chosen == ranked[0]


def test_the_weakest_looking_topic_is_ranked_before_the_strongest(deps, clean_db):
    with clean_db.begin() as c:
        c.execute(sa.insert(S.topic_confidence).values(
            candidate_id=CANDIDATE, topic_id="strong", alpha=40.0, beta=2.0))
        c.execute(sa.insert(S.topic_confidence).values(
            candidate_id=CANDIDATE, topic_id="weak", alpha=2.0, beta=40.0))
    sel = TopicSelector(deps.confidence)
    firsts = [
        sel.rank(candidate_id=CANDIDATE, topic_ids=["strong", "weak"],
                 rng=np.random.default_rng(s))[0]
        for s in range(30)
    ]
    assert firsts.count("weak") == 30


def test_an_empty_scope_cannot_be_ranked(deps):
    with pytest.raises(ValueError, match="nothing in scope"):
        TopicSelector(deps.confidence).rank(
            candidate_id=CANDIDATE, topic_ids=[], rng=np.random.default_rng(1))


# --- the budget the plan is cut to -----------------------------------------


def test_a_fifteen_minute_session_over_twelve_topics_plans_five_questions(a_session):
    engine, cand, sess = a_session
    ids = _topics(12)
    plan = _planner(engine, ids).plan(
        session_id=sess, candidate_id=cand, scope_module_ids=["mod-1"],
        duration_seconds=15 * 60, rng=np.random.default_rng(3),
    )
    assert plan.budget_questions == 5
    assert len(plan.items) == 5
    assert plan.breadth == "compressed"
    # Twelve Topics into five questions cannot be one Topic each.
    assert any(len(i.topic_ids) > 1 for i in plan.items)
    assert all(1 <= len(i.topic_ids) <= 3 for i in plan.items)
    # Nothing is dropped and nothing is examined twice.
    planned = [t for i in plan.items for t in i.topic_ids]
    assert sorted(planned) == sorted(ids)


def test_a_clock_that_affords_a_question_per_topic_plans_full_breadth(a_session):
    engine, cand, sess = a_session
    ids = _topics(6)
    plan = _planner(engine, ids).plan(
        session_id=sess, candidate_id=cand, scope_module_ids=["mod-1"],
        duration_seconds=6 * SECONDS_PER_QUESTION, rng=np.random.default_rng(3),
    )
    assert plan.breadth == "full"
    assert len(plan.items) == 6
    assert all(len(i.topic_ids) == 1 for i in plan.items)


def test_a_clock_longer_than_the_scope_still_asks_one_question_per_topic(a_session):
    """A question about no Topic is not a question, so the budget is capped."""
    engine, cand, sess = a_session
    plan = _planner(engine, _topics(3)).plan(
        session_id=sess, candidate_id=cand, scope_module_ids=["mod-1"],
        duration_seconds=40 * SECONDS_PER_QUESTION, rng=np.random.default_rng(3),
    )
    assert plan.budget_questions == 40
    assert len(plan.items) == 3


def test_a_clock_below_the_minimum_leaves_the_tail_unplanned(a_session):
    """Grouping buys a bounded amount of time, and past the bound the honest
    answer is fewer Topics rather than a question spanning nine."""
    engine, cand, sess = a_session
    plan = _planner(engine, _topics(12)).plan(
        session_id=sess, candidate_id=cand, scope_module_ids=["mod-1"],
        duration_seconds=SECONDS_PER_QUESTION, rng=np.random.default_rng(3),
    )
    assert len(plan.items) == 1
    assert len(plan.items[0].topic_ids) == 3


# --- what the model is allowed to decide ------------------------------------


def _reply_grouping(ranked, sizes, focus="what this would test"):
    lines, cursor = [], 0
    for size in sizes:
        group = ranked[cursor:cursor + size]
        cursor += size
        lines.append(f"ITEM: {', '.join(group)} | {focus}")
    return "\n".join(lines)


def test_a_well_formed_grouping_is_taken_as_given(a_session):
    engine, cand, sess = a_session
    ids = _topics(12)
    planner = _planner(engine, ids)
    ranked = TopicSelector(ConfidenceStore(engine)).rank(
        candidate_id=cand, topic_ids=ids, rng=np.random.default_rng(3))
    model = _Replies(_reply_grouping(ranked, [3, 3, 2, 2, 2], "the trade it makes"))

    plan = planner.plan(
        session_id=sess, candidate_id=cand, scope_module_ids=["mod-1"],
        duration_seconds=15 * 60, rng=np.random.default_rng(3),
        model=model, model_ref=f"plan_{sess}", provider="deepseek",
    )
    assert plan.planner_fallback is False
    assert plan.planner_provider == "deepseek"
    assert [len(i.topic_ids) for i in plan.items] == [3, 3, 2, 2, 2]
    assert all(i.focus == "the trade it makes" for i in plan.items)
    # Exactly one, and it carries the plan's own attribution rather than a
    # Topic Visit that does not exist yet.
    assert len(model.calls) == 1
    assert model.calls[0]["topic_visit_id"] == f"plan_{sess}"
    assert model.calls[0]["role"] == "session_planner"


@pytest.mark.parametrize("reply, why", [
    ("I would start with attention and then move on.", "prose"),
    ("", "nothing at all"),
    ("ITEM: t00 | one\nITEM: t01 | two", "too few items"),
    ("\n".join(f"ITEM: t{i:02d} | x" for i in range(11)), "too many items"),
    ("ITEM: t00, t01, t02, t03 | x\nITEM: t04 | x\nITEM: t05 | x\n"
     "ITEM: t06 | x\nITEM: t07 | x", "an item spanning four Topics"),
    ("ITEM: t00 | x\nITEM: t00 | x\nITEM: t01 | x\nITEM: t02 | x\nITEM: t03 | x",
     "the same Topic in two items"),
    ("ITEM: nope | x\nITEM: t01 | x\nITEM: t02 | x\nITEM: t03 | x\nITEM: t04 | x",
     "a Topic that is not in scope"),
])
def test_a_reply_that_is_not_a_plan_still_yields_a_plan(a_session, reply, why):
    """The first thing that happens in a Session may not be a 500."""
    engine, cand, sess = a_session
    plan = _planner(engine, _topics(12)).plan(
        session_id=sess, candidate_id=cand, scope_module_ids=["mod-1"],
        duration_seconds=15 * 60, rng=np.random.default_rng(3),
        model=_Replies(reply), model_ref=f"plan_{sess}", provider="deepseek",
    )
    assert plan.planner_fallback is True, why
    assert len(plan.items) == 5
    assert all(1 <= len(i.topic_ids) <= 3 for i in plan.items)
    # A fallback plan claims no Provider: nothing a Provider said survived.
    assert plan.planner_provider is None


def test_a_plan_never_names_a_topic_outside_the_scope(a_session):
    engine, cand, sess = a_session
    ids = _topics(12)
    reply = "\n".join(
        ["ITEM: t00, smuggled | x"] + [f"ITEM: t{i:02d} | x" for i in range(1, 5)]
    )
    plan = _planner(engine, ids).plan(
        session_id=sess, candidate_id=cand, scope_module_ids=["mod-1"],
        duration_seconds=15 * 60, rng=np.random.default_rng(3),
        model=_Replies(reply),
    )
    named = {t for i in plan.items for t in i.topic_ids}
    assert "smuggled" not in named
    assert named <= set(ids)


def test_validation_says_what_was_wrong_rather_than_repairing_it():
    with pytest.raises(PlanRejected, match="not in scope"):
        SessionPlanner.validate(
            [(["a"], "x"), (["ghost"], "x")], ranked=["a", "b"], wanted=2)
    with pytest.raises(PlanRejected, match="spans 4 topics"):
        SessionPlanner.validate(
            [(["a", "b", "c", "d"], "x")], ranked=list("abcd"), wanted=1)
    with pytest.raises(PlanRejected, match="expected 2 items"):
        SessionPlanner.validate([(["a"], "x")], ranked=["a", "b"], wanted=2)


def test_a_provider_failure_is_not_a_bad_plan(a_session):
    """It parks, like every other model call. A dropped connection must not
    lock a Candidate into a fallback plan they can never replace."""
    from interviewer.service.metering.client import ProviderFailure

    class _Down:
        def complete(self, **kw):
            raise ProviderFailure("provider_timeout", "deepseek")

    engine, cand, sess = a_session
    with pytest.raises(ProviderFailure):
        _planner(engine, _topics(12)).plan(
            session_id=sess, candidate_id=cand, scope_module_ids=["mod-1"],
            duration_seconds=900, rng=np.random.default_rng(3), model=_Down(),
        )
    assert PlanStore(engine).get(sess) is None


# --- fixedness --------------------------------------------------------------


def test_the_same_seed_plans_the_same_session(a_session, clean_db):
    engine, cand, sess = a_session
    ids = _topics(12)

    def once(session_id):
        return _planner(engine, ids).plan(
            session_id=session_id, candidate_id=cand, scope_module_ids=["mod-1"],
            duration_seconds=15 * 60, rng=np.random.default_rng(19),
        )

    second = f"sess_{uuid.uuid4().hex[:8]}"
    with clean_db.begin() as c:
        c.execute(sa.insert(S.session).values(
            session_id=second, candidate_id=cand, mode="managed",
            payment_route="credits", scope_module_ids=["mod-1"],
            duration_seconds=900, rubric_version="v2",
        ))
    a, b = once(sess), once(second)
    assert [i.topic_ids for i in a.items] == [i.topic_ids for i in b.items]


def test_a_plan_item_is_fixed_once_written(a_session):
    """The trigger, against a row the planner itself wrote."""
    engine, cand, sess = a_session
    plan = _planner(engine, _topics(6)).plan(
        session_id=sess, candidate_id=cand, scope_module_ids=["mod-1"],
        duration_seconds=900, rng=np.random.default_rng(3),
    )
    item = plan.items[0]
    with pytest.raises(DBAPIError, match="fixed once planned"):
        with engine.begin() as c:
            c.execute(sa.update(S.plan_item)
                      .where(S.plan_item.c.plan_item_id == item.plan_item_id)
                      .values(topic_ids=["something-else"]))


def test_the_stored_plan_reads_back_exactly_as_written(a_session):
    engine, cand, sess = a_session
    plan = _planner(engine, _topics(12)).plan(
        session_id=sess, candidate_id=cand, scope_module_ids=["mod-1"],
        duration_seconds=900, rng=np.random.default_rng(3),
    )
    assert PlanStore(engine).get(sess) == plan


# --- the graph builds it, once ----------------------------------------------


def test_a_session_has_a_plan_before_its_first_question(deps, clean_db):
    r = SessionRunner(deps)
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:1]
    sid, first = r.start(
        candidate_id=CANDIDATE,
        cfg=SessionConfig(scope_module_ids=tuple(mods), duration_seconds=1800),
    )
    plan = PlanStore(clean_db).get(sid)
    assert plan is not None
    assert plan.items
    assert plan.chosen_seconds == 1800
    in_scope = set(deps.corpus.topic_ids_for(mods))
    assert {t for i in plan.items for t in i.topic_ids} <= in_scope


def test_resuming_reads_the_stored_plan_rather_than_making_a_second_one(
    deps, clean_db
):
    """Fixedness survives a restart because the plan is in Postgres."""
    r = SessionRunner(deps)
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:1]
    sid, _ = r.start(
        candidate_id=CANDIDATE,
        cfg=SessionConfig(scope_module_ids=tuple(mods), duration_seconds=1800),
    )
    before = PlanStore(clean_db).get(sid)

    # A fresh runner is a fresh checkpointer: nothing of the first run survives
    # in memory, which is the whole point of asking the database. The Visit the
    # first run opened is abandoned, which is what a Session parked at a Visit
    # boundary looks like from the database's side.
    deps.visits.abandon(deps.visits.unresolved(sid)["topic_visit_id"])
    deps.sessions.park(sid, "provider_failure")
    again = SessionRunner(deps)
    again.resume_after_interruption(sid)

    # Fixed, item for item: the same Topics in the same order under the same
    # focus. `state` is the one column the trigger lets move — an item asked
    # before the park is still asked after it — so the comparison is of the
    # plan rather than of what has happened to it (ISSUE-0042).
    after = PlanStore(clean_db).get(sid)
    assert [(i.plan_item_id, i.item_order, i.topic_ids, i.focus)
            for i in after.items] == [
        (i.plan_item_id, i.item_order, i.topic_ids, i.focus) for i in before.items
    ]
    planner_calls = [c for c in deps.ports.model.calls
                     if c["role"] == "session_planner"]
    assert len(planner_calls) == 1
    with clean_db.connect() as c:
        headers = c.execute(
            sa.select(sa.func.count()).select_from(S.session_plan)
            .where(S.session_plan.c.session_id == sid)
        ).scalar()
    assert headers == 1


# --- the endpoint -----------------------------------------------------------


@pytest.fixture()
def client(clean_db, served_corpus):
    from interviewer import idempotency
    from interviewer.wiring import wiring

    wiring.cache_clear()
    idempotency.reset()
    return signed_in_client()


@pytest.fixture()
def started(client):
    mods = [m["module_id"] for m in
            client.get("/v1/skills/modules", params={"track": "aiml"}).json()]
    client.post("/v1/credits/grants", headers={"x-operator-token": "dev-operator-token"},
                json={"candidate_id": "c_signed_in", "credits": 90_000,
                      "payment_ref": "pay_plan"})
    r = client.post("/v1/sessions", json={"module_ids": mods[:1],
                                          "duration_seconds": 900})
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def test_the_plan_endpoint_serves_the_plan(client, started):
    body = client.get(f"/v1/sessions/{started}/plan").json()
    assert body["budget_questions"] == 5
    assert body["chosen_seconds"] == 900
    assert body["suggested_seconds"] > 0
    assert body["breadth"] in ("full", "compressed")
    assert body["items"]
    assert [i["item_order"] for i in body["items"]] == list(
        range(len(body["items"])))
    for item in body["items"]:
        assert 1 <= len(item["topic_ids"]) <= 3
        assert len(item["topic_titles"]) == len(item["topic_ids"])
    # The Session is already running the plan (ISSUE-0042): its first question
    # has been asked and everything after it is still waiting.
    assert [i["state"] for i in body["items"]] == (
        ["asked"] + ["planned"] * (len(body["items"]) - 1)
    )


def test_reading_the_plan_twice_returns_the_same_bytes(client, started):
    a = client.get(f"/v1/sessions/{started}/plan")
    b = client.get(f"/v1/sessions/{started}/plan")
    assert a.content == b.content


def test_the_plan_belongs_to_the_candidate_who_started_the_session(client, started):
    other = signed_in_client("someone_else")
    assert other.get(f"/v1/sessions/{started}/plan").status_code == 404


def test_a_session_with_no_plan_is_not_an_empty_plan(client):
    assert client.get("/v1/sessions/sess_nothing/plan").status_code == 404
