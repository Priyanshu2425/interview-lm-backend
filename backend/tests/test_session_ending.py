"""Ending a Session is one decision, made in one module.

Three callers end a Session — the graph's last node, `POST /end`, and the
resumption path that finds a Session whose process died after the graph
finished. Each used to carry its own copy of what ending meant, and the copies
disagreed: whether a reason is gradable was a `startswith("credits_exhausted")`
written twice and missing twice, and `/end` marked the row ended on the routes'
engine before grading on the graph's.

These tests hold the rule where it now lives, and hold the two Sessions that
must not be confused: one that stopped, and one that ran out of Credits.
"""

import pytest

from conftest import signed_in_client

from interviewer.service.ending import EndReason, SessionEnding


class _Sessions:
    """A Session row, as far as ending is concerned."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def end(self, session_id: str, reason: str) -> None:
        self.calls.append(("end", reason))

    def park(self, session_id: str, reason: str) -> None:
        self.calls.append(("park", reason))


class _Grader:
    def __init__(self) -> None:
        self.graded: list[str] = []

    def grade(self, session_id: str) -> list:
        self.graded.append(session_id)
        return ["one row"]


# --- the rule ---------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    ["duration", "plan_exhausted", "scope_exhausted", "candidate_ended"],
)
def test_a_session_that_is_over_is_ended_and_graded(reason):
    sessions, grader = _Sessions(), _Grader()
    out = SessionEnding(sessions=sessions, grader=grader).close("s1", reason)

    assert sessions.calls == [("end", reason)]
    assert grader.graded == ["s1"]
    assert out.state == "ended" and out.reason == reason and out.graded


@pytest.mark.parametrize(
    "reason", ["credits_exhausted", "credits_exhausted_mid_visit", "provider_failure"]
)
def test_a_session_that_can_be_picked_back_up_is_parked_and_never_graded(reason):
    """Grading a parked Session writes a Beta observation for a Candidate who
    is about to be asked more questions about the same Topics."""
    sessions, grader = _Sessions(), _Grader()
    out = SessionEnding(sessions=sessions, grader=grader).close("s1", reason)

    assert sessions.calls == [("park", reason)]
    assert grader.graded == []
    assert out.parked and out.graded == []


def test_the_reason_decides_and_not_the_spelling_of_it():
    """`credits_exhausted_mid_visit` parks because of what it is, not because
    two call sites both remembered to test the same prefix."""
    assert EndReason.CREDITS_EXHAUSTED_MID_VISIT.parks
    assert not EndReason.CREDITS_EXHAUSTED_MID_VISIT.gradable
    assert EndReason.DURATION.gradable


def test_a_reason_nobody_named_still_ends_and_still_grades():
    """Refusing to grade an unfamiliar reason would silently lose Evidence the
    Session had already earned. Parking is the closed set; ending is not."""
    sessions, grader = _Sessions(), _Grader()
    out = SessionEnding(sessions=sessions, grader=grader).close("s1", "who_knows")

    assert out.state == "ended"
    assert grader.graded == ["s1"]


def test_without_a_grader_the_plan_is_still_settled():
    """An unasked item is unreached rather than merely unfinished, and exactly
    one of the two paths says so."""

    class _Plans:
        def __init__(self):
            self.marked = []

        def mark_unreached(self, session_id):
            self.marked.append(session_id)
            return 3

    sessions, plans = _Sessions(), _Plans()
    SessionEnding(sessions=sessions, plans=plans).close("s1", "duration")
    assert plans.marked == ["s1"]


# --- the three callers ------------------------------------------------------


def test_the_graph_the_endpoint_and_the_resumption_path_share_one_ending():
    """Not three instances configured alike — one instance."""
    from interviewer.wiring import wiring

    wiring.cache_clear()
    ending = wiring().ending
    assert wiring().deps.ending is ending


def test_the_endpoint_ends_through_the_same_module(clean_db, served_corpus):
    """`/end` no longer marks the row on one engine and grades on the other."""
    with signed_in_client() as client:
        from interviewer.wiring import wiring

        mods = [m.module_id for m in wiring().deps.corpus.modules("aiml")][:1]
        started = client.post(
            "/v1/sessions", json={"module_ids": mods, "duration_seconds": 1800}
        )
        assert started.status_code == 201
        sid = started.json()["session_id"]
        client.post(f"/v1/sessions/{sid}/turns", json={"answer": "an answer"})

        out = client.post(f"/v1/sessions/{sid}/end")
        assert out.status_code == 200
        body = out.json()
        assert body["state"] == "ended"
        assert body["reason"] == EndReason.CANDIDATE_ENDED.value
        # Graded in the same call, against a row that already said `ended`.
        assert body["graded"] >= 1
        assert client.get(f"/v1/sessions/{sid}").json()["state"] == "ended"
