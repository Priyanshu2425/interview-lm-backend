"""Evidence has one writer and one shape, whichever engine is asking.

The routes run on an async engine and the graph on a sync one, and for a while
each had its own hand-written copy of the Evidence table's reads and writes.
The copies drifted: the async one never learned `write_topic`, and never
learned the two dimensions the Judge has read since ISSUE-0043 — so a Session
graded through it would have reported `null` for both, permanently, in the one
record that is not allowed to be rebuilt.

These tests hold the two halves of the fix: nothing but the ledger writes, and
both engines project the same row.
"""

import asyncio

from conftest import grade_session

from interviewer.repository.async_core.evidence import AsyncEvidenceLedger
from interviewer.service.graph.runner_service import SessionRunner
from interviewer.service.graph.sessions import SessionConfig

CANDIDATE = "cand_one_ledger"


def _graded_session(deps) -> str:
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:1]
    r = SessionRunner(deps)
    sid, out = r.start(
        candidate_id=CANDIDATE,
        cfg=SessionConfig(scope_module_ids=tuple(mods), duration_seconds=1800),
    )
    for _ in range(30):
        if out.kind == "session_ended":
            break
        out = r.submit(sid, "an answer worth grading")
    grade_session(deps, sid)
    return sid


def test_the_async_ledger_cannot_write_evidence():
    """One writer, and it is the one holding the transaction.

    Not a style rule. `write` is idempotent on a Topic Visit and `write_topic`
    on a Session's Topic, and both bump a posterior in the same transaction as
    the insert. A second writer reachable from a request is a second chance to
    get that wrong on a record that is append-only at the database.
    """
    for forbidden in ("write", "write_topic", "_bump_posterior"):
        assert not hasattr(AsyncEvidenceLedger, forbidden), (
            f"AsyncEvidenceLedger.{forbidden} is a second writer of Evidence"
        )


def test_both_engines_read_the_same_evidence_row(deps, clean_db):
    """The projection is shared, so neither engine can fall behind the other.

    `source_score` and `truth_score` are named explicitly: they are exactly
    what the async copy was missing while it had reads of its own.
    """
    sid = _graded_session(deps)
    sync_rows = deps.evidence.for_session(sid)
    assert sync_rows, "the Session wrote no Evidence to compare"

    async def read_async():
        from interviewer.db.engine_async import async_db_context

        async with async_db_context() as s:
            return await AsyncEvidenceLedger(s).for_session(sid)

    async_rows = asyncio.run(read_async())

    assert [r["evidence_id"] for r in async_rows] == [
        r["evidence_id"] for r in sync_rows
    ]
    for sync_row, async_row in zip(sync_rows, async_rows):
        assert set(sync_row) == set(async_row)
        assert async_row["source_score"] == sync_row["source_score"]
        assert async_row["truth_score"] == sync_row["truth_score"]


def test_the_dead_sync_to_async_bridge_is_gone():
    """217 lines re-declaring the whole repository surface, with no callers and
    names that had drifted past the Visit lifecycle they claimed to drive."""
    import importlib

    try:
        importlib.import_module("interviewer.service.graph.async_adapters")
    except ModuleNotFoundError:
        return
    raise AssertionError("async_adapters is back, and still nothing calls it")
