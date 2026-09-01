"""ISSUE-0023 — PDF and URL sources, and the stub Module.

Two source types people actually have, and the honest failure when they carry no
text. A scanned handout is the common case, not the edge case, and Coverage is
measured against the real notebook rather than the part that happened to parse.
"""

from __future__ import annotations

import pytest
from conftest import signed_in_client
from fastapi.testclient import TestClient

from interviewer.service.corpus.sources.notebook.documents.extract import (
    extract, extract_html, extract_pdf,
)
from pdf_fixtures import scanned_pdf, text_pdf

#: A page of a real handout carries a page of prose. These are long enough that
#: a chunk cannot span the whole document, which is what makes page attribution
#: observable at all.
PAGES = [
    "Attention scales scores by the square root of the key dimension before the "
    "softmax, which keeps the softmax in a region that still has a gradient. " * 12,
    "Bagging trains models on bootstrap resamples and averages them, which "
    "attacks variance and does nothing at all for bias. " * 12,
    "Boosting fits models in sequence on the errors of the last, which attacks "
    "bias and will overfit if it is left running. " * 12,
]

PAGE_HTML = """
<html><head><title>Notes</title><style>.a{color:red}</style></head>
<body>
  <nav><a href="/">Home</a><a href="/about">About</a></nav>
  <header>Site banner nobody is examined on</header>
  <article>
    <h1>Gradient descent</h1>
    <p>Gradient descent follows the negative gradient of the loss, and the
       learning rate decides how far each step goes.</p>
    <h2>Momentum</h2>
    <p>Momentum accumulates a velocity over past gradients, which damps
       oscillation across a ravine and speeds progress along it.</p>
  </article>
  <footer>Copyright notice nobody is examined on</footer>
  <script>document.write('invisible to the reader')</script>
</body></html>
"""


# -- extraction --------------------------------------------------------------


def test_a_text_pdf_extracts_with_real_page_numbers():
    extracted = extract_pdf(text_pdf(PAGES))
    assert "square root" in extracted.text
    assert [p.number for p in extracted.pages] == [1, 2, 3]
    for page in extracted.pages:
        assert extracted.page_of(page.char_start) == page.number


def test_a_pdf_locator_names_the_page_the_text_is_actually_on():
    extracted = extract_pdf(text_pdf(PAGES))
    where = extracted.text.index("Boosting")
    assert extracted.page_of(where) == 3


def test_a_scanned_pdf_is_a_stub_with_a_reason():
    extracted = extract_pdf(scanned_pdf())
    assert extracted.is_stub
    assert "no extractable text" in extracted.stub_reason


def test_a_file_that_is_not_a_pdf_is_a_stub_not_a_crash():
    extracted = extract_pdf(b"this is not a PDF at all")
    assert extracted.is_stub
    assert extracted.stub_reason


def test_a_page_extracts_its_prose_and_drops_its_chrome():
    extracted = extract_html(PAGE_HTML, url="https://example.com/notes")
    assert "Gradient descent follows" in extracted.text
    assert "Momentum accumulates" in extracted.text
    for chrome in ("Home", "About", "Site banner", "Copyright", "invisible"):
        assert chrome not in extracted.text


def test_a_page_keeps_its_headings_as_anchors():
    extracted = extract_html(PAGE_HTML)
    anchors = {p.anchor for p in extracted.pages}
    assert "Gradient descent" in anchors
    assert "Momentum" in anchors


def test_a_script_written_page_is_a_stub():
    extracted = extract_html(
        "<html><body><div id='root'></div>"
        "<script>render()</script></body></html>"
    )
    assert extracted.is_stub
    assert "script" in extracted.stub_reason


def test_one_door_for_every_source_type():
    assert extract(text="# Notes\n\nprose").text.startswith("# Notes")
    assert extract(data=text_pdf(PAGES), media_type="application/pdf").pages
    assert extract(text=PAGE_HTML, media_type="text/html").pages


# -- through the store -------------------------------------------------------


def test_a_pdf_becomes_a_module_whose_chunks_carry_page_numbers(notebooks):
    notebooks.create("nb-pdf", "cand-1", "Handouts")
    added = notebooks.add_source(
        "nb-pdf",
        source_id="s1",
        title="Lecture handout",
        data=text_pdf(PAGES * 8),
        media_type="application/pdf",
    )
    assert added.state == "ready"
    rows = notebooks.store.chunks_of("nb-pdf")
    assert rows
    assert {r["page"] for r in rows} != {1}, "every chunk claimed page 1"
    for row in rows:
        assert row["page"] >= 1


