"""ADR-0017 — a figure is a chunk that happens to be a picture.

Two claims are under test, and the second matters more than the first.

The figure lane works: pictures come out of a PDF, land in the same table and
the same 768-dimensional space as the prose around them, and are stored once
however often they repeat.

And the figure lane stays subordinate: text draws every Topic boundary, and a
figure joins one without ever moving it. The shared space makes attaching by
similarity *possible*, which is exactly why the refusal needs a test rather
than a comment.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from interviewer.adapters.internal.notebook import Chunk, Figure, as_chunks, attach
from interviewer.db.content import notebook_chunk
from pdf_fixtures import image_pdf, text_pdf

PAGES = [
    "Attention weights every token against every other token. " * 12,
    "Backpropagation applies the chain rule backwards through the graph. " * 12,
]


@pytest.fixture()
def deck():
    return image_pdf(PAGES, figures_per_page=1)


def rows(engine, modality: str) -> list[dict]:
    with engine.begin() as c:
        return [
            dict(r) for r in c.execute(
                sa.select(notebook_chunk)
                .where(notebook_chunk.c.modality == modality)
                .order_by(notebook_chunk.c.chunk_id)
            ).mappings()
        ]


# -- attachment is arithmetic ------------------------------------------------

def chunk(cid: str, page: int, start: int, topic: str) -> Chunk:
    return Chunk(cid, "s1", page, start, start + 10, "body", f"h{cid}", topic_id=topic)


def test_a_figure_joins_a_topic_that_text_already_drew():
    chunks = [chunk("c1", 1, 0, "t1"), chunk("c2", 2, 10, "t2")]
    assert attach([Figure(2, 0, b"x", 99, 99)], chunks) == ["t2"]


def test_a_figure_on_a_wordless_page_falls_back_to_the_nearest_prose():
    """A slide whose only words are its title still cites the passage before it."""
    chunks = [chunk("c1", 1, 0, "t1"), chunk("c2", 9, 10, "t9")]
    assert attach([Figure(7, 0, b"x", 99, 99)], chunks) == ["t9"]
    assert attach([Figure(2, 0, b"x", 99, 99)], chunks) == ["t1"]


def test_a_tie_between_pages_resolves_to_the_earlier_one():
    chunks = [chunk("c1", 1, 0, "t1"), chunk("c2", 3, 10, "t3")]
    assert attach([Figure(2, 0, b"x", 99, 99)], chunks) == ["t1"]


def test_a_source_with_no_prose_at_all_attaches_nothing():
    """There is no Topic to join, and a figure may not mint one (ADR-0015)."""
    assert attach([Figure(1, 0, b"x", 99, 99)], []) == [None]


def test_an_unattached_figure_becomes_no_row_at_all():
    figures = [Figure(7, 0, b"x", 99, 99)]
    assert as_chunks(
        figures, [None], source_id="s1", notebook_id="nb",
        object_key_for=lambda n, h: "k",
    ) == []


def test_attachment_is_deterministic():
    chunks = [chunk("c1", 1, 0, "t1"), chunk("c2", 1, 10, "t2")]
    figures = [Figure(1, 0, b"a", 99, 99), Figure(1, 1, b"b", 99, 99)]
    assert attach(figures, chunks) == attach(figures, chunks) == ["t1", "t2"]


def test_a_figure_never_mints_a_topic_id():
    chunks = [chunk("c1", 1, 0, "t1")]
    produced = as_chunks(
        [Figure(1, 0, b"x", 99, 99)], attach([Figure(1, 0, b"x", 99, 99)], chunks),
        source_id="s1", notebook_id="nb", object_key_for=lambda n, h: "k",
    )
    assert {c.topic_id for c in produced} <= {c.topic_id for c in chunks}


def test_the_same_picture_twice_is_one_object_key():
    figures = [Figure(1, 0, b"same", 99, 99), Figure(2, 0, b"same", 99, 99)]
    produced = as_chunks(
        figures, ["t1", "t1"], source_id="s1", notebook_id="nb",
        object_key_for=lambda n, h: f"notebooks/{n}/figures/{h}.png",
    )
    assert produced[0].object_key == produced[1].object_key


# -- the lane, end to end ----------------------------------------------------

def test_a_pdf_with_figures_stores_them_beside_its_prose(illustrated, deck, objects):
    illustrated.create("nb-1", "cand-1", "Lecture deck")
    added = illustrated.add_source(
        "nb-1", source_id="s1", title="Deck", data=deck,
        media_type="application/pdf",
    )
    assert added.figures == 2
    assert added.chunks >= 1
    stored = rows(illustrated.store._engine, "image")
    assert len(stored) == 2
    # The bytes are in the store, and the row points at them.
    for row in stored:
        assert objects.get(row["object_key"])


def test_every_stored_figure_belongs_to_a_topic_text_drew(illustrated, deck):
    illustrated.create("nb-1", "cand-1", "Lecture deck")
    illustrated.add_source(
        "nb-1", source_id="s1", title="Deck", data=deck,
        media_type="application/pdf",
    )
    text_topics = {r["topic_id"] for r in rows(illustrated.store._engine, "text")}
    for row in rows(illustrated.store._engine, "image"):
        assert row["topic_id"] in text_topics


def test_figures_share_the_column_and_the_width_of_the_prose(illustrated, deck):
    illustrated.create("nb-1", "cand-1", "Lecture deck")
    illustrated.add_source(
        "nb-1", source_id="s1", title="Deck", data=deck,
        media_type="application/pdf",
    )
    widths = {
        len(r["embedding"])
        for modality in ("text", "image")
        for r in rows(illustrated.store._engine, modality)
    }
    assert widths == {768}


def test_the_database_refuses_a_text_row_carrying_an_object_key(
    illustrated, content_db
):
    """The invariant is the database's, so no code path can forget it."""
    illustrated.create("nb-1", "cand-1", "Notes")
    illustrated.add_source("nb-1", source_id="s1", title="N", text="Some notes. " * 60)
    with pytest.raises(sa.exc.IntegrityError):
        with content_db.begin() as c:
            c.execute(
                sa.update(notebook_chunk)
                .where(notebook_chunk.c.modality == "text")
                .values(object_key="notebooks/nb-1/figures/x.png")
            )


