"""ISSUE-0045 — the report a Candidate reads when the Session ends.

The Session is graded once, at the end (ISSUE-0044), so this is the only place
a result is shown — which makes it the screen most likely to want to break the
refusals. Every test here is about a number that is easy and natural to
produce and must not be: a headline figure, a fused pair of sub-scores, and
above all a zero standing in for a Topic nobody asked about.

The Sessions are real and run to their ends, for ISSUE-0044's reason: a Topic
that was planned and never reached only exists where a plan outran its clock,
and a hand-built fixture is written by somebody who reached everything they
thought to write down.
"""

import pytest

from conftest import SIGNED_IN_CANDIDATE, grade_session, signed_in_client

from interviewer.service.confidence.reading import SessionReadingService
from interviewer.service.graph.planner import PlanStore
from interviewer.service.graph.runner import SessionRunner
from interviewer.service.graph.sessions import SessionConfig

CANDIDATE = "cand_reads_the_report"


def _cfg(deps, n=1, seconds=1800):
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:n]
    return SessionConfig(scope_module_ids=tuple(mods), duration_seconds=seconds)


def _svc(deps, clean_db, corpus=None):
    return SessionReadingService(
        sessions=deps.sessions, visits=deps.visits, evidence=deps.evidence,
        plans=PlanStore(clean_db), loader=deps.loader,
        confidence=deps.confidence, corpus=corpus,
    )


def _finished(deps, seconds=1800, n=1, candidate=CANDIDATE):
    r = SessionRunner(deps)
    sid, out = r.start(candidate_id=candidate, cfg=_cfg(deps, n=n, seconds=seconds))
    for _ in range(30):
        if out.kind == "session_ended":
            break
        out = r.submit(sid, "an answer worth grading")
    return sid


def _outran_its_clock(deps, candidate=CANDIDATE):
    """One question asked, the rest of the plan left unreached."""
    r = SessionRunner(deps)
    sid, _ = r.start(candidate_id=candidate, cfg=_cfg(deps, seconds=1800))
    deps.ports.clock.advance(3600)
    out = r.submit(sid, "the only answer this Session will get")
    assert out.kind == "session_ended"
    return sid


def _report(deps, clean_db, sid):
    return _svc(deps, clean_db).report(sid)


# --- reached and unreached are different things ----------------------------


def test_the_report_names_the_topics_it_reached_and_the_ones_it_did_not(
    deps, clean_db
):
    sid = _outran_its_clock(deps)
    rep = _report(deps, clean_db, sid)

    reached = {t["topic_id"] for t in rep.topics}
    missed = {t["topic_id"] for t in rep.planned_not_reached}
    assert reached and missed
    assert not reached & missed
    # Every one of them is named rather than counted.
    assert all(t["title"] for t in rep.planned_not_reached)


def test_an_unreached_topic_carries_no_band_no_score_and_no_interval(
    deps, clean_db
):
    """The property the whole set was ordered around. Untested is not zero."""
    sid = _outran_its_clock(deps)
    rep = _report(deps, clean_db, sid)

    assert rep.planned_not_reached
    for topic in rep.planned_not_reached:
        assert set(topic) == {"topic_id", "title"}
        flat = str(topic).lower()
        for banned in ("band", "score", "mastery", "coverage", "interval", "0"):
            assert banned not in flat.replace(topic["topic_id"].lower(), "")


def test_an_unreached_topic_is_not_quietly_given_the_prior(deps, clean_db):
    """A prior renders as a band — `untested` — and that is still a reading.

    An unreached Topic must not appear among the readings at all, because a
    row saying `untested` beside rows saying `early signal` reads as a Topic
    that was asked about and went nowhere.
    """
    sid = _outran_its_clock(deps)
    rep = _report(deps, clean_db, sid)
    plan = PlanStore(clean_db).get(sid)
    unreached = {t for i in plan.items if i.state == "unreached" for t in i.topic_ids}

    assert unreached
    assert not unreached & {t["topic_id"] for t in rep.topics}


def test_the_plan_says_what_became_of_every_item(deps, clean_db):
    sid = _outran_its_clock(deps)
    rep = _report(deps, clean_db, sid)

    states = [i["state"] for i in rep.plan["items"]]
    assert states[0] == "asked"
    assert set(states[1:]) == {"unreached"}
    assert rep.plan["budget_questions"] >= len(rep.plan["items"]) > 0
    # Both readings of the scope survive: a plan built for forty minutes and
    # run in twenty examined less, and the report can say so.
    assert rep.plan["suggested_seconds"] and rep.plan["chosen_seconds"]


# --- the refusals ----------------------------------------------------------


def test_no_field_fuses_coverage_with_mastery(deps, clean_db):
    sid = _finished(deps)
    rep = _report(deps, clean_db, sid)

    assert rep.topics
    for topic in rep.topics:
        assert "coverage" in topic and "mastery" in topic
        for banned in ("overall", "total", "percent", "combined", "final"):
            assert not [k for k in topic if banned in k]
    # And there is no Session-wide figure of any kind to fuse them into.
    for field in ("coverage", "mastery", "overall", "score"):
        assert not hasattr(rep, field)


