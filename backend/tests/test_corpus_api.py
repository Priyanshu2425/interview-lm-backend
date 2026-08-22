"""ISSUE-0001 — the picker's end of the vertical slice.

Asserts what a Candidate choosing scope would see, and the two things the API
must structurally refuse to say.
"""

import pytest
from fastapi.testclient import TestClient

from interviewer.api.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_modules_carry_real_topic_and_ground_truth_counts(client):
    rows = client.get("/v1/corpus/modules").json()
    assert len(rows) == 15
    assert sum(r["topic_count"] for r in rows) == 71

    aiml = [r for r in rows if r["track_key"] == "aiml"]
    assert [r["ground_truth_topic_count"] for r in aiml] == [4, 5, 5, 5, 4, 3, 0, 0]


def test_modules_can_be_filtered_by_track(client):
    dsa = client.get("/v1/corpus/modules", params={"track": "dsa"}).json()
    assert len(dsa) == 7
    assert sum(r["topic_count"] for r in dsa) == 14
    assert all(r["ground_truth_topic_count"] == 0 for r in dsa)


def test_scope_reports_what_the_chosen_modules_can_produce(client):
    rows = client.get("/v1/corpus/modules", params={"track": "aiml"}).json()
    ids = [rows[0]["module_id"], rows[5]["module_id"]]  # Data Foundations + NLP
    s = client.get("/v1/corpus/scope", params=[("module_id", i) for i in ids]).json()
    assert s["module_count"] == 2
    assert s["topic_count"] == 10
    assert s["ground_truth_topic_count"] == 7
    assert s["strongest_mode"] == "ground_truth"


def test_an_empty_scope_reports_nothing_rather_than_failing(client):
    s = client.get("/v1/corpus/scope").json()
    assert s == {
        "module_count": 0,
        "topic_count": 0,
        "ground_truth_topic_count": 0,
        "strongest_mode": None,
    }


def test_a_module_without_answer_keys_is_selectable_and_says_so(client):
    rows = client.get("/v1/corpus/modules", params={"track": "aiml"}).json()
    genai = next(r for r in rows if r["title"].startswith("Basics of GenAI"))
    assert genai["ground_truth_topic_count"] == 0
    assert genai["ceiling"] == "text_grounded"

    s = client.get(
        "/v1/corpus/scope", params=[("module_id", genai["module_id"])]
    ).json()
    assert s["topic_count"] == 9
    assert s["strongest_mode"] == "text_grounded"


def test_no_corpus_response_carries_a_difficulty_field(client):
    for path in ("/v1/corpus/modules", "/v1/corpus/tracks"):
        body = client.get(path).text.lower()
        assert "difficult" not in body
        assert '"level"' not in body


def test_no_corpus_response_leaks_ground_truth_text(client):
    """A Candidate-facing route never returns grading material."""
    body = client.get("/v1/corpus/topics/cmrovsvm21xy1qj0fmr2rinvz").json()
    assert "text" not in body
    assert "ground_truth" not in {k for k in body if k != "grading_mode_ceiling"}
    assert body["grading_mode_ceiling"] == "ground_truth"


def test_an_unknown_topic_is_a_404(client):
    assert client.get("/v1/corpus/topics/nope").status_code == 404


def test_provenance_says_which_extract_this_is(client):
    p = client.get("/v1/corpus/provenance").json()
    assert p["source"] == "cortex.scaler.com"
    assert p["adapter"] == "cortex"
    assert p["extracted_at"]
