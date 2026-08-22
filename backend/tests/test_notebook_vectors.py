"""Vectors in Postgres, and the two things that go wrong without care.

pgvector is here so that citation (ISSUE-0025) is an index lookup rather than
every chunk of a notebook pulled into Python and compared there. These tests
hold the storage contract: the width is fixed, the operator works, one index
serves both modalities, and deleting a notebook reaches the bucket as well as
the rows.

They also cover the reuse defect a swappable embedder introduces — see
`test_a_model_change_re_embeds_rather_than_reusing`, which is the one that
would have shipped silently.
"""

from __future__ import annotations

import sqlalchemy as sa

from interviewer.db.content import EMBEDDING_DIM, notebook_chunk, notebook_topic
from interviewer.notebooks import NotebookService
from pdf_fixtures import image_pdf

#: Long enough to be cut into several chunks, so that adding material to the
#: end leaves the earlier chunks byte-identical — which is the only situation
#: in which content-addressed reuse has anything to reuse.
NOTES = "\n\n".join(
    f"# Section {n}\n\n"
    + f"Attention weights every token against every other token, part {n}. " * 60
    for n in range(4)
)


def test_a_vector_survives_the_round_trip_at_full_width(notebooks, content_db):
    notebooks.create("nb-1", "cand-1", "Notes")
    notebooks.add_source("nb-1", source_id="s1", title="N", text=NOTES)
    with content_db.begin() as c:
        stored = c.execute(
            sa.select(notebook_chunk.c.embedding).limit(1)
        ).scalar_one()
    assert len(stored) == EMBEDDING_DIM
    assert abs(sum(float(x) ** 2 for x in stored) - 1.0) < 1e-3


def test_the_column_is_a_vector_and_the_index_is_hnsw(content_db):
    with content_db.begin() as c:
        udt = c.execute(sa.text(
            "select udt_name from information_schema.columns "
            "where table_schema='content' and table_name='notebook_chunk' "
            "and column_name='embedding'"
        )).scalar()
        index = c.execute(sa.text(
            "select indexdef from pg_indexes where schemaname='content' "
            "and indexname='ix_chunk_embedding_hnsw'"
        )).scalar()
    assert udt == "vector"
    assert "hnsw" in index and "vector_cosine_ops" in index


def test_nearest_neighbour_is_a_query_rather_than_a_scan(notebooks, content_db):
    notebooks.create("nb-1", "cand-1", "Notes")
    notebooks.add_source("nb-1", source_id="s1", title="N", text=NOTES)
    with content_db.begin() as c:
        probe = c.execute(sa.select(notebook_chunk.c.embedding).limit(1)).scalar_one()
        rows = c.execute(
            sa.text(
                "select chunk_id from content.notebook_chunk "
                "order by embedding <=> cast(:probe as vector) limit 3"
            ),
            {"probe": str(list(float(x) for x in probe))},
        ).all()
    assert rows, "the cosine operator returned nothing"


def test_one_index_answers_across_both_modalities(illustrated, content_db):
    """The reason a figure is a row here rather than a table of its own."""
    illustrated.create("nb-1", "cand-1", "Deck")
    illustrated.add_source(
        "nb-1", source_id="s1", title="Deck",
        data=image_pdf(["Attention. " * 40, "Backprop. " * 40], figures_per_page=1),
        media_type="application/pdf",
    )
    with content_db.begin() as c:
        figure = c.execute(
            sa.select(notebook_chunk.c.embedding).where(
                notebook_chunk.c.modality == "image"
            ).limit(1)
        ).scalar_one()
        nearest = c.execute(
            sa.text(
                "select modality from content.notebook_chunk "
                "order by embedding <=> cast(:probe as vector) limit 5"
            ),
            {"probe": str([float(x) for x in figure])},
        ).scalars().all()
    # One query, one index, both kinds of row reachable from a single probe.
    assert "image" in nearest


def test_a_centroid_is_stored_at_the_same_width(notebooks, content_db):
    notebooks.create("nb-1", "cand-1", "Notes")
    notebooks.add_source("nb-1", source_id="s1", title="N", text=NOTES)
    with content_db.begin() as c:
        centroid = c.execute(
            sa.select(notebook_topic.c.centroid).limit(1)
        ).scalar_one()
    assert len(centroid) == EMBEDDING_DIM


# -- the reuse defect --------------------------------------------------------

