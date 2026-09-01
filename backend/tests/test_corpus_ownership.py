"""ISSUE-0032 — a Corpus has an owner, and a shared one cannot be deleted.

The delete guard is the point of this slice. ADR-0010 defined `content` as "the
Candidate's, and deleted when they say so", and a shared Corpus is not that:
without the guard, a Candidate deleting a Corpus they did not create retires the
`topic_id`s every other Candidate's Evidence points at, and nothing errors. The
damage surfaces weeks later, as somebody asking why their record looks thinner
than it did.

So the guard is asserted at the service, not at the route. A refusal that exists
only because nobody wrote the route is a refusal that lasts until somebody does.
"""

from __future__ import annotations

import pytest
from conftest import signed_in_client
from fastapi.testclient import TestClient

HDR = {"x-operator-token": "dev-operator-token"}


@pytest.fixture()
def client(content_db, clean_db):
    from interviewer.app import create_app
    from interviewer.deps import refresh_corpus

    refresh_corpus()
    with signed_in_client() as c:
        yield c
    refresh_corpus()


def _personal(client, candidate="cand-own", title="My notes"):
    return client.post(
        "/v1/notebooks", json={"candidate_id": candidate, "title": title}
    ).json()["notebook_id"]


def _shared(client, title="InterviewLM"):
    response = client.post("/v1/operator/skills", json={"title": title}, headers=HDR)
    assert response.status_code == 201, response.text
    return response.json()["notebook_id"]


# -- owner and visibility ----------------------------------------------------

def test_a_corpus_carries_an_owner_and_a_visibility(client):
    """The owner is the signed-in Candidate. There is no id to pass and no id
    to pass wrongly — a Library belongs to whoever uploaded it (ISSUE-0032)."""
    owner = signed_in_client("cand-own")
    assert owner.get("/v1/notebooks").json() == []
    _personal(owner)
    record = owner.get("/v1/notebooks").json()[0]
    assert record["candidate_id"] == "cand-own"
    assert record["visibility"] == "personal"


def test_personal_is_the_default_and_existing_rows_migrate_to_it(content_db):
    """A deployment that never creates a shared Corpus behaves exactly as today."""
    import sqlalchemy as sa

    from interviewer.db.content import notebook as notebook_t

    with content_db.begin() as c:
        # Written the way a row from before this column existed was written.
        c.execute(sa.insert(notebook_t).values(
            notebook_id="nb-old", candidate_id="cand-old",
            title="Older than the column", embedding_model="counting@8",
        ))
        assert c.execute(
            sa.select(notebook_t.c.visibility).where(
                notebook_t.c.notebook_id == "nb-old"
            )
        ).scalar_one() == "personal"


def test_a_candidate_cannot_create_a_shared_corpus(client):
    """Not refused — unreachable. The route takes no visibility at all."""
    created = client.post("/v1/notebooks", json={
        "candidate_id": "cand-own", "title": "Mine", "visibility": "shared",
    }).json()
    assert created["visibility"] == "personal"


def test_an_operator_can_create_a_shared_corpus(client):
    notebook_id = _shared(client)
    from interviewer.deps import get_notebook_service

    record = get_notebook_service().store.get(notebook_id)
    assert record.visibility == "shared"


def test_creating_a_shared_corpus_is_authenticated_as_an_operator(client):
    assert client.post("/v1/operator/skills", json={"title": "X"}).status_code == 401
    assert client.post(
        "/v1/operator/skills", json={"title": "X"},
        headers={"x-operator-token": "wrong"},
    ).status_code == 401


# -- who may write -----------------------------------------------------------

def test_a_candidate_may_add_a_source_to_their_own_corpus(client, real_notes):
    notebook_id = _personal(client)
    response = client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "AIML notes", "text": real_notes},
    )
    assert response.status_code == 201


def test_a_candidate_may_not_add_a_source_to_a_shared_corpus(client, real_notes):
    notebook_id = _shared(client)
    response = client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "Mine now", "text": real_notes},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "corpus_is_shared"
    assert response.json()["message"]


def test_an_operator_may_add_a_source_to_a_shared_corpus(client, real_notes):
    notebook_id = _shared(client)
    response = client.post(
        f"/v1/operator/skills/{notebook_id}/sources",
        json={"title": "Attention", "text": real_notes}, headers=HDR,
    )
    assert response.status_code == 201
    assert response.json()["module_id"]


# -- the delete guard --------------------------------------------------------

def test_deleting_a_shared_corpus_is_refused_at_the_service(client, real_notes):
    """Proved here rather than left to the absence of a route.

    A constraint that holds only because nobody wrote the call is a constraint
    that lasts until somebody does.
    """
    from interviewer.deps import get_notebook_service
    from interviewer.service.notebooks import SharedCorpusIsNotYours

    notebook_id = _shared(client)
    svc = get_notebook_service()
    with pytest.raises(SharedCorpusIsNotYours):
        svc.delete(notebook_id)
    assert svc.store.get(notebook_id) is not None


