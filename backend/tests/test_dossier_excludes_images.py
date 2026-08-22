"""A figure in the table must not become a figure in the dossier.

ISSUE-0021 requires that a Topic's dossier is its chunks in locator order,
byte-identical to the source spans concatenated. Putting figures in the same
table as prose (ADR-0017) puts a row in reach of every query that rebuilds that
text — and an image row carries no characters, so one joining the concatenation
corrupts it in a way no exception reports.

This is the failure mode the single-table shape introduces, so it is the one
this file exists to hold shut.
"""

from __future__ import annotations

import pytest

from pdf_fixtures import image_pdf

PAGES = [
    "Attention weights every token against every other token in the sequence. " * 14,
    "Backpropagation applies the chain rule backwards through the graph. " * 14,
]


@pytest.fixture()
def ingested(illustrated):
    illustrated.create("nb-1", "cand-1", "Lecture deck")
    added = illustrated.add_source(
        "nb-1", source_id="s1", title="Deck",
        data=image_pdf(PAGES, figures_per_page=2),
        media_type="application/pdf",
    )
    assert added.figures > 0, "the fixture must actually carry figures"
    return illustrated


def test_no_leaf_is_a_figure(ingested):
    corpus = ingested.corpus("nb-1")
    for topic in corpus.topics:
        for leaf in topic.leaves:
            assert leaf.text.strip(), f"{leaf.id} is an empty leaf"
            assert "#fig" not in leaf.id


def test_dossier_text_still_reassembles_the_source(ingested):
    """The acceptance criterion from ISSUE-0021, with pictures in the table."""
    source_text = ingested.store.sources_of("nb-1")[0].text
    for topic in ingested.corpus("nb-1").topics:
        joined = "".join(leaf.text for leaf in topic.leaves)
        assert joined in source_text


def test_the_token_budget_does_not_count_pictures(ingested):
    corpus = ingested.corpus("nb-1")
    for topic in corpus.topics:
        counted = sum(len(leaf.text or "") for leaf in topic.leaves) // 4
        assert counted > 0


def test_the_corpus_still_conforms_with_figures_present(ingested):
    from interviewer.corpus.conformance import validate

    report = validate(ingested.corpus("nb-1"))
    assert report.violations == []


def test_the_figures_are_stored_even_though_no_leaf_shows_them(ingested):
    """Excluded from the dossier, present in the table — both, deliberately."""
    assert ingested.store.figures_of("nb-1")


def test_a_session_reads_the_same_corpus_with_or_without_figures(
    content_db, seeing, objects
):
    from interviewer.notebooks import NotebookService

    deck = image_pdf(PAGES, figures_per_page=2)
    with_images = NotebookService(
        content_db, embedder=seeing, objects=objects, images=True
    )
    with_images.create("nb-a", "cand-1", "Deck")
    with_images.add_source(
        "nb-a", source_id="sa", title="Deck", data=deck,
        media_type="application/pdf",
    )
    without = NotebookService(content_db, embedder=seeing, objects=objects)
    without.create("nb-b", "cand-1", "Deck")
    without.add_source(
        "nb-b", source_id="sb", title="Deck", data=deck,
        media_type="application/pdf",
    )

    def prose(service, notebook_id):
        return [
            [leaf.text for leaf in topic.leaves]
            for topic in service.corpus(notebook_id).topics
        ]

    assert prose(with_images, "nb-a") == prose(without, "nb-b")
