"""The `content` schema — a Corpus the Candidate brought, and can take away.

ADR-0010 put two schemas with opposite lifecycles in one Postgres. This is the
third, and it is the most disposable of them:

  graph/    checkpoints. Disposable outside the resumption window.
  core/     everything permanent. Evidence lives here and never leaves.
  content/  notebook material. The Candidate's, and deleted when they say so.

The split is the point. Deleting a notebook empties `content` and touches
nothing in `core`, which is how a Topic can retire while the Evidence it
produced stays readable (ISSUE-0027).
"""

from __future__ import annotations

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint, Column, ForeignKey, Index, Integer, MetaData, String,
    Table, Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP

CONTENT = "interview_lm_content"

#: One space for both modalities. SigLIP 2 embeds a paragraph and a diagram into
#: the same 768 dimensions, which is what lets a figure be a row in the chunk
#: table rather than a table of its own — one column, one index, one query that
#: can answer "what is this passage about" across prose and pictures alike.
#: Changing it is a re-embed (ADR-0017), never an in-place edit.
EMBEDDING_DIM = 768

content_metadata = MetaData(schema=CONTENT)


def _ts(name: str, **kw) -> Column:
    return Column(name, TIMESTAMP(timezone=True), **kw)


#: A Corpus is owned by the platform or by a Candidate, and `candidate_id`
#: carries the owner either way. This is the id a platform-owned one is written
#: under — a sentinel for a NOT NULL column, and never the rule itself: every
#: guard reads `visibility`, so a Candidate who happens to be called `platform`
#: owns a personal Corpus like anybody else (SPEC-0006 §Ownership).
PLATFORM_OWNER = "platform"

#: personal — a Candidate's own uploads: theirs, private, deletable, and never
#: compared to anyone, because their cohort is one by construction.
#: shared — imported once by an operator, read-only to every Candidate, and the
#: same `topic_id`s for all of them. That last part is the whole reason it
#: exists: Topic Confidence is keyed on `topic_id`.
PERSONAL = "personal"
SHARED = "shared"

notebook = Table(
    "notebook", content_metadata,
    Column("notebook_id", String, primary_key=True),
    Column("candidate_id", String, nullable=False),
    Column("title", String, nullable=False),
    # Personal is the default, so a deployment that never creates a shared
    # Corpus behaves exactly as it did before this column existed.
    Column("visibility", String, nullable=False, server_default=PERSONAL),
    # Discovery only, not deletion. A shared Corpus taken off active duty
    # disappears from module listings and new-Session scoping, but a Topic it
    # already produced Evidence for stays fully readable — the same "Evidence
    # stays" boundary ISSUE-0027 already draws for a deleted notebook.
    Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
    # Recorded, not assumed: a change of model re-embeds, and Topic membership
    # is carried across rather than recomputed (ISSUE-0022).
    Column("embedding_model", String, nullable=False),
    # Which extract this Library is, as JSON, where it came from one. PRD-0001
    # §13 requires a Session to be able to say what it ran against, and after
    # ISSUE-0037 the answer cannot come from a file's header — so an import
    # carries its source's provenance across rather than replacing it with the
    # adapter that happened to load it. Empty for a Candidate's own upload,
    # which *is* the notebook adapter's own extract.
    Column("provenance", Text, nullable=False, server_default="{}"),
    _ts("created_at", nullable=False, server_default=sa.func.now()),
    CheckConstraint(
        f"visibility IN ('{PERSONAL}','{SHARED}')", name="ck_notebook_visibility"
    ),
)

