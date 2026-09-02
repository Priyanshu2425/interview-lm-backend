"""ISSUE-0042 — the Session runs the plan, and grades nothing.

ISSUE-0041 made a plan and served it. Here the loop executes it: one question
per plan item, in plan order, every turn written to the transcript, and no
Evidence at all until the Session is over and ISSUE-0044 grades it.

These are about the *loop*. What the plan contains is `test_session_plan.py`;
what the Judge does with a transcript is ISSUE-0044.
"""

import pytest
import sqlalchemy as sa

from conftest import SIGNED_IN_CANDIDATE, signed_in_client

from interviewer.db import schema as S
from interviewer.model.corpus_models import GradingMode, Leaf, LeafKind
from interviewer.service.corpus.loader_service import Dossier
from interviewer.service.graph.planner_service import PlanStore
from interviewer.service.graph.runner_service import SessionRunner
from interviewer.service.graph.sessions import SessionConfig
from interviewer.service.graph.transcript import Transcript
from interviewer.service.judge.question_writer_service import QuestionWriter, weakest

CANDIDATE = "cand_runs_plan"


def _cfg(deps, n=1, seconds=1800):
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:n]
    return SessionConfig(scope_module_ids=tuple(mods), duration_seconds=seconds)


def _run_to_the_end(r, sid, out, answer="an answer", limit=30):
    for _ in range(limit):
        if out.kind == "session_ended":
            break
        out = r.submit(sid, answer)
    return out


# --- the loop executes the plan --------------------------------------------


def test_a_full_session_runs_end_to_end_and_exhausts_its_plan(deps, clean_db):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    out = _run_to_the_end(r, sid, first)

    assert out.kind == "session_ended"
    assert out.payload["reason"] == "plan_exhausted"
    assert deps.sessions.get(sid)["state"] == "ended"

    plan = PlanStore(clean_db).get(sid)
    assert plan.items
    assert all(i.state == "asked" for i in plan.items)


def test_the_questions_are_asked_in_the_plans_order(deps, clean_db):
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    asked = [out.payload["topic_ids"]]
    for _ in range(30):
        out = r.submit(sid, "an answer")
        if out.kind == "session_ended":
            break
        asked.append(out.payload["topic_ids"])

    plan = PlanStore(clean_db).get(sid)
    assert asked == [list(i.topic_ids) for i in plan.items]
    # One Topic Visit per plan item, each pointing back at the item that
    # scheduled it.
    visits = deps.visits.for_session(sid)
    assert [v["plan_item_id"] for v in visits] == [
        i.plan_item_id for i in plan.items
    ]
    assert [v["topic_ids"] for v in visits] == [
        list(i.topic_ids) for i in plan.items
    ]


def test_a_question_never_reached_is_recorded_as_unreached(deps, clean_db):
    """A question nobody asked is not a question answered badly."""
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps, seconds=1800))
    assert len(PlanStore(clean_db).get(sid).items) > 1

    deps.ports.clock.advance(3600)          # the clock runs out mid-question
    out = r.submit(sid, "an answer after the deadline")
    assert out.payload["reason"] == "duration"

    states = [i.state for i in PlanStore(clean_db).get(sid).items]
    assert states[0] == "asked"
    assert set(states[1:]) == {"unreached"}


# --- nothing is graded ------------------------------------------------------


def test_no_evidence_row_is_written_while_the_session_is_running(deps, clean_db):
    """Rewritten by ISSUE-0044: *while running*, not ever.

    The Session is graded now — once, on the edge to END — so the assertion
    that held for the whole of a Session's life now holds up to the moment it
    ends. What ISSUE-0042 removed was the in-loop write path, and that is what
    is checked here: after every turn the Session is still running, there is no
    Evidence, no posterior and no Judge has been called.
    """
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    turns = 0
    while out.kind != "session_ended" and turns < 30:
        with clean_db.connect() as c:
            assert c.execute(
                sa.select(sa.func.count()).select_from(S.evidence)).scalar() == 0
        assert deps.confidence.all_for(CANDIDATE) == {}
        assert not [c for c in deps.ports.model.calls if c["role"] == "judge"]
        out = r.submit(sid, "an answer")
        turns += 1
    assert out.kind == "session_ended"


def test_no_turn_response_carries_a_score_a_band_or_a_last_visit(deps):
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    seen = [out]
    for _ in range(30):
        if out.kind == "session_ended":
            break
        out = r.submit(sid, "an answer")
        seen.append(out)

    for turn in seen:
        flat = str(turn.payload).lower()
        for banned in ("last_visit", "score", "band", "mastery", "coverage",
                       "rationale"):
            assert banned not in flat, (turn.kind, banned)


# --- the transcript ---------------------------------------------------------


