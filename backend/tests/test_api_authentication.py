"""ISSUE-0011 — a Candidate is resolved from the token, never from the request.

The rest of the suite signs in by overriding one dependency, which is the right
trade for tests about something else — but it means nothing in those tests would
notice if the guard were removed. These would.

What is being closed here was open by construction rather than by oversight:
`POST /v1/credits/grants` took a `candidate_id` and minted Credits against it
with no authentication at all, and every reading under
`/v1/candidates/{candidate_id}/…` was legible to anyone who could name one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import signed_in_client
from interviewer.api.app import create_app

OPERATOR = {"x-operator-token": "dev-operator-token"}

#: Every Candidate-scoped route, and the method that reaches it.
GUARDED = [
    ("get", "/v1/candidates/me/confidence"),
    ("get", "/v1/candidates/me/credits"),
    ("get", "/v1/candidates/me/weakest"),
    ("get", "/v1/candidates/me/coverage-standing"),
    ("get", "/v1/candidates/me/topics/t1/standing"),
    ("post", "/v1/candidates/me/byok"),
    ("delete", "/v1/candidates/me/byok/key_1"),
    ("get", "/v1/notebooks"),
    ("get", "/v1/corpus/modules"),
    ("get", "/v1/corpus/provenance"),
    ("post", "/v1/notebooks"),
    ("post", "/v1/sessions"),
]


@pytest.fixture()
def anonymous(clean_db):
    """No override, no header. What the internet gets."""
    return TestClient(create_app())


@pytest.mark.parametrize("method,path", GUARDED)
def test_a_candidate_scoped_route_refuses_an_unauthenticated_caller(
    anonymous, method, path
):
    call = getattr(anonymous, method)
    r = call(path, json={}) if method == "post" else call(path)
    assert r.status_code == 401, f"{method.upper()} {path} answered {r.status_code}"
    assert r.json()["code"] == "not_signed_in"


@pytest.mark.parametrize("header", [
    {"authorization": "gibberish"},
    {"authorization": "Bearer"},
    {"authorization": "Bearer "},
    {"authorization": "Basic dXNlcjpwdw=="},
    {"authorization": "Bearer not.a.token"},
])
def test_a_token_that_is_not_one_is_refused(anonymous, header):
    r = anonymous.get("/v1/candidates/me/credits", headers=header)
    assert r.status_code == 401
    assert r.json()["code"] == "not_signed_in"


def test_minting_credits_is_the_operators_and_not_a_members(clean_db):
    """Signing in is not evidence that money arrived.

    A Candidate's own token must not mint Credits — for themselves least of all.
    """
    body = {"candidate_id": "cand_greedy", "credits": 100_000, "payment_ref": "free"}

    assert TestClient(create_app()).post("/v1/credits/grants", json=body).status_code == 401

    signed_in = signed_in_client("cand_greedy")
    assert signed_in.post("/v1/credits/grants", json=body).status_code == 401
    assert signed_in.get("/v1/candidates/me/credits").json()["balance"] == 0

    granted = signed_in.post("/v1/credits/grants", json=body, headers=OPERATOR)
    assert granted.status_code == 201
    assert signed_in.get("/v1/candidates/me/credits").json()["balance"] == 100_000


def test_one_candidate_cannot_read_anothers_record(clean_db):
    """`me` is not a path segment anybody can write."""
    mine = signed_in_client("cand_mine")
    theirs = signed_in_client("cand_theirs")

    theirs.post("/v1/credits/grants",
                json={"candidate_id": "cand_theirs", "credits": 500, "payment_ref": "p"},
                headers=OPERATOR)

    assert theirs.get("/v1/candidates/me/credits").json()["balance"] == 500
    assert mine.get("/v1/candidates/me/credits").json()["balance"] == 0


def test_a_key_cannot_be_revoked_by_somebody_who_learned_its_id(clean_db):
    """A key id comes back in the response that attached it, and travels."""
    owner = signed_in_client("cand_owner")
    attached = owner.post("/v1/candidates/me/byok",
                          json={"openrouter_key": "sk-or-v1-" + "b" * 32})
    assert attached.status_code == 201
    key_id = attached.json()["key_id"]

    thief = signed_in_client("cand_thief")
    assert thief.delete(f"/v1/candidates/me/byok/{key_id}").status_code == 404
    assert owner.get("/v1/candidates/me/credits").json()["route"] == "byok"

    assert owner.delete(f"/v1/candidates/me/byok/{key_id}").status_code == 200
    assert owner.get("/v1/candidates/me/credits").json()["route"] == "credits"


def test_no_route_takes_a_candidate_id_from_the_caller():
    """The rule, asserted against the schema rather than against memory.

    A route that wanted to trust a body would have to ask for it in writing.
    `/v1/credits/grants` is the one exception and is the operator's.
    """
    spec = create_app().openapi()
    offenders = [p for p in spec["paths"] if "{candidate_id}" in p]
    assert offenders == []

    for path, ops in spec["paths"].items():
        if path == "/v1/credits/grants":
            continue
        for method, op in ops.items():
            names = {p["name"] for p in op.get("parameters", [])}
            assert "candidate_id" not in names, f"{method.upper()} {path}"
