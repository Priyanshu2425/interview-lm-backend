"""ISSUE-0048 — a Candidate says who they are, and the record says when.

Until this slice there was no moment at which the product learned anything
about the person using it. `display_name` had existed since the table did and
was never written, because its only writer built an upsert and returned without
running it.

These tests are about that moment: what the columns default to for everyone who
came before it, what the two `/me` routes answer, and what a second answer is
allowed to move. ADR-0026 is not reopened here — there is no credential and no
address anywhere below, and the last test says so where a reviewer can see it.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from conftest import signed_in_client
from interviewer.db import schema as S
from interviewer.db.engine import create_core
from interviewer.db.schema import CORE


def _cand() -> str:
    return f"cand_{uuid.uuid4().hex[:12]}"


@pytest.fixture()
def signed_in(clean_db):
    """A signed-in Candidate with no row of their own yet.

    Unseen in the sense the ticket means it: a token has verified, and nothing
    in `core` has ever been told anything about them.
    """
    candidate_id = _cand()
    return candidate_id, signed_in_client(candidate_id)


# --- the columns ----------------------------------------------------------

def test_an_existing_candidate_reads_as_unanswered_rather_than_unknown(clean_db):
    """The defaults are what every row that predates the form gets."""
    cid = _cand()
    with clean_db.begin() as c:
        c.execute(sa.insert(S.candidate).values(candidate_id=cid))
        row = c.execute(
            sa.select(S.candidate).where(S.candidate.c.candidate_id == cid)
        ).one()

    assert row.onboarded_at is None, "null is the only honest 'never completed'"
    assert (row.target_role, row.experience_level, row.goal) == ("", "", "")


def test_create_core_against_a_populated_database_is_a_no_op_the_second_time(clean_db):
    """The migrator looks before it ALTERs, so a second boot changes nothing.

    A row is present on purpose. `create_all` is trivially idempotent against an
    empty database; the failure worth catching is a migrator that re-applies a
    `NOT NULL DEFAULT ''` over a Candidate's actual answers.
    """
    cid = _cand()
    with clean_db.begin() as c:
        c.execute(sa.insert(S.candidate).values(
            candidate_id=cid, display_name="Ada", target_role="backend",
            experience_level="senior", goal="ship the thing",
            onboarded_at=sa.func.now(),
        ))

    def snapshot():
        with clean_db.connect() as c:
            columns = c.execute(sa.text(
                "SELECT table_name, column_name, data_type, is_nullable, "
                "column_default FROM information_schema.columns "
                "WHERE table_schema = :s ORDER BY table_name, column_name"
            ), {"s": CORE}).all()
            row = c.execute(
                sa.select(S.candidate).where(S.candidate.c.candidate_id == cid)
            ).one()
        return columns, dict(row._mapping)

    before = snapshot()
    create_core(clean_db)
    assert snapshot() == before


# --- the reading ----------------------------------------------------------

def test_an_unseen_candidate_reads_as_not_onboarded(signed_in):
    cid, client = signed_in
    body = client.get("/v1/candidates/me").json()

    assert body == {"candidate_id": cid, "display_name": None, "onboarded": False}


def test_the_reading_carries_nothing_the_surface_was_not_promised(signed_in):
    """Three fields. The three answers are collected and not served."""
    _, client = signed_in
    client.patch("/v1/candidates/me", json={"display_name": "Ada", "goal": "a job"})

    assert set(client.get("/v1/candidates/me").json()) == {
        "candidate_id", "display_name", "onboarded",
    }


# --- the writing ----------------------------------------------------------

def test_a_patch_sets_the_name_and_flips_onboarded(signed_in, clean_db):
    cid, client = signed_in
    r = client.patch("/v1/candidates/me", json={
        "display_name": "Ada",
        "target_role": "backend engineer",
        "experience_level": "3-5 years",
        "goal": "interview in March",
    })

    assert r.status_code == 200
    assert r.json() == {"candidate_id": cid, "display_name": "Ada", "onboarded": True}
    assert client.get("/v1/candidates/me").json()["onboarded"] is True

    with clean_db.connect() as c:
        row = c.execute(
            sa.select(S.candidate).where(S.candidate.c.candidate_id == cid)
        ).one()
    assert row.target_role == "backend engineer"
    assert row.experience_level == "3-5 years"
    assert row.goal == "interview in March"
    assert row.onboarded_at is not None


def test_a_second_patch_changes_the_answers_and_does_not_move_the_stamp(
    signed_in, clean_db
):
    """The stamp records when the person finished, so a correction is not one."""
    cid, client = signed_in
    client.patch("/v1/candidates/me", json={"display_name": "Ada", "goal": "a job"})

    def stamped():
        with clean_db.connect() as c:
            return c.execute(sa.select(S.candidate.c.onboarded_at).where(
                S.candidate.c.candidate_id == cid
            )).scalar_one()

    first = stamped()
    client.patch("/v1/candidates/me", json={"display_name": "Ada Lovelace"})

    assert stamped() == first
    assert client.get("/v1/candidates/me").json()["display_name"] == "Ada Lovelace"


def test_an_omitted_field_is_left_alone_rather_than_reset(signed_in, clean_db):
    """It is a PATCH. Correcting the name must not erase the goal."""
    cid, client = signed_in
    client.patch("/v1/candidates/me", json={
        "display_name": "Ada", "target_role": "backend", "goal": "interview in March",
    })
    client.patch("/v1/candidates/me", json={"display_name": "Ada Lovelace"})

    with clean_db.connect() as c:
        row = c.execute(
            sa.select(S.candidate).where(S.candidate.c.candidate_id == cid)
        ).one()
    assert (row.target_role, row.goal) == ("backend", "interview in March")


def test_the_row_is_minted_by_the_patch_when_nothing_has_minted_it(
    signed_in, clean_db
):
    """`ensure_candidate` used to build its upsert and return without running it.

    `IdentityStore.resolve` hides that in production by inserting first. Here
    the dependency is overridden, so the PATCH is the only thing that can create
    the row — and if the upsert is inert again, this is where it shows.
    """
    cid, client = signed_in
    with clean_db.connect() as c:
        assert c.execute(sa.select(sa.func.count()).select_from(S.candidate).where(
            S.candidate.c.candidate_id == cid
        )).scalar_one() == 0

    assert client.patch("/v1/candidates/me", json={"display_name": "Ada"}).status_code == 200

    with clean_db.connect() as c:
        assert c.execute(sa.select(S.candidate.c.display_name).where(
            S.candidate.c.candidate_id == cid
        )).scalar_one() == "Ada"


def test_a_second_sign_in_never_resets_what_was_answered(signed_in, clean_db):
    """The upsert does nothing on conflict, and that is the whole point of it."""
    cid, client = signed_in
    client.patch("/v1/candidates/me", json={"display_name": "Ada", "goal": "a job"})
    client.patch("/v1/candidates/me", json={"display_name": "Ada"})

    with clean_db.connect() as c:
        assert c.execute(sa.select(S.candidate.c.goal).where(
            S.candidate.c.candidate_id == cid
        )).scalar_one() == "a job"


# --- what may not be said -------------------------------------------------

@pytest.mark.parametrize("field", ["candidate_id", "email", "password"])
def test_the_form_refuses_a_body_that_names_somebody_or_carries_a_credential(
    signed_in, field
):
    """ADR-0026, enforced rather than trusted.

    Refused rather than ignored: a surface that sent a `candidate_id` and got a
    200 would go on believing the field means something. `candidate_id` is the
    one that matters — the Candidate comes from the token — and email and
    password are here because the day somebody adds them is the day this fails.
    """
    _, client = signed_in
    r = client.patch("/v1/candidates/me", json={"display_name": "Ada", field: "x"})

    assert r.status_code == 422


def test_the_form_is_not_reachable_without_a_token(clean_db):
    from fastapi.testclient import TestClient

    from interviewer.app import create_app

    anonymous = TestClient(create_app())
    assert anonymous.get("/v1/candidates/me").status_code == 401
    assert anonymous.patch("/v1/candidates/me", json={}).status_code == 401