def test_the_database_refuses_an_image_row_with_nowhere_to_fetch_its_bytes(
    illustrated, deck, content_db
):
    illustrated.create("nb-1", "cand-1", "Lecture deck")
    illustrated.add_source(
        "nb-1", source_id="s1", title="Deck", data=deck,
        media_type="application/pdf",
    )
    with pytest.raises(sa.exc.IntegrityError):
        with content_db.begin() as c:
            c.execute(
                sa.update(notebook_chunk)
                .where(notebook_chunk.c.modality == "image")
                .values(object_key=None)
            )


def test_images_off_ingests_the_text_and_says_nothing_about_pictures(
    notebooks, deck
):
    notebooks.create("nb-1", "cand-1", "Lecture deck")
    added = notebooks.add_source(
        "nb-1", source_id="s1", title="Deck", data=deck,
        media_type="application/pdf",
    )
    assert added.figures == 0
    assert added.chunks >= 1
    assert rows(notebooks.store._engine, "image") == []


def test_a_source_with_no_figures_is_unaffected(illustrated):
    illustrated.create("nb-1", "cand-1", "Notes")
    added = illustrated.add_source(
        "nb-1", source_id="s1", title="N", text="Plain markdown notes. " * 80
    )
    assert added.figures == 0


def test_a_text_pdf_carrying_no_images_yields_no_figures(illustrated):
    illustrated.create("nb-1", "cand-1", "Paper")
    added = illustrated.add_source(
        "nb-1", source_id="s1", title="Paper", data=text_pdf(PAGES),
        media_type="application/pdf",
    )
    assert added.figures == 0
    assert added.topics >= 1
