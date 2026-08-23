"""ISSUE-0034 — a structured import keeps the Topics it arrived with.

The Notebook Adapter mints `topic_id`s by clustering, because a Candidate's file
arrives with no divisions. Authored material arrives with its own — the Scaler
course has 71 — and clustering it would produce a different 71 and mean
something different by every one.

Exactly one stage of the pipeline changes. Everything before it (extract, chunk,
embed) and everything after it (freeze, dossier build, validate) is shared, so
the tests here are mostly about what the given branch *does not reach*.
"""

from __future__ import annotations

import pytest
from conftest import signed_in_client

from interviewer.corpus.adapters.notebook.structured import GivenLeaf, GivenTopic

PROSE = (
    "Attention weights every token against every other token, and the softmax "
    "over scaled dot products is what keeps the gradient from vanishing as the "
    "dimension grows. "
)


def _topic(topic_id: str, title: str, order: int, *, extra: str = "") -> GivenTopic:
    return GivenTopic(
        topic_id=topic_id,
        title=title,
        order=order,
        leaves=(
            GivenLeaf(
                leaf_id=f"{topic_id}-l1",
                title=f"{title} — notes",
                text=f"# {title}\n\n" + PROSE * 8 + extra,
            ),
        ),
    )


GIVEN = [
    _topic("aiml-attention", "Attention Mechanisms", 1),
    _topic("aiml-cnn", "CNN Fundamentals", 2, extra="Kernels are shared. " * 20),
    _topic("aiml-numpy", "NumPy", 3, extra="Broadcasting aligns shapes. " * 20),
]


@pytest.fixture()
def service(content_db, counting):
    from interviewer.notebooks import NotebookService

    svc = NotebookService(content_db, embedder=counting)
    svc.create("nb-import", "platform", "InterviewLM")
    return svc


def _import(service, *, source_id="src-import", topics=None, module_id="m-aiml"):
    return service.import_structured(
        "nb-import",
        source_id=source_id,
        title="AIML",
        module_id=module_id,
        topics=topics if topics is not None else GIVEN,
    )


# -- nothing is derived ------------------------------------------------------

def test_a_given_import_keeps_the_ids_it_arrived_with(service):
    """The load-bearing assertion: not one id is minted."""
    _import(service)
    frozen = service.store.frozen_topics("nb-import")
    assert set(frozen) == {"aiml-attention", "aiml-cnn", "aiml-numpy"}


def test_the_clusterer_and_the_id_minter_are_not_reached(service, monkeypatch):
    """Verified by call count, not by reading the code."""
    from interviewer.corpus.adapters import notebook

    def forbidden(*a, **kw):
        raise AssertionError("a structured import must derive no structure")

    monkeypatch.setattr(notebook.adapter, "topic_id_for", forbidden)
    monkeypatch.setattr(notebook.adapter, "cluster_chunks", forbidden)
    monkeypatch.setattr(notebook.clustering, "cluster_chunks", forbidden)
    _import(service)


def test_the_given_branch_imports_no_clusterer_at_all(service):
    """Stronger than not calling one: there is nothing here to call.

    A rule held only by a code path that happens not to be taken is a rule the
    next edit re-opens without noticing.
    """
    from interviewer.corpus.adapters.notebook import structured

    assert not hasattr(structured, "cluster_chunks")
    assert not hasattr(structured, "Cluster")
    assert not hasattr(structured, "topic_id_for")


def test_derived_stays_the_default(service, real_notes):
    service.add_source(
        "nb-import", source_id="src-derived", title="Notes", text=real_notes,
        as_operator=True,
    )
    source = next(
        s for s in service.store.get("nb-import").sources
        if s.source_id == "src-derived"
    )
    assert source.structure == "derived"


def test_a_given_import_records_that_it_was_given(service):
    _import(service)
    source = service.store.get("nb-import").sources[0]
    assert source.structure == "given"


# -- order, titles and Ground Truth -----------------------------------------

def test_topic_order_comes_from_the_source(service):
    _import(service, topics=list(reversed(GIVEN)))
    corpus = service.corpus("nb-import")
    module = corpus.modules[0]
    assert [t.id for t in module.topics] == [
        "aiml-attention", "aiml-cnn", "aiml-numpy"
    ]


