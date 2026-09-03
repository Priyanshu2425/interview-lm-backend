"""Reading one document back — what the Notebook screen is a rendering of.

The screen shows a document's extracted text beside the Topics cut out of it,
and highlights the passages each Topic came from. That last part is a claim
about the data rather than a decoration: `text[char_start:char_end]` is the
chunk exactly (`util/chunking_utils`), so if the offsets and the text ever stop
describing one string, a Topic highlights the wrong passage and *nothing else
fails*. Most of this file exists to notice that.

The rest is the rule that a state is data. A document being read, one that
carried no text, and one whose embedding died are three different facts, and
none of them is an error — a document that vanished from this route would look
like one that never arrived.
"""

from __future__ import annotations

import pytest
from conftest import signed_in_client

HDR = {"x-operator-token": "dev-operator-token"}


@pytest.fixture()
def client(content_db, clean_db):
    from interviewer.deps import refresh_corpus

    refresh_corpus()
    with signed_in_client("cand-read") as c:
        yield c
    refresh_corpus()


def _with_a_document(client, ingested, real_notes, title="AIML notes"):
    """A notebook holding one ingested document, read back whole."""
    notebook_id = client.post("/v1/notebooks", json={"title": "My notes"}).json()[
        "notebook_id"
    ]
    source_id = client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": title, "text": real_notes},
    ).json()["source_id"]
    ingested(client, notebook_id)
    return notebook_id, source_id


def _read(client, notebook_id, source_id):
    response = client.get(f"/v1/notebooks/{notebook_id}/sources/{source_id}")
    assert response.status_code == 200, response.text
    return response.json()


# -- what the screen is made of ----------------------------------------------

def test_a_document_reads_back_with_its_text_and_its_topics(
    client, ingested, real_notes
):
    notebook_id, source_id = _with_a_document(client, ingested, real_notes)
    body = _read(client, notebook_id, source_id)

    assert body["state"] == "ready"
    assert body["text"].strip()
    assert body["topics"], "an ingested document produced no Topics"
    assert body["topic_count"] == len(body["topics"])
    orders = [t["topic_order"] for t in body["topics"]]
    assert orders == sorted(orders), "Topics arrived out of the order they were frozen"
    assert all(t["title"] for t in body["topics"])


def test_every_span_indexes_the_text_it_was_drawn_from(client, ingested, real_notes):
    """The claim the whole screen makes.

    Every span must address a real, non-empty passage of the text served
    beside it, and must sit inside the page it says it is on. A drift here is
    invisible everywhere else: the request still answers, the screen still
    renders, and the highlight is simply over the wrong sentence.
    """
    notebook_id, source_id = _with_a_document(client, ingested, real_notes)
    body = _read(client, notebook_id, source_id)
    text, pages = body["text"], body["pages"]

    spans = [s for t in body["topics"] for s in t["spans"]]
    assert spans, "no Topic carried a span, so nothing could be highlighted"

    for span in spans:
        assert 0 <= span["char_start"] < span["char_end"] <= len(text)
        assert text[span["char_start"] : span["char_end"]].strip()
        if pages:
            page = next(
                (
                    p
                    for p in pages
                    if p["char_start"] <= span["char_start"] < p["char_end"]
                ),
                None,
            )
            assert page is not None, "a span fell outside every page of its document"
            assert page["number"] == span["page"]


def test_reading_a_document_never_materialises_a_vector(client, ingested, real_notes):
    """768 floats per Topic and per chunk that no screen can use. The
    enforcement is that the fields are absent, not that a caller drops them."""
    notebook_id, source_id = _with_a_document(client, ingested, real_notes)
    body = _read(client, notebook_id, source_id)

    assert "centroid" not in repr(body)
    assert "embedding" not in repr(body)
    assert all("chunk_hashes" not in t for t in body["topics"])


def test_a_span_does_not_carry_the_passage_twice(client, ingested, real_notes):
    """The span *is* a slice of the text already served, so repeating it would
    send the document a second time in the same response."""
    notebook_id, source_id = _with_a_document(client, ingested, real_notes)
    body = _read(client, notebook_id, source_id)

    for topic in body["topics"]:
        assert all("text" not in span for span in topic["spans"])


# -- a state is data ---------------------------------------------------------

def test_a_document_with_no_text_says_why_rather_than_erroring(client):
    """A recording is kept and listed. Hiding it would make it indistinguishable
    from a document that never arrived."""
    notebook_id = client.post("/v1/notebooks", json={"title": "Mixed"}).json()[
        "notebook_id"
    ]
    source_id = client.post(
        f"/v1/notebooks/{notebook_id}/sources",
        json={"title": "lecture.mp4", "text": "", "stub_reason": "no extractable text"},
    ).json()["source_id"]

    body = _read(client, notebook_id, source_id)
    assert body["state"] == "stub"
    assert body["stub_reason"]
    assert body["text"] == ""
    assert body["topics"] == []
    assert body["topic_count"] == 0


# -- whose document it is ----------------------------------------------------

def test_another_candidates_document_is_not_readable(client, ingested, real_notes):
    notebook_id, source_id = _with_a_document(client, ingested, real_notes)
    with signed_in_client("cand-somebody-else") as stranger:
        assert (
            stranger.get(f"/v1/notebooks/{notebook_id}/sources/{source_id}").status_code
            == 404
        )


def test_a_source_id_from_another_notebook_is_unknown(client, ingested, real_notes):
    """Both ids are checked, so a source id learned somewhere else does not
    resolve just because the notebook in the path is yours."""
    notebook_id, source_id = _with_a_document(client, ingested, real_notes)
    other = client.post("/v1/notebooks", json={"title": "Another"}).json()[
        "notebook_id"
    ]

    response = client.get(f"/v1/notebooks/{other}/sources/{source_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "unknown source_id"


def test_an_unknown_notebook_is_a_404(client):
    assert client.get("/v1/notebooks/nb-nope/sources/s1").status_code == 404


# -- the Library is your own material ----------------------------------------

def test_a_shared_corpus_is_not_in_anybodys_notebook(client, served_corpus):
    """It is imported by an operator and chosen at Session setup. Listing it
    beside a Candidate's own uploads made the Notebook screen a place where
    material they never added sat next to material they did (SPEC-0006)."""
    assert client.get("/v1/notebooks").json() == []


def test_the_library_says_what_became_of_each_document(client, ingested, real_notes):
    """Served, not derived: the surface used to work this out by joining the
    Module list against a source's `module_id` (ADR-0009)."""
    notebook_id, _ = _with_a_document(client, ingested, real_notes)
    listed = client.get("/v1/notebooks").json()

    assert [n["notebook_id"] for n in listed] == [notebook_id]
    assert listed[0]["created_at"]
    assert listed[0]["sources"][0]["topic_count"] > 0
