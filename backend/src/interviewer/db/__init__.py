"""Database package exports."""

from .engine import (
    create_core,
    create_content,
    create_graph,
    drop_graph,
    graph_dsn,
    make_engine,
    dsn,
    with_driver,
    is_pooled,
    connect_args_for,
    DimensionMismatch,
    CORE,
    GRAPH,
)

from .engine_async import (
    make_async_engine,
    get_async_engine,
    get_async_db,
    async_db_context,
    create_async_tables,
)

__all__ = [
    # Sync (LangGraph checkpointer)
    "create_core",
    "create_content",
    "create_graph",
    "drop_graph",
    "graph_dsn",
    "make_engine",
    "dsn",
    "with_driver",
    "is_pooled",
    "connect_args_for",
    "DimensionMismatch",
    "CORE",
    "GRAPH",
    # Async (API services)
    "make_async_engine",
    "get_async_engine",
    "get_async_db",
    "async_db_context",
    "create_async_tables",
]