def test_the_two_sub_scores_are_reported_apart_and_never_combined(deps, clean_db):
    """ISSUE-0043's pair. The number they fed the posterior is not a reading."""
    sid = _finished(deps)
    rep = _report(deps, clean_db, sid)

    for topic in rep.topics:
        assert "source_score" in topic and "truth_score" in topic
        # `evidence.score` is the combination. It is an input to the maths and
        # is deliberately not carried out here.
        assert "score" not in topic
        assert not [k for k in topic if k.endswith("_total") or k == "verdict"]

    stored = {r["topic_id"]: r for r in deps.evidence.for_session(sid)}
    for topic in rep.topics:
        row = stored[topic["topic_id"]]
        assert topic["truth_score"] == pytest.approx(float(row["truth_score"]))
        assert topic["question_count"] == row["question_count"]


def test_a_topic_below_the_evidence_floor_renders_the_word_not_a_number(
    deps, clean_db
):
    sid = _finished(deps, n=2, seconds=900)
    rep = _report(deps, clean_db, sid)

    # One question against a Topic with no Answer Key does not reach the
    # Floor: the interval is still nearly the whole unit line.
    below = [t for t in rep.topics if t["band"] == "untested"]
    assert below, "one model-judged question is not enough to report a figure"
    for topic in below:
        assert topic["label"] == "Untested"
        assert topic["mastery"] is None
        assert topic["interval"] is None


def test_a_reached_topic_carries_its_citations_and_the_mode_that_graded_it(
    deps, clean_db
):
    sid = _finished(deps)
    rep = _report(deps, clean_db, sid)
    assert all(t["graded_by"] for t in rep.topics)
    assert all(isinstance(t["citations"], list) for t in rep.topics)


# --- a report is what a Session gets, whatever happened to it ---------------


def test_a_session_that_reached_nothing_still_reports(deps, clean_db):
    """No error, no zeroes: a plan, and every Topic in it named as unreached."""
    r = SessionRunner(deps)
    sid, _ = r.start(candidate_id=CANDIDATE, cfg=_cfg(deps))
    rep = _report(deps, clean_db, sid)

    assert rep.topics == []
    assert rep.planned_not_reached
    assert all(set(t) == {"topic_id", "title"} for t in rep.planned_not_reached)


def test_a_session_with_no_plan_reports_rather_than_raising(deps, clean_db):
    """MCP Mode's Sessions, and anything from before ISSUE-0041."""
    deps.sessions.ensure_candidate(CANDIDATE)
    sid = deps.sessions.create(CANDIDATE, _cfg(deps))
    rep = _report(deps, clean_db, sid)
    assert rep.plan is None
    assert rep.topics == [] and rep.planned_not_reached == []


def test_the_same_session_reports_the_same_reading_twice(deps, clean_db):
    sid = _finished(deps)
    svc = _svc(deps, clean_db)
    assert svc.report(sid) == svc.report(sid)


def test_a_retired_topic_keeps_its_place_under_the_name_it_was_examined_by(
    deps, clean_db
):
    """Evidence outlives the material (ADR-0003)."""
    sid = _finished(deps)
    rep = _report(deps, clean_db, sid)
    stored = {r["topic_id"]: r for r in deps.evidence.for_session(sid)}
    for topic in rep.topics:
        assert topic["title"] == stored[topic["topic_id"]]["topic_title_snapshot"]


# --- the summary keeps working ---------------------------------------------


def test_the_summary_reads_evidence_by_session_and_topic(deps, clean_db, corpus):
    """ISSUE-0044 moved the key. A spanning question writes one row per Topic
    and all of them share a `topic_visit_id`, so a summary joined on the Visit
    would drop every row but the last and read it against the wrong Topic."""
    sid = _finished(deps, n=2, seconds=900)
    grade_session(deps, sid)
    out = _svc(deps, clean_db, corpus).summary(sid)

    stored = {r["topic_id"]: r for r in deps.evidence.for_session(sid)}
    assert out.per_topic
    for entry in out.per_topic:
        row = stored.get(entry["topic_id"])
        if row is not None:
            assert entry["title"] == row["topic_title_snapshot"]


# --- the endpoint ----------------------------------------------------------


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
                      "payment_ref": "pay_report"})
    return client.post("/v1/sessions", json={"module_ids": mods[:1],
                                             "duration_seconds": 900}).json()


@pytest.fixture()
def ended(client):
    sid = _start(client)["session_id"]
    for i in range(30):
        body = client.post(f"/v1/sessions/{sid}/turns",
                           json={"answer": f"answer {i}"}).json()
        if body["kind"] == "session_ended":
            break
    client.post(f"/v1/sessions/{sid}/end")
    return sid


def test_the_report_endpoint_serves_the_plan_and_the_readings(client, ended):
    body = client.get(f"/v1/sessions/{ended}/report").json()
    assert body["session_id"] == ended
    assert body["plan"]["items"]
    assert body["topics"]
    assert {t["topic_id"] for t in body["topics"]} & {
        t["topic_id"] for item in body["plan"]["items"] for t in item["topics"]
    }


def test_the_report_endpoint_shows_no_headline_figure(client, ended):
    body = client.get(f"/v1/sessions/{ended}/report").json()
    assert set(body) == {
        "session_id", "state", "ended_reason", "duration_seconds", "provider",
        "plan", "topics", "planned_not_reached",
    }
    for topic in body["topics"]:
        assert "score" not in topic


def test_the_report_belongs_to_the_candidate_who_ran_the_session(client, ended):
    other = signed_in_client("someone_else")
    assert other.get(f"/v1/sessions/{ended}/report").status_code == 404


def test_an_unknown_session_has_no_report(client):
    assert client.get("/v1/sessions/sess_nothing/report").status_code == 404


def test_the_summary_endpoint_still_answers(client, ended):
    assert client.get(f"/v1/sessions/{ended}/summary").status_code == 200
