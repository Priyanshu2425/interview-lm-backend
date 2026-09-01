"""Async database engine and session factory.

This module provides the async SQLAlchemy engine and session factory for all
API services. The sync engine (for LangGraph checkpointer) remains in
db/engine.py.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from interviewer.config import config


def make_async_engine(cfg: AsyncDBConfig | None = None) -> AsyncEngine:
    """Create an async engine, one connection per checkout, never reused.

    `NullPool` rather than a real pool: an asyncpg connection is bound to the
    event loop that opened it, and this module builds its engine exactly once
    at import time — before anything has decided which loop that will be. A
    pooled connection handed to a *different* loop later (a fresh loop per
    request, which is how the test client and some ASGI workers behave)
    doesn't raise; it hangs, silently, mid-query, holding whatever lock it
    already took. `NullPool` closes every connection the moment it's returned,
    so nothing outlives the loop that opened it and there is nothing to hand
    to the wrong one.

    Args:
        cfg: Optional config override. Uses global config if not provided.

    Returns:
        Configured AsyncEngine with no cross-request connection reuse.
    """
    cfg = cfg or config.async_db
    return create_async_engine(
        cfg.url,
        poolclass=NullPool,
    )


# Session factory - created once at module load
_async_engine = make_async_engine()
_AsyncSessionLocal = async_sessionmaker(
    bind=_async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


def get_async_engine() -> AsyncEngine:
    """Get the global async engine instance."""
    return _async_engine


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: provides an async database session per request.

    A bare async generator, deliberately. FastAPI drives a generator dependency
    itself — it steps the generator, hands the yielded value to the route, and
    resumes it once the response is done. Wrapping this in `@asynccontextmanager`
    hands FastAPI a context-manager *object* instead of a generator, and every
    route depending on it fails at dependency resolution with

        '_AsyncGeneratorContextManager' object is not an async iterator

    before a line of route code runs. Callers outside FastAPI that want
    `async with` use `async_db_context` below, which is this same generator with
    the decorator applied at the one place that needs it.

    Yields:
        AsyncSession that is closed on exit (success or exception).
    """
    async with _AsyncSessionLocal() as session:
        try:
            yield session
            # A route that wrote and never said so is a write that never
            # happened: nothing here commits on its behalf implicitly, and
            # nothing commits twice either — this is the one place that does,
            # once, after every route that reaches here without raising.
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


#: The same session, for callers that manage their own scope with `async with`.
#: FastAPI must not be given this one; see `get_async_db`.
async_db_context = asynccontextmanager(get_async_db)


async def create_async_tables() -> None:
    """Create all tables in the async engine, triggers included.

    Note: This is for tests only. Production uses create_core/create_content
    on the sync engine at startup.

    The triggers are not decoration. Until ISSUE-0039 this ran `create_all`
    alone, so a database built through the async path had the tables and none
    of the invariants — Evidence was quietly mutable, and a Session's scope
    quietly editable, in exactly the suite meant to prove they were not. There
    are four of them now and three are load-bearing, so the set is imported
    rather than restated: two places listing triggers by hand is how they came
    to disagree in the first place.
    """
    from sqlalchemy import text

    from interviewer.db.content import content_metadata
    from interviewer.db.schema import CORE, CORE_TRIGGERS, metadata, statements

    async with _async_engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {CORE}"))
        await conn.run_sync(metadata.create_all)
        await conn.run_sync(content_metadata.create_all)
        for trigger in CORE_TRIGGERS:
            # One command at a time: asyncpg prepares every statement and
            # rejects a blob containing several. See `schema.statements`.
            for statement in statements(trigger):
                await conn.execute(text(statement))