def test_deleting_a_shared_corpus_over_the_wire_names_a_code(client):
    notebook_id = _shared(client)
    response = client.delete(f"/v1/notebooks/{notebook_id}")
    assert response.status_code == 409
    assert response.json()["code"] == "corpus_is_shared"


def test_deleting_one_source_of_a_shared_corpus_is_refused_too(client, real_notes):
    """The retire path is the damage, and a Source carries Topics like a Corpus."""
    notebook_id = _shared(client)
    source_id = client.post(
        f"/v1/operator/skills/{notebook_id}/sources",
        json={"title": "Attention", "text": real_notes}, headers=HDR,
    ).json()["source_id"]
    response = client.delete(f"/v1/notebooks/{notebook_id}/sources/{source_id}")
    assert response.status_code == 409
    assert response.json()["code"] == "corpus_is_shared"


def test_the_guard_reads_visibility_and_not_the_owner_string(content_db):
    """`platform` is a sentinel for a column, never the rule itself.

    Keying the guard on an owner id would make a Candidate who happened to be
    called `platform` undeletable, and a shared Corpus imported under an
    operator's own id deletable.
    """
    from interviewer.repository.notebooks import NotebookStore

    store = NotebookStore(content_db)
    store.create("nb-odd", "platform", "Owned by a candidate called platform",
                 "counting@8")
    assert store.get("nb-odd").visibility == "personal"
    assert store.deletable("nb-odd") is True


def test_deleting_a_personal_corpus_behaves_exactly_as_before(client, real_notes):
    """ISSUE-0027 unchanged: content goes, Evidence stays."""
    notebook_id = _personal(client)
    client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "AIML notes", "text": real_notes},
    )
    assert client.delete(f"/v1/notebooks/{notebook_id}").status_code == 204
    assert client.get("/v1/notebooks?candidate_id=cand-own").json() == []


# -- what shared is for ------------------------------------------------------

def test_a_shared_corpus_is_visible_to_every_candidate(client, real_notes):
    notebook_id = _shared(client)
    client.post(
        f"/v1/operator/skills/{notebook_id}/sources",
        json={"title": "Attention", "text": real_notes}, headers=HDR,
    )
    for candidate in ("cand-a", "cand-b"):
        listed = client.get(f"/v1/notebooks?candidate_id={candidate}").json()
        assert [n["notebook_id"] for n in listed] == [notebook_id]
        assert listed[0]["visibility"] == "shared"


def test_a_shared_corpus_appears_in_the_picker_for_everyone(client, real_notes):
    notebook_id = _shared(client)
    module_id = client.post(
        f"/v1/operator/skills/{notebook_id}/sources",
        json={"title": "Attention", "text": real_notes}, headers=HDR,
    ).json()["module_id"]
    for candidate in ("cand-a", "cand-b"):
        modules = client.get(f"/v1/skills/modules?candidate_id={candidate}").json()
        assert module_id in {m["module_id"] for m in modules}


def test_one_candidates_notebook_is_still_invisible_to_another(client, real_notes):
    a, b = signed_in_client("cand-a"), signed_in_client("cand-b")
    notebook_id = _personal(a, "cand-a")
    a.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "AIML notes", "text": real_notes},
    )
    assert b.get("/v1/notebooks").json() == []


def test_two_candidates_examined_on_a_shared_topic_hold_the_same_topic_id(
    client, real_notes
):
    """The entire reason a shared Corpus exists.

    Topic Confidence is keyed on `topic_id`, so one shared Corpus is what makes
    two people's Mastery on a Topic the same measurement rather than two
    unrelated ones.
    """
    notebook_id = _shared(client)
    module_id = client.post(
        f"/v1/operator/skills/{notebook_id}/sources",
        json={"title": "Attention", "text": real_notes}, headers=HDR,
    ).json()["module_id"]

    def topics_for(candidate: str) -> set[str]:
        modules = client.get(f"/v1/skills/modules?candidate_id={candidate}").json()
        assert module_id in {m["module_id"] for m in modules}
        from interviewer.deps import get_corpus

        return {
            t.id for m in get_corpus().modules if m.id == module_id for t in m.topics
        }

    assert topics_for("cand-a") == topics_for("cand-b")
    assert topics_for("cand-a")


# -- comparison --------------------------------------------------------------

def test_a_personal_corpus_yields_no_comparison(client, real_notes):
    """Their cohort is one by construction, so no rule is needed to stop it.

    Said out loud anyway, because the absence of a rule is not obvious to the
    next reader — and ISSUE-0036 will be reaching for exactly this seam.
    """
    from interviewer.deps import get_notebook_service

    notebook_id = _personal(client)
    assert get_notebook_service().comparable(notebook_id) is False


def test_a_shared_corpus_is_what_a_comparison_may_be_drawn_over(client):
    from interviewer.deps import get_notebook_service

    assert get_notebook_service().comparable(_shared(client)) is True
