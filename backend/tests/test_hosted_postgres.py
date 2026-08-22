"""Connecting to a Postgres somebody else runs.

Locally the database is a container that never moves, never suspends and takes
its connection string plain. A hosted one does none of those things, and every
assumption the plain case let us make is wrong somewhere else:

- the URL already carries query parameters,
- the compute suspends when idle, so pooled connections go stale,
- and the endpoint in front of it may be a transaction pooler that cannot keep
  a prepared statement straight.

Each test here corresponds to a way this failed, or would have.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import sqlalchemy as sa

from interviewer.db.engine import (
    GRAPH, connect_args_for, graph_dsn, is_pooled, make_engine,
)

NEON = (
    "postgresql+psycopg://u:pw@ep-cool-1-pooler.us-east-2.aws.neon.tech/cortex"
    "?sslmode=require&channel_binding=require"
)
DIRECT = "postgresql+psycopg://u:pw@ep-cool-1.us-east-2.aws.neon.tech/cortex?sslmode=require"
LOCAL = "postgresql+psycopg://cortex:cortex@127.0.0.1:55432/cortex"


def query_of(dsn: str) -> dict:
    return parse_qs(urlsplit(dsn).query)


# -- the bug that would have moved the checkpointer into `public` ------------

def test_the_search_path_survives_a_url_that_already_has_parameters():
    """It used to be concatenated on, and was swallowed by the value before it.

    The checkpointer then created its tables in `public` with no error, and
    `drop_graph` dropped nothing — ADR-0010's separation gone, silently.
    """
    dsn = graph_dsn(sa.create_engine(NEON))
    assert dsn.count("?") == 1
    assert query_of(dsn)["options"] == [f"-csearch_path={GRAPH}"]


def test_the_parameters_the_host_needs_are_not_lost_either():
    dsn = graph_dsn(sa.create_engine(NEON))
    assert query_of(dsn)["sslmode"] == ["require"]
    assert query_of(dsn)["channel_binding"] == ["require"]


def test_a_plain_local_url_still_gets_its_search_path():
    dsn = graph_dsn(sa.create_engine(LOCAL))
    assert query_of(dsn)["options"] == [f"-csearch_path={GRAPH}"]


def test_the_driver_prefix_is_dropped_for_the_checkpointer():
    """LangGraph takes a libpq string, not a SQLAlchemy one."""
    assert graph_dsn(sa.create_engine(NEON)).startswith("postgresql://")
    assert "+psycopg" not in graph_dsn(sa.create_engine(NEON))


# -- the checkpointer does not belong behind a transaction pooler ------------

def test_the_checkpointer_is_pointed_at_the_direct_endpoint():
    """It pipelines and prepares; a transaction pooler cannot keep that straight."""
    assert is_pooled(NEON) is True
    assert "-pooler" not in urlsplit(graph_dsn(sa.create_engine(NEON))).netloc


def test_an_explicit_graph_url_wins(monkeypatch):
    monkeypatch.setenv("GRAPH_DATABASE_URL", "postgresql://a:b@elsewhere/db")
    dsn = graph_dsn(sa.create_engine(NEON))
    assert "elsewhere" in dsn
    assert query_of(dsn)["options"] == [f"-csearch_path={GRAPH}"]


def test_a_direct_endpoint_is_left_alone():
    assert is_pooled(DIRECT) is False
    assert is_pooled(LOCAL) is False
    assert "ep-cool-1." in graph_dsn(sa.create_engine(DIRECT))


# -- a database that is allowed to go away ----------------------------------

def test_connections_are_checked_before_use():
    """A suspended compute wakes with every pooled connection already dead."""
    engine = make_engine(LOCAL)
    assert engine.pool._pre_ping is True


def test_pooled_endpoints_do_not_prepare_statements():
    """PgBouncer in transaction mode hands the next statement a different backend."""
    assert connect_args_for(NEON) == {"prepare_threshold": None}
    make_engine(NEON)  # and the Engine accepts them


def test_a_direct_endpoint_keeps_prepared_statements():
    """They are a real speed-up; giving them up everywhere would be a tax."""
    assert connect_args_for(DIRECT) == {}
    assert connect_args_for(LOCAL) == {}


def test_an_explicit_argument_is_never_overridden():
    engine = make_engine(LOCAL, pool_pre_ping=False)
    assert engine.pool._pre_ping is False