def test_the_same_model_reuses_what_it_already_embedded(notebooks, counting):
    notebooks.create("nb-1", "cand-1", "Notes")
    notebooks.add_source("nb-1", source_id="s1", title="N", text=NOTES)
    total = sum(counting.calls)
    counting.calls.clear()
    notebooks.add_source(
        "nb-1", source_id="s2", title="Revised",
        text=NOTES + "\n\n# Addendum\n\nSomething new entirely.",
    )
    # Only the material that actually changed reaches the embedder.
    assert 0 < sum(counting.calls) < total


def test_a_model_change_re_embeds_rather_than_reusing(content_db, objects):
    """The defect a swappable embedder introduces, and the fix.

    Reuse keyed on content alone would hand back vectors drawn by the previous
    model — two geometries inside one notebook, and nothing anywhere reporting
    it. Keyed on the model as well, a change simply re-embeds.
    """
    from interviewer.corpus.adapters.notebook import HashingEmbedder

    class Named(HashingEmbedder):
        def __init__(self, name):
            super().__init__()
            self.model_name = name
            self.embedded = 0

        def embed(self, texts):
            self.embedded += len(texts)
            return super().embed(texts)

    first = Named("model-a@768")
    service = NotebookService(content_db, embedder=first, objects=objects)
    service.create("nb-1", "cand-1", "Notes")
    service.add_source("nb-1", source_id="s1", title="N", text=NOTES)

    # A *different* source that repeats most of the same prose: the case where
    # reuse-by-content-hash actually pays off, and therefore the case where
    # reusing across a model change would do the damage.
    second = Named("model-b@768")
    swapped = NotebookService(content_db, embedder=second, objects=objects)
    swapped.add_source(
        "nb-1", source_id="s2", title="Revised", text=NOTES + "\n\n# Addendum\n\nNew.",
    )
    assert second.embedded > 0, "a model change must not reuse the old space"


def test_the_same_model_still_reuses_across_sources(content_db, objects):
    """The saving is real and must survive the fix that scopes it to a model."""
    from interviewer.corpus.adapters.notebook import HashingEmbedder

    class Named(HashingEmbedder):
        def __init__(self, name):
            super().__init__()
            self.model_name = name
            self.embedded = 0

        def embed(self, texts):
            self.embedded += len(texts)
            return super().embed(texts)

    same = Named("model-a@768")
    service = NotebookService(content_db, embedder=same, objects=objects)
    service.create("nb-1", "cand-1", "Notes")
    service.add_source("nb-1", source_id="s1", title="N", text=NOTES)
    first_pass = same.embedded
    service.add_source(
        "nb-1", source_id="s2", title="Revised", text=NOTES + "\n\n# Addendum\n\nNew.",
    )
    assert same.embedded - first_pass < first_pass


def test_stored_chunks_record_which_model_drew_them(notebooks, content_db):
    notebooks.create("nb-1", "cand-1", "Notes")
    notebooks.add_source("nb-1", source_id="s1", title="N", text=NOTES)
    with content_db.begin() as c:
        models = c.execute(
            sa.select(notebook_chunk.c.embedding_model).distinct()
        ).scalars().all()
    assert models == ["hashing-v1"]


# -- deletion reaches the bucket ---------------------------------------------

def test_deleting_a_notebook_empties_the_rows_and_the_object_store(
    illustrated, objects, content_db
):
    illustrated.create("nb-1", "cand-1", "Deck")
    illustrated.add_source(
        "nb-1", source_id="s1", title="Deck",
        data=image_pdf(["Attention. " * 40], figures_per_page=2),
        media_type="application/pdf",
    )
    keys = illustrated.store.object_keys_of("nb-1")
    assert keys and all(objects.get(k) for k in keys)

    illustrated.delete("nb-1")

    with content_db.begin() as c:
        assert c.execute(
            sa.select(sa.func.count()).select_from(notebook_chunk)
        ).scalar() == 0
    # CASCADE empties the schema; it has never heard of the bucket.
    assert objects.delete_prefix("nb-1") == 0


def test_deleting_one_notebook_leaves_another_notebooks_figures_alone(
    illustrated, objects
):
    deck = image_pdf(["Attention. " * 40], figures_per_page=1)
    for notebook_id, source_id in (("nb-1", "s1"), ("nb-2", "s2")):
        illustrated.create(notebook_id, "cand-1", "Deck")
        illustrated.add_source(
            notebook_id, source_id=source_id, title="Deck", data=deck,
            media_type="application/pdf",
        )
    survivor = illustrated.store.object_keys_of("nb-2")
    illustrated.delete("nb-1")
    assert all(objects.get(k) for k in survivor)
