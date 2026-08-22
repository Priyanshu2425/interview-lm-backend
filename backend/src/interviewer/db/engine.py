"""Engine and migration entry points.

Two schemas, two owners (ADR-0010):
  core   — ours. `create_core` is the only thing that may write its DDL.
  graph  — LangGraph's. Its own `setup()` owns it, which is why there is no
           migration of ours that could reach `core` by accident.
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .content import CONTENT, EMBEDDING_DIM, content_metadata
from .schema import (
    APPEND_ONLY_EVIDENCE_TRIGGER,
    CORE,
    GRAPH,
    IMMUTABLE_SESSION_FIELDS_TRIGGER,
    metadata,
)

DEFAULT_DSN = "postgresql+psycopg://cortex:cortex@127.0.0.1:55432/cortex"


def dsn() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DSN)


def make_engine(url: str | None = None, **kw) -> Engine:
    return sa.create_engine(url or dsn(), future=True, **kw)


def create_core(engine: Engine) -> None:
    """Apply the `core` tree. Never touches `graph`."""
    with engine.begin() as c:
        c.execute(text(f"CREATE SCHEMA IF NOT EXISTS {CORE}"))
    metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(text(IMMUTABLE_SESSION_FIELDS_TRIGGER))
        c.execute(text(APPEND_ONLY_EVIDENCE_TRIGGER))


def create_content(engine: Engine) -> None:
    """Apply the `content` tree — notebook material, deletable by its owner.

    Separate from `create_core` on purpose: the two have opposite lifecycles,
    and nothing that drops content may be able to reach Evidence.

    There is no alembic in this project, so the widening of the vector columns
    happens here, in the same place and the same style as `create_core`'s
    triggers: idempotent DDL applied on every boot, guarded so that running it
    against an already-migrated database is a no-op.
    """
    with engine.begin() as c:
        c.execute(text(f"CREATE SCHEMA IF NOT EXISTS {CONTENT}"))
        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    content_metadata.create_all(engine)
    # `create_all` builds what is missing and alters nothing that exists, so a
    # database from before ADR-0017 needs the rest applied by hand.
    _migrate_vector_columns(engine)
    _migrate_added_columns(engine)
    _migrate_constraints(engine)
    _create_vector_indexes(engine)


#: Columns that were `double precision[]` before ADR-0017 and are `vector(n)`
#: after it. Table, column, and whether a null is allowed while backfilling.
_VECTOR_COLUMNS = (
    ("notebook_chunk", "embedding"),
    ("notebook_topic", "centroid"),
)


class DimensionMismatch(RuntimeError):
    """Stored vectors are not the width the running model produces.

    Refused rather than cast: a column holding two vector spaces is a Topic
    boundary that cannot be trusted, and the failure would surface much later as
    inexplicable clustering. `NotebookService.re_embed` is the way across.
    """


def _migrate_vector_columns(engine: Engine) -> None:
    """`double precision[]` -> `vector(n)`, once, in place.

    A row already stored at another width cannot be cast and must not be
    silently dropped — the Candidate's material is not ours to discard. The
    migration refuses and names the notebooks that have to be re-embedded or
    deleted first.
    """
    with engine.begin() as c:
        for table, column in _VECTOR_COLUMNS:
            udt = c.execute(
                text(
                    "SELECT udt_name FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = :t "
                    "AND column_name = :c"
                ),
                {"s": CONTENT, "t": table, "c": column},
            ).scalar()
            if udt is None or udt == "vector":
                continue
            widths = c.execute(
                text(
                    f"SELECT DISTINCT array_length({column}, 1) "  # noqa: S608
                    f"FROM {CONTENT}.{table} WHERE {column} IS NOT NULL"
                )
            ).scalars().all()
            wrong = sorted(w for w in widths if w and w != EMBEDDING_DIM)
            if wrong:
                raise DimensionMismatch(
                    f"{CONTENT}.{table}.{column} holds vectors of width "
                    f"{wrong}, and this deployment embeds at {EMBEDDING_DIM}. "
                    "Re-embed the affected notebooks (NotebookService.re_embed) "
                    "or delete them before starting."
                )
            c.execute(
                text(
                    f"ALTER TABLE {CONTENT}.{table} "
                    f"ALTER COLUMN {column} TYPE vector({EMBEDDING_DIM}) "
                    f"USING {column}::vector({EMBEDDING_DIM})"
                )
            )


#: Columns added to `notebook_chunk` after the table first shipped. Each is
#: nullable or defaulted, so adding one to a populated table rewrites nothing.
_ADDED_COLUMNS = (
    ("notebook_chunk", "embedding_model", "text NOT NULL DEFAULT ''"),
    ("notebook_chunk", "modality", "text NOT NULL DEFAULT 'text'"),
    ("notebook_chunk", "object_key", "text"),
)


def _migrate_added_columns(engine: Engine) -> None:
    with engine.begin() as c:
        for table, column, spec in _ADDED_COLUMNS:
            c.execute(
                text(
                    f"ALTER TABLE {CONTENT}.{table} "
                    f"ADD COLUMN IF NOT EXISTS {column} {spec}"
                )
            )
        # A chunk stored before the column existed was embedded by whatever the
        # notebook records. Backfilling from there keeps reuse honest rather
        # than leaving every old chunk looking like it came from nowhere.
        c.execute(
            text(
                f"UPDATE {CONTENT}.notebook_chunk ch "
                f"SET embedding_model = nb.embedding_model "
                f"FROM {CONTENT}.notebook nb "
                f"WHERE ch.notebook_id = nb.notebook_id AND ch.embedding_model = ''"
            )
        )


#: The invariants that outlive any one code path. Named, so re-applying them is
#: a lookup rather than an exception.
_CONSTRAINTS = (
    ("notebook_chunk", "ck_chunk_modality", "CHECK (modality IN ('text','image'))"),
    (
        "notebook_chunk",
        "ck_chunk_payload_matches_modality",
        "CHECK ((modality = 'image') = (object_key IS NOT NULL))",
    ),
)


def _migrate_constraints(engine: Engine) -> None:
    with engine.begin() as c:
        for table, name, body in _CONSTRAINTS:
            exists = c.execute(
                text(
                    "SELECT 1 FROM pg_constraint co "
                    "JOIN pg_class cl ON cl.oid = co.conrelid "
                    "JOIN pg_namespace n ON n.oid = cl.relnamespace "
                    "WHERE n.nspname = :s AND cl.relname = :t AND co.conname = :c"
                ),
                {"s": CONTENT, "t": table, "c": name},
            ).scalar()
            if exists:
                continue
            c.execute(
                text(f"ALTER TABLE {CONTENT}.{table} ADD CONSTRAINT {name} {body}")
            )


def _create_vector_indexes(engine: Engine) -> None:
    """One HNSW index, over both modalities, because they share a space.

    Built outside `create_all` because SQLAlchemy has no vocabulary for the
    operator class, and raised `maintenance_work_mem` because the default turns
    an index build into a disk sort.
    """
    with engine.begin() as c:
        c.execute(text("SET LOCAL maintenance_work_mem = '256MB'"))
        c.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS ix_chunk_embedding_hnsw "
                f"ON {CONTENT}.notebook_chunk "
                f"USING hnsw (embedding vector_cosine_ops)"
            )
        )
        c.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS ix_chunk_figure_page "
                f"ON {CONTENT}.notebook_chunk (notebook_id, page) "
                f"WHERE modality = 'image'"
            )
        )


def create_graph(engine: Engine) -> None:
    """Apply the `graph` tree — the checkpointer's own setup."""
    from langgraph.checkpoint.postgres import PostgresSaver

    raw = engine.url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    with engine.begin() as c:
        c.execute(text(f"CREATE SCHEMA IF NOT EXISTS {GRAPH}"))
    with PostgresSaver.from_conn_string(raw + "?options=-csearch_path%3D" + GRAPH) as s:
        s.setup()


def drop_graph(engine: Engine) -> None:
    """Discard checkpoints outside the resumption window. `core` is untouched —
    this is the operation ADR-0010's migration test exercises."""
    with engine.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {GRAPH} CASCADE"))
        c.execute(text(f"CREATE SCHEMA {GRAPH}"))