def test_the_transcript_holds_every_question_probe_hint_and_answer(deps):
    deps.ports.model.replies["interviewer"] = [
        "ACTION: probe\nTEXT: Why does that follow?",
        "ACTION: hint\nTEXT: Think about the softmax tails.",
        "ACTION: close",
    ]
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    vid = first.payload["topic_visit_id"]
    for a in ("one", "two", "three"):
        r.submit(sid, a)

    said = [m for m in Transcript(deps.visits._e).of(sid)
            if m["topic_visit_id"] == vid]
    assert [m["kind"] for m in said] == [
        "question", "answer", "probe", "answer", "hint", "answer",
    ]
    assert [m["role"] for m in said] == [
        "interviewer", "candidate", "interviewer", "candidate",
        "interviewer", "candidate",
    ]
    assert [m["text"] for m in said if m["role"] == "candidate"] == [
        "one", "two", "three",
    ]


def test_the_transcript_is_one_ordered_record_of_the_whole_session(deps):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    _run_to_the_end(r, sid, first)

    said = Transcript(deps.visits._e).of(sid)
    assert [m["seq"] for m in said] == list(range(len(said)))
    # One question per plan item, and every answer belongs to a question.
    assert sum(1 for m in said if m["kind"] == "question") == len(
        deps.visits.for_session(sid))
    assert all(m["topic_visit_id"] and m["plan_item_id"] for m in said)


def test_a_spanning_items_messages_carry_all_of_its_topic_ids(deps, clean_db):
    r = SessionRunner(deps)
    # Twelve Topics and fifteen minutes: five questions, so some must group.
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps, n=2, seconds=900))
    _run_to_the_end(r, sid, first)

    plan = PlanStore(clean_db).get(sid)
    spanning = [i for i in plan.items if len(i.topic_ids) > 1]
    assert spanning, "a fifteen-minute Session over twelve Topics must group"

    said = Transcript(deps.visits._e).of(sid)
    for item in spanning:
        theirs = [m for m in said if m["plan_item_id"] == item.plan_item_id]
        assert theirs
        assert all(m["topic_ids"] == list(item.topic_ids) for m in theirs)


# --- the weakest mode -------------------------------------------------------


def _dossier(topic_id, *, with_key=False, with_text=False):
    content = (
        (Leaf(id=f"{topic_id}-c", order=1, title="Notes",
              kind=LeafKind.CONTENT, text="Some real material."),)
        if with_text else ()
    )
    pairs = (
        ((Leaf(id=f"{topic_id}-p", order=1, title="Q", kind=LeafKind.PROMPT,
               text="Question in the assignment."),
          Leaf(id=f"{topic_id}-k", order=2, title="A",
               kind=LeafKind.GROUND_TRUTH, text="The worked solution.",
               answers_leaf_id=f"{topic_id}-p")),)
        if with_key else ()
    )
    ceiling = (GradingMode.GROUND_TRUTH if with_key
               else GradingMode.TEXT_GROUNDED if with_text
               else GradingMode.MODEL_JUDGMENT)
    return Dossier(
        topic_id=topic_id, topic_title=f"Title {topic_id}", module_id="m",
        module_title="M", module_order=1, topic_order=1, content=content,
        ground_truth_pairs=pairs, syllabus=("a", "b"),
        grading_mode_ceiling=ceiling,
    )


@pytest.mark.parametrize("shapes, expected", [
    ([dict(with_key=True)], GradingMode.GROUND_TRUTH),
    ([dict(with_key=True), dict(with_text=True)], GradingMode.TEXT_GROUNDED),
    ([dict(with_key=True), dict()], GradingMode.MODEL_JUDGMENT),
    ([dict(with_text=True), dict(with_text=True)], GradingMode.TEXT_GROUNDED),
])
def test_a_spanning_question_records_the_weakest_mode_among_its_dossiers(
    shapes, expected
):
    """A composite question is only as grounded as its least-grounded part.

    Claiming otherwise would record a Ground-Truth grade against material that
    has no answer key — the strongest weight in the model, attached to the one
    thing that cannot support it.
    """
    from interviewer.service.graph.ports import ScriptedModel

    dossiers = [_dossier(f"t{i}", **kw) for i, kw in enumerate(shapes)]
    written = QuestionWriter().write(
        dossiers=dossiers, focus="how they relate",
        topic_visit_id="v1", model=ScriptedModel(default="What connects them?"),
    )
    assert written.mode is expected


def test_the_weakest_of_several_modes_is_the_least_authoritative():
    assert weakest([GradingMode.GROUND_TRUTH]) is GradingMode.GROUND_TRUTH
    assert weakest([GradingMode.GROUND_TRUTH,
                    GradingMode.MODEL_JUDGMENT]) is GradingMode.MODEL_JUDGMENT


def test_a_spanning_question_records_where_each_topic_grounded_it():
    from interviewer.service.corpus.citations import resolve
    from interviewer.service.graph.ports import ScriptedModel

    dossiers = [_dossier("t0", with_text=True), _dossier("t1", with_text=True)]
    written = QuestionWriter().write(
        dossiers=dossiers, topic_visit_id="v1",
        model=ScriptedModel(default="q?"),
    )
    assert written.grounding_ref["kind"] == "spanning"
    assert [p["topic_id"] for p in written.grounding_ref["parts"]] == ["t0", "t1"]
    # And a citation belongs to the Topic it came from, never to the other one.
    cited = resolve(dossiers[1], written.grounding_ref)
    assert [c["chunk_id"] for c in cited] == ["t1-c"]


