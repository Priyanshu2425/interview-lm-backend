"""Reading Evidence from the routes' engine.

There is one writer of an Evidence row and it is `EvidenceLedger`, on the
graph's synchronous engine. This reads; it does not write, and the absence is
the point rather than an omission waiting to be filled in.

A second write path existed here until it was removed. It was never called —
grading runs in the graph, in `/end` and on the resumption path, all of them
through the one ledger — and it had already fallen behind the writer it
copied: no `write_topic`, no `source_score`, no `truth_score`, and a read-then-
insert where the ledger holds a transaction. Evidence is permanent, so a
second way to write it is a second way to write it wrong.

The projections are shared with the sync ledger (`db.evidence_reads`) so the
two engines cannot disagree about the shape of a row.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...db.evidence_reads import for_session_stmt, rejudgeable_stmt, rows_for_stmt


class AsyncEvidenceLedger:
    """Evidence, read on the routes' engine. Read-only by construction."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def rejudgeable(
        self, *, limit: int = 500, mode: str | None = None
    ) -> list[dict[str, Any]]:
        result = await self._s.execute(rejudgeable_stmt(limit=limit, mode=mode))
        return [dict(r._mapping) for r in result.all()]

    async def for_session(self, session_id: str) -> list[dict[str, Any]]:
        result = await self._s.execute(for_session_stmt(session_id))
        return [dict(r._mapping) for r in result.all()]

    async def rows_for(self, candidate_id: str) -> list[dict[str, Any]]:
        result = await self._s.execute(rows_for_stmt(candidate_id))
        return [dict(r._mapping) for r in result.all()]