def test_a_scanned_pdf_makes_a_stub_module_and_spends_nothing(notebooks, counting):
    notebooks.create("nb-scan", "cand-1", "Scans")
    counting.calls.clear()
    added = notebooks.add_source(
        "nb-scan",
        source_id="s1",
        title="Scanned handout",
        data=scanned_pdf(),
        media_type="application/pdf",
    )
    assert added.state == "stub"
    assert "no extractable text" in added.stub_reason
    assert counting.calls == [], "a stub reached the embedder"
    assert notebooks.corpus("nb-scan") is None


def test_a_page_becomes_a_module(notebooks):
    notebooks.create("nb-web", "cand-1", "Reading")
    added = notebooks.add_source(
        "nb-web",
        source_id="s1",
        title="Optimisation notes",
        text=PAGE_HTML * 12,
        media_type="text/html",
        url="https://example.com/notes",
    )
    assert added.state == "ready"
    assert added.topics >= 1


def test_a_notebook_of_only_stubs_is_valid(notebooks):
    notebooks.create("nb-empty", "cand-1", "Only scans")
    notebooks.add_source(
        "nb-empty", source_id="s1", title="Scan one",
        data=scanned_pdf(), media_type="application/pdf",
    )
    notebooks.add_source(
        "nb-empty", source_id="s2", title="Scan two",
        data=scanned_pdf(2), media_type="application/pdf",
    )
    record = notebooks.store.get("nb-empty")
    assert [s.state for s in record.sources] == ["stub", "stub"]
    assert notebooks.corpus("nb-empty") is None


# -- on the surface ----------------------------------------------------------


@pytest.fixture()
def client(content_db, clean_db):
    from interviewer.app import create_app
    from interviewer.deps import refresh_corpus

    refresh_corpus()
    with signed_in_client() as c:
        yield c
    refresh_corpus()


def test_a_stub_module_is_listed_unselectable_and_unreachable(client):
    created = client.post(
        "/v1/notebooks", json={"candidate_id": "cand-s", "title": "Scans"}
    )
    notebook_id = created.json()["notebook_id"]
    added = client.post(
        f"/v1/notebooks/{notebook_id}/files",
        files={"file": ("scan.pdf", scanned_pdf(), "application/pdf")},
        data={"title": "Scanned handout"},
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["state"] == "stub"
    module_id = body["module_id"]

    listed = {
        m["module_id"]: m
        for m in client.get(
            "/v1/skills/modules", params={"candidate_id": "cand-s"}
        ).json()
    }
    assert module_id in listed, "a stub Module was hidden rather than shown"
    assert listed[module_id]["selectable"] is False
    assert listed[module_id]["stub_reason"]
    assert listed[module_id]["topic_count"] == 0

    refused = client.post(
        "/v1/sessions",
        json={
            "candidate_id": "cand-s",
            "module_ids": [module_id],
            "duration_seconds": 600,
        },
    )
    assert refused.status_code == 422
    assert "no examinable Topic" in refused.text


def test_a_pdf_uploaded_through_the_surface_is_examinable(client, ingested):
    created = client.post(
        "/v1/notebooks", json={"candidate_id": "cand-p", "title": "Handouts"}
    )
    notebook_id = created.json()["notebook_id"]
    added = client.post(
        f"/v1/notebooks/{notebook_id}/files",
        files={"file": ("handout.pdf", text_pdf(PAGES * 8), "application/pdf")},
        data={"title": "Lecture handout"},
    )
    assert added.status_code == 201, added.text
    # The upload answers at once and the embedding runs behind it (ISSUE-0035).
    assert added.json()["state"] == "uploaded"
    assert ingested(client, notebook_id)["state"] == "ready"

    module_id = added.json()["module_id"]
    started = client.post(
        "/v1/sessions",
        json={
            "candidate_id": "cand-p",
            "module_ids": [module_id],
            "duration_seconds": 600,
        },
    )
    assert started.status_code == 201, started.text
    assert started.json()["question"].strip()