def test_the_prompt_names_every_topic_the_question_must_span():
    from interviewer.service.graph.ports import ScriptedModel

    model = ScriptedModel(default="q?")
    QuestionWriter().write(
        dossiers=[_dossier("t0", with_text=True), _dossier("t1", with_text=True)],
        focus="the trade between them", topic_visit_id="v1", model=model,
    )
    asked = model.calls[0]["user"]
    assert "Title t0" in asked and "Title t1" in asked
    assert "the trade between them" in asked


# --- what did not change ----------------------------------------------------


def test_the_graph_still_parks_and_resumes_at_the_answer_turn(deps):
    r = SessionRunner(deps)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    deps.sessions.park(sid, "client_gone")

    back = r.resume_after_interruption(sid)
    assert back is not None
    assert back.payload["question"] == first.payload["question"]
    assert back.payload["topic_visit_id"] == first.payload["topic_visit_id"]
    assert deps.sessions.get(sid)["state"] == "running"


def test_metering_still_binds_one_provider_per_question(metered_deps, clean_db):
    d = metered_deps
    d.credits.grant(CANDIDATE, 200_000, "pay_meter")
    r = SessionRunner(d)
    sid, first = r.start(candidate_id=CANDIDATE, cfg=_cfg(d))
    _run_to_the_end(r, sid, first)

    visits = d.visits.for_session(sid)
    assert visits
    for v in visits:
        vid = v["topic_visit_id"]
        assert d.credits.visit_cost(vid) > 0
        with clean_db.connect() as c:
            providers = {
                row[0] for row in c.execute(
                    sa.select(S.call_record.c.provider)
                    .where(S.call_record.c.topic_visit_id == vid)
                ).all()
            }
        assert providers == {d.bindings.get(vid).provider}
    # And the plan's own call is still attributed to the plan (ISSUE-0041).
    assert d.credits.visit_cost(f"plan_{sid}") > 0


# --- the endpoint -----------------------------------------------------------


@pytest.fixture()
def client(clean_db, served_corpus):
    from interviewer import idempotency
    from interviewer.wiring import wiring

    wiring.cache_clear()
    idempotency.reset()
    return signed_in_client()


def _start(client):
    mods = [m["module_id"] for m in
            client.get("/v1/skills/modules", params={"track": "aiml"}).json()]
    client.post("/v1/credits/grants",
                headers={"x-operator-token": "dev-operator-token"},
                json={"candidate_id": SIGNED_IN_CANDIDATE, "credits": 90_000,
                      "payment_ref": "pay_transcript"})
    return client.post("/v1/sessions", json={"module_ids": mods[:1],
                                             "duration_seconds": 900}).json()


@pytest.fixture()
def answered(client):
    """A Session run to the end, so its whole transcript is written.

    A question's turns land together, when the question closes — so a Session
    stopped mid-question has a transcript that ends at the last question it
    finished, which is the right answer and not what this fixture is for.
    """
    sid = _start(client)["session_id"]
    for i in range(30):
        body = client.post(f"/v1/sessions/{sid}/turns",
                           json={"answer": f"answer {i}"}).json()
        if body["kind"] == "session_ended":
            break
    return sid


def test_the_transcript_endpoint_serves_the_messages_in_order(client, answered):
    body = client.get(f"/v1/sessions/{answered}/transcript").json()
    said = body["messages"]
    assert said
    assert [m["seq"] for m in said] == list(range(len(said)))
    assert said[0]["kind"] == "question" and said[0]["role"] == "interviewer"
    assert [m["text"] for m in said if m["kind"] == "answer"][:2] == [
        "answer 0", "answer 1",
    ]
    for m in said:
        assert m["topic_ids"] and m["plan_item_id"]


def test_the_transcript_carries_no_score(client, answered):
    flat = client.get(f"/v1/sessions/{answered}/transcript").text.lower()
    for banned in ("score", "band", "mastery", "rationale", "verdict"):
        assert banned not in flat


def test_a_turn_no_longer_returns_a_visit_result(client):
    sid = _start(client)["session_id"]
    body = client.post(f"/v1/sessions/{sid}/turns",
                       json={"answer": "one more"}).json()
    assert "last_visit" not in body["payload"]
    assert body["kind"] in ("question", "probe", "hint", "session_ended")


def test_the_transcript_belongs_to_the_candidate_who_ran_the_session(
    client, answered
):
    other = signed_in_client("someone_else")
    assert other.get(f"/v1/sessions/{answered}/transcript").status_code == 404


def test_a_session_that_has_said_nothing_has_an_empty_transcript(client):
    assert client.get("/v1/sessions/sess_nothing/transcript").status_code == 404