notebook_source = Table(
    "notebook_source", content_metadata,
    Column("source_id", String, primary_key=True),
    Column("notebook_id", String,
           ForeignKey(f"{CONTENT}.notebook.notebook_id", ondelete="CASCADE"),
           nullable=False),
    Column("module_id", String, nullable=False),
    Column("title", String, nullable=False),
    Column("media_type", String, nullable=False, server_default="text/markdown"),
    Column("source_order", Integer, nullable=False),
    Column("text", Text, nullable=False, server_default=""),
    Column("content_hash", String, nullable=False),
    # uploaded | ingesting | ready | failed | stub.
    #
    # `stub` is a Module that exists, is visible, and states why it carries
    # nothing (ISSUE-0023). The other four are the ingest lifecycle: a Source
    # exists as soon as its bytes do, so `uploaded` is a document in the Library
    # that has not been embedded yet (ISSUE-0035). A Module still appears only
    # at `ready`, so there is no partial Module and no orphan Topic.
    Column("state", String, nullable=False, server_default="ready"),
    Column("stub_reason", String, nullable=True),
    # Work done against work found — never an indeterminate spinner, because
    # forty seconds of spinner is indistinguishable from a hang. The total is
    # known at upload: chunking is local and costs nothing, so the count is a
    # measurement before the first provider call rather than after it.
    # Where each region of the extracted text came from, as JSON, so a citation
    # can name a page after the upload and the ingest have been separated
    # (ISSUE-0035). Extraction produces these and nothing carries a locator
    # across a process boundary, so they are written with the row rather than
    # rediscovered — a deployment with no object store keeps its page numbers.
    Column("pages", Text, nullable=False, server_default="[]"),
    Column("progress_done", Integer, nullable=False, server_default="0"),
    Column("progress_total", Integer, nullable=False, server_default="0"),
    _ts("started_at", nullable=True),
    # When progress last moved. A worker that stalls inside a live process
    # cannot be detected by a timeout we invented, so this is reported and the
    # judgement is left to whoever is reading it.
    _ts("progress_at", nullable=True),
    # Where the bytes that arrived still are (ISSUE-0033). `text` is what one
    # extractor made of them and is a cache; this is the document. Nullable
    # because a Source ingested before this column existed has no object, and
    # that is a different state from an object that has gone missing.
    Column("object_key", String, nullable=True),
    Column("byte_length", Integer, nullable=False, server_default="0"),
    # derived | given. Derived is the existing path: a Candidate's file arrives
    # with no divisions and the clusterer mints them. Given is a structured
    # import — the source already drew its Topics, and re-deriving them would
    # produce different ids meaning something different by every one
    # (SPEC-0006 §Structure is given, or derived).
    Column("structure", String, nullable=False, server_default="derived"),
    # Which Track this Module belongs to, where the source drew one. A
    # Candidate's upload has no Tracks and gets the notebook's own key; an
    # import keeps the divisions it arrived with, and a Track is one of them
    # (ISSUE-0034, ISSUE-0037).
    Column("track_key", String, nullable=False, server_default=""),
    Column("track_title", String, nullable=False, server_default=""),
    _ts("created_at", nullable=False, server_default=sa.func.now()),
    CheckConstraint(
        "structure IN ('derived','given')", name="ck_source_structure"
    ),
)

notebook_topic = Table(
    "notebook_topic", content_metadata,
    Column("topic_id", String, primary_key=True),
    Column("notebook_id", String,
           ForeignKey(f"{CONTENT}.notebook.notebook_id", ondelete="CASCADE"),
           nullable=False),
    Column("source_id", String,
           ForeignKey(f"{CONTENT}.notebook_source.source_id", ondelete="CASCADE"),
           nullable=False),
    Column("module_id", String, nullable=False),
    Column("title", String, nullable=False),
    Column("topic_order", Integer, nullable=False),
    # Stored, never recomputed. A centroid that drifts with every upload is a
    # Topic boundary that moves without saying so (ADR-0015).
    Column("centroid", Vector(EMBEDDING_DIM), nullable=False),
    Column("chunk_hashes", ARRAY(String), nullable=False),
    Column("dossier_tokens", Integer, nullable=False, server_default="0"),
)

notebook_chunk = Table(
    "notebook_chunk", content_metadata,
    Column("chunk_id", String, primary_key=True),
    Column("notebook_id", String,
           ForeignKey(f"{CONTENT}.notebook.notebook_id", ondelete="CASCADE"),
           nullable=False),
    Column("source_id", String,
           ForeignKey(f"{CONTENT}.notebook_source.source_id", ondelete="CASCADE"),
           nullable=False),
    Column("topic_id", String, nullable=False),
    # The locator. This is what a citation points at, and the reason chunks
    # exist at all (ADR-0015).
    Column("page", Integer, nullable=False, server_default="1"),
    Column("char_start", Integer, nullable=False),
    Column("char_end", Integer, nullable=False),
    Column("anchor", String, nullable=False, server_default=""),
    Column("text", Text, nullable=False),
    Column("content_hash", String, nullable=False),
    Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    # Which model drew this vector. Without it, reuse-by-content-hash hands back
    # a vector from a space the notebook has since left (ISSUE-0026).
    Column("embedding_model", String, nullable=False, server_default=""),
    # text | image. A figure is a chunk that happens to be a picture: same
    # locator, same Topic, same space (ADR-0017). What differs is where the
    # payload lives — prose in `text`, pixels behind `object_key`.
    Column("modality", String, nullable=False, server_default="text"),
    Column("object_key", String, nullable=True),
    # What mining found this span to be: content, prompt, or the worked answer
    # to a prompt in the same Topic (ISSUE-0024). Stored rather than re-derived,
    # so reading a notebook back never re-runs a classifier over it.
    Column("leaf_kind", String, nullable=False, server_default="content"),
    Column("answers_chunk_id", String, nullable=True),
    CheckConstraint(
        "modality IN ('text','image')", name="ck_chunk_modality"
    ),
    # The invariant is the database's, not a convention: an image chunk is
    # exactly the one that has somewhere to fetch its bytes from.
    CheckConstraint(
        "(modality = 'image') = (object_key IS NOT NULL)",
        name="ck_chunk_payload_matches_modality",
    ),
)

Index("ix_chunk_topic", notebook_chunk.c.topic_id)
Index("ix_chunk_hash", notebook_chunk.c.notebook_id, notebook_chunk.c.content_hash)
Index("ix_source_notebook", notebook_source.c.notebook_id)
Index("ix_topic_notebook", notebook_topic.c.notebook_id)
Index(
    "ix_chunk_figure_page",
    notebook_chunk.c.notebook_id,
    notebook_chunk.c.page,
    postgresql_where=notebook_chunk.c.modality == "image",
)
