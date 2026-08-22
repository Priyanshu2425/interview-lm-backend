"""ISSUE-0028 — a deck with no words, and what this product says about it.

ADR-0024 decided: pictures alone are not examinable, and no caption model is
introduced to pretend otherwise. What follows from that decision is small and is
tested here — the refusal is about the **material** rather than about a parser,
so the document says what it actually holds.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def service(content_db, seeing, tmp_path):
    from interviewer.embeddings.artifacts import LocalObjectStore
    from interviewer.notebooks import NotebookService

    svc = NotebookService(
        content_db, embedder=seeing, objects=LocalObjectStore(tmp_path), images=True
    )
    svc.create("nb-deck", "cand-deck", "Slides")
    return svc


def test_a_deck_of_pictures_says_how_many_pictures_it_holds(service):
    """"No extractable text" describes the parser. This describes the file."""
    from pdf_fixtures import image_pdf

    added = service.add_source(
        "nb-deck", source_id="src-1", title="Lecture slides.pdf",
        data=image_pdf(["", ""], figures_per_page=2),
        media_type="application/pdf",
    )
    assert added.state == "stub"
    reason = service.store.get("nb-deck").sources[0].stub_reason
    assert "figure" in reason
    assert "not examinable" in reason


def test_it_says_the_document_is_kept(service):
    """Because it is (ISSUE-0033), and because ADR-0024 may be revisited."""
    from pdf_fixtures import image_pdf

    service.add_source(
        "nb-deck", source_id="src-1", title="Slides.pdf",
        data=image_pdf(["", ""], figures_per_page=1),
        media_type="application/pdf",
    )
    source = service.store.get("nb-deck").sources[0]
    assert "kept" in (source.stub_reason or "")
    assert source.object_key, "the bytes have to actually be there"


def test_a_scan_with_no_figures_keeps_the_plain_reason(service):
    """Nothing invented: a file with neither text nor pictures says so."""
    from pdf_fixtures import scanned_pdf

    service.add_source(
        "nb-deck", source_id="src-1", title="Scan.pdf",
        data=scanned_pdf(), media_type="application/pdf",
    )
    reason = service.store.get("nb-deck").sources[0].stub_reason
    assert "no extractable text" in reason
    assert "figure" not in reason


def test_no_topic_is_minted_from_pictures(service):
    """ADR-0024's first two questions, answered by absence.

    A figure-only Topic would be a Topic with no prose to ask about and no span
    to grade against. None is created, so neither question arises at runtime.
    """
    from pdf_fixtures import image_pdf

    service.add_source(
        "nb-deck", source_id="src-1", title="Slides.pdf",
        data=image_pdf(["", ""], figures_per_page=2),
        media_type="application/pdf",
    )
    assert service.store.frozen_topics("nb-deck") == {}
    assert service.corpus("nb-deck") is None


def test_counting_figures_costs_no_provider_call(content_db, counting, tmp_path):
    """A stub reaches no embedder at all, and that did not change."""
    from interviewer.embeddings.artifacts import LocalObjectStore
    from interviewer.notebooks import NotebookService
    from pdf_fixtures import image_pdf

    svc = NotebookService(
        content_db, embedder=counting, objects=LocalObjectStore(tmp_path)
    )
    svc.create("nb-cost", "cand-cost", "Slides")
    counting.calls.clear()
    added = svc.add_source(
        "nb-cost", source_id="src-1", title="Slides.pdf",
        data=image_pdf(["", ""], figures_per_page=1),
        media_type="application/pdf",
    )
    assert added.state == "stub"
    assert counting.calls == []


def test_a_broken_file_still_stubs_rather_than_failing(service):
    """Counting is an addition, and an addition must not take the product down."""
    added = service.add_source(
        "nb-deck", source_id="src-1", title="Broken.pdf",
        data=b"%PDF-1.4 this is not really a pdf",
        media_type="application/pdf",
    )
    assert added.state == "stub"
    assert service.store.get("nb-deck").sources[0].stub_reason
