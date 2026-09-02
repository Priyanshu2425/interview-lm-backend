"""One Session, read once — and therefore read the same by every endpoint.

`/sessions/{id}`, `/plan`, `/report` and `/summary` are four questions about
one Session. Each used to assemble its own answer, and the answers disagreed:
the report called a Topic *reached* when it had an Evidence row, the summary
called it *examined* when it had an answered Visit, the plan came out in one
shape here and another there, and the rule that a retired Topic keeps its id
as its title was written out three times.

The disagreements were never about the Session. They were about how to read
it, and there is one reading now.
"""


from conftest import signed_in_client

from interviewer.service.confidence.reading_service import (
    SessionFacts,
    reached_topic_ids,
    title_of,
)
from interviewer.service.graph.planner_service import PlanStore
from interviewer.service.graph.runner_service import SessionRunner
from interviewer.service.graph.sessions import SessionConfig

CAND = "cand_one_reading"


def _svc(deps, clean_db, corpus=None):
    from interviewer.service.confidence.reading_service import SessionReadingService

    return SessionReadingService(
        sessions=deps.sessions, visits=deps.visits, evidence=deps.evidence,
        plans=PlanStore(clean_db), loader=deps.loader,
        confidence=deps.confidence, corpus=corpus,
    )


def _outran_its_clock(deps):
    """One question asked, the rest of the plan left unreached."""
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:1]
    r = SessionRunner(deps)
    sid, _ = r.start(
        candidate_id=CAND,
        cfg=SessionConfig(scope_module_ids=tuple(mods), duration_seconds=1800),
    )
    deps.ports.clock.advance(3600)
    assert r.submit(sid, "the only answer this Session will get").kind \
        == "session_ended"
    return sid


# --- the rules that were written more than once -----------------------------


def test_reached_is_one_definition(deps, clean_db, corpus):
    """The report and the summary used to answer this differently about the
    same Session, and a Candidate reading both could see it."""
    sid = _outran_its_clock(deps)
    svc = _svc(deps, clean_db, corpus)
    reading = svc.read(sid)

    examined = {
        v["topic_id"] for v in reading.visits
        if v["state"] in ("answered", "graded")
    }
    assert examined
    assert examined <= reading.reached

    in_plan = {
        t["topic_id"]
        for item in svc.plan_of(reading)["items"] for t in item["topics"]
        if t["reached"]
    }
    named_as_missed = {
        t["topic_id"] for t in svc.report_of(reading).planned_not_reached
    }
    assert in_plan == reading.reached & set(reading.planned_topic_ids)
    assert not in_plan & named_as_missed


def test_a_topic_the_session_answered_is_never_called_unreached(deps, clean_db):
    """An answered Visit is a Topic the Session got to, whether or not the
    grade landed. Reading `reached` off the Evidence alone called a Session
    that was parked before grading a Session that reached nothing."""
    sid = _outran_its_clock(deps)
    svc = _svc(deps, clean_db)
    reading = svc.read(sid)
    answered = {v["topic_id"] for v in reading.visits if v["state"] != "asked"}

    missed = {t["topic_id"] for t in svc.report_of(reading).planned_not_reached}
    assert answered and not answered & missed


def test_a_retired_topic_keeps_its_id_as_its_title():
    """One handler, where there were three."""

    class _Gone:
        def load(self, topic_id):
            raise LookupError(topic_id)

    assert title_of(_Gone(), "topic_that_left") == "topic_that_left"


def test_the_session_row_is_read_by_name_and_not_by_key(deps, clean_db):
    """`provider_chosen` is the database's name for it. Every reader used to
    reach into a raw row for six keys and each had its own idea of which."""
    sid = _outran_its_clock(deps)
    facts = SessionFacts.of(deps.sessions.get(sid))
    assert facts.session_id == sid
    assert facts.provider
    assert facts.state in ("ended", "parked", "running")


def test_reached_counts_evidence_written_against_visits_this_loop_never_opened():
    """MCP Mode writes Evidence against its own Visits."""
    assert reached_topic_ids(
        visits=[{"topic_id": "t1", "state": "asked"}],
        evidence=[{"topic_id": "t2"}],
    ) == {"t2"}


# --- the endpoints agree ----------------------------------------------------


def test_the_plan_endpoint_and_the_report_serve_the_same_plan(clean_db,
                                                              served_corpus):
    """Two shapes of one plan is how they came to disagree about an item."""
    with signed_in_client() as client:
        from interviewer.wiring import wiring

        mods = [m.module_id for m in wiring().deps.corpus.modules("aiml")][:1]
        started = client.post(
            "/v1/sessions", json={"module_ids": mods, "duration_seconds": 900}
        )
        assert started.status_code == 201
        sid = started.json()["session_id"]
        client.post(f"/v1/sessions/{sid}/turns", json={"answer": "an answer"})
        client.post(f"/v1/sessions/{sid}/end")

        plan = client.get(f"/v1/sessions/{sid}/plan").json()
        report = client.get(f"/v1/sessions/{sid}/report").json()
        assert plan["items"] == report["plan"]["items"]

        reached = {
            t["topic_id"] for item in plan["items"] for t in item["topics"]
            if t["reached"]
        }
        missed = {t["topic_id"] for t in report["planned_not_reached"]}
        assert not reached & missed