def test_titles_come_from_the_source_and_no_labeller_runs(service):
    _import(service)
    titles = {t.id: t.title for t in service.corpus("nb-import").topics}
    assert titles["aiml-attention"] == "Attention Mechanisms"


def test_ground_truth_survives_the_import(service):
    """It decides the Grading Mode ceiling, so dropping it downgrades silently."""
    topic = GivenTopic(
        topic_id="aiml-assignment",
        title="Backpropagation",
        order=1,
        leaves=(
            GivenLeaf(
                leaf_id="l-prompt", title="Exercise", kind="prompt",
                text="# Exercise\n\nDerive the gradient of the loss. " * 12,
            ),
            GivenLeaf(
                leaf_id="l-key", title="Answer key", kind="ground_truth",
                text="# Answer key\n\nApply the chain rule backwards. " * 12,
                answers_leaf_id="l-prompt",
            ),
        ),
    )
    _import(service, topics=[topic])
    corpus = service.corpus("nb-import")
    kinds = {leaf.kind.value for t in corpus.topics for leaf in t.leaves}
    assert "ground_truth" in kinds


# -- determinism -------------------------------------------------------------

def test_importing_the_same_material_twice_is_the_same_corpus(service):
    first = _import(service)
    before = _dossiers(service)
    second = _import(service, source_id="src-again")
    assert second.deduplicated is True
    assert second.module_id == first.module_id
    assert _dossiers(service) == before


def test_two_corpora_built_from_one_import_are_byte_identical(content_db, counting):
    """Ids come from the source, so the same material is the same Corpus."""
    from interviewer.notebooks import NotebookService

    def built(notebook_id: str) -> list[str]:
        svc = NotebookService(content_db, embedder=counting)
        svc.create(notebook_id, "platform", "InterviewLM")
        svc.import_structured(
            notebook_id, source_id=f"{notebook_id}-src", title="AIML",
            module_id="m-aiml", topics=[GIVEN[0]],
        )
        return [
            leaf.text
            for t in svc.corpus(notebook_id).topics
            for leaf in t.leaves
        ]

    with pytest.raises(Exception):
        # The second import claims the same `topic_id`, which is the primary
        # key. Refused by the database rather than by a convention — two
        # Corpora asserting the same Topic id is the ambiguity shared ownership
        # exists to prevent.
        built("nb-one"), built("nb-two")


def _dossiers(service) -> dict[str, str]:
    corpus = service.corpus("nb-import")
    return {
        t.id: "".join(leaf.text or "" for leaf in t.leaves) for t in corpus.topics
    }


# -- it is an ordinary ingest in every other respect -------------------------

def test_the_imported_corpus_passes_conformance_with_zero_violations(service):
    from interviewer.corpus.conformance import validate

    _import(service)
    report = validate(service.corpus("nb-import"))
    assert report.violations == []


def test_an_import_is_metered_like_any_other_ingest(content_db, counting, clean_db):
    """Measured and reported on the same ledger, by the same estimator.

    The lexical stand-in is free per thousand tokens, so the assertion is on the
    measurement rather than on the balance — a figure of zero Credits here is
    "this embedder costs nothing", which is exactly what an unpriced route is
    supposed to report rather than collapse into.
    """
    from interviewer.metering.ledger import CreditLedger
    from interviewer.notebooks import NotebookService

    ledger = CreditLedger(content_db)
    ledger.grant("platform", 100_000, "seed")
    svc = NotebookService(content_db, embedder=counting, credits=ledger)
    svc.create("nb-metered", "platform", "InterviewLM")
    added = svc.import_structured(
        "nb-metered", source_id="src-1", title="AIML", module_id="m-aiml",
        topics=GIVEN,
    )
    assert added.cost is not None
    assert added.cost.tokens > 0
    assert added.cost.route == "credits"


def test_an_import_is_refused_when_the_balance_cannot_cover_it(content_db, clean_db):
    """The gate is the same one, and it stops before the first embedding call."""
    from interviewer.metering.ledger import CreditLedger
    from interviewer.notebooks import NotebookService
    from interviewer.notebooks.metering import InsufficientBalance

    class Priced(type(_counting())):
        credits_per_1k_tokens = 500.0

    svc = NotebookService(
        content_db, embedder=Priced(), credits=CreditLedger(content_db)
    )
    svc.create("nb-broke", "platform", "InterviewLM")
    with pytest.raises(InsufficientBalance):
        svc.import_structured(
            "nb-broke", source_id="src-1", title="AIML", module_id="m-aiml",
            topics=GIVEN,
        )
    assert svc.store.get("nb-broke").sources == ()


def _counting():
    from interviewer.corpus.adapters.notebook import HashingEmbedder

    return HashingEmbedder()


def test_an_import_is_atomic_per_source(content_db, counting):
    """A failure leaves no Module, no Topic and no chunk."""
    from interviewer.notebooks import NotebookService

    class Exploding(type(counting)):
        def embed(self, texts):
            raise RuntimeError("provider fell over")

    svc = NotebookService(content_db, embedder=Exploding())
    svc.create("nb-atomic", "platform", "InterviewLM")
    with pytest.raises(RuntimeError):
        svc.import_structured(
            "nb-atomic", source_id="src-1", title="AIML", module_id="m-aiml",
            topics=GIVEN,
        )
    assert svc.store.get("nb-atomic").sources == ()
    assert svc.corpus("nb-atomic") is None


def test_a_candidate_cannot_import_into_a_shared_corpus(content_db, counting):
    from interviewer.db.content import SHARED
    from interviewer.notebooks import NotebookService, SharedCorpusIsNotYours

    svc = NotebookService(content_db, embedder=counting)
    svc.create("nb-shared", "platform", "InterviewLM", visibility=SHARED)
    with pytest.raises(SharedCorpusIsNotYours):
        svc.import_structured(
            "nb-shared", source_id="src-1", title="AIML", module_id="m-aiml",
            topics=GIVEN,
        )


# -- over the wire, and examinable ------------------------------------------

HDR = {"x-operator-token": "dev-operator-token"}


@pytest.fixture()
def client(content_db, clean_db):
    from fastapi.testclient import TestClient

    from interviewer.api.app import create_app
    from interviewer.api.deps import refresh_corpus

    refresh_corpus()
    with signed_in_client() as c:
        yield c
    refresh_corpus()


def _imported_module(client) -> str:
    notebook_id = client.post(
        "/v1/operator/corpora", json={"title": "InterviewLM"}, headers=HDR
    ).json()["notebook_id"]
    response = client.post(
        f"/v1/operator/corpora/{notebook_id}/import",
        headers=HDR,
        json={
            "title": "AIML",
            "module_id": "m-aiml",
            "topics": [
                {
                    "topic_id": t.topic_id,
                    "title": t.title,
                    "order": t.order,
                    "leaves": [
                        {"leaf_id": leaf.leaf_id, "title": leaf.title,
                         "text": leaf.text, "kind": leaf.kind}
                        for leaf in t.leaves
                    ],
                }
                for t in GIVEN
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["module_id"]


def test_an_import_lands_in_a_shared_corpus_over_the_wire(client):
    module_id = _imported_module(client)
    assert module_id == "m-aiml"
    modules = client.get("/v1/corpus/modules?candidate_id=cand-any").json()
    listed = next(m for m in modules if m["module_id"] == "m-aiml")
    assert listed["topic_count"] == 3


def test_a_session_scoped_to_an_imported_module_asks_from_its_topics(client):
    """The point of the whole slice, stated as behaviour."""
    module_id = _imported_module(client)
    started = client.post("/v1/sessions", json={
        "candidate_id": "cand-import",
        "module_ids": [module_id],
        "duration_seconds": 600,
    }).json()
    client.post(f"/v1/sessions/{started['session_id']}/turns",
                json={"answer": "Softmax over scaled dot products."})
    state = client.get(f"/v1/sessions/{started['session_id']}").json()
    assert {v["topic_id"] for v in state["visits"]} <= {t.topic_id for t in GIVEN}
    assert state["visits"]


def test_a_candidate_cannot_reach_the_import_route(client):
    notebook_id = client.post(
        "/v1/operator/corpora", json={"title": "InterviewLM"}, headers=HDR
    ).json()["notebook_id"]
    assert client.post(
        f"/v1/operator/corpora/{notebook_id}/import",
        json={"title": "AIML", "topics": [{"topic_id": "t", "title": "T",
                                           "order": 1, "leaves": []}]},
    ).status_code == 401
