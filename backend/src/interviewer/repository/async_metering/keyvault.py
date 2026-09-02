"""BYOK keys, for the async routes.

A delegate, not a second vault. Attaching a key validates it with the provider,
generates a data key, wraps it with the KMS and revokes whatever was active —
and none of that is something to hold two copies of. The earlier async version
reimplemented the table without the cryptography, which left `attach` missing
and `resolver` returning a fingerprint where a key belonged.

`KeyVault` is synchronous and talks to a synchronous engine, so the work runs in
a worker thread rather than on the event loop. `routes/v1/notebooks.py` reaches
`wiring().vault` the same way and for the same reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import anyio.to_thread
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from ...service.metering.keyvault_service import AttachedKey


class AsyncKeyVault:
    """The one `KeyVault`, awaited."""

    __slots__ = ()

    def __init__(self, session: AsyncSession | None = None) -> None:
        # The session is accepted and ignored: this reads and writes through
        # `wiring().vault`'s own engine, and taking one here keeps the
        # dependency shaped like every other in `deps_async`.
        pass

    @staticmethod
    def _vault():
        from ...wiring import wiring

        return wiring().vault

    async def attach(self, candidate_id: str, key: str) -> "AttachedKey":
        """Validate, wrap and store. Raises `RejectedKey` as the sync one does."""
        return await anyio.to_thread.run_sync(
            lambda: self._vault().attach(candidate_id, key)
        )

    async def active(self, candidate_id: str) -> "AttachedKey | None":
        """Metadata only. This is what an API boundary may see."""
        return await anyio.to_thread.run_sync(
            lambda: self._vault().active(candidate_id)
        )

    async def revoke(self, candidate_id: str, key_id: str) -> bool:
        """Whether a key of *this* Candidate's matched."""
        return await anyio.to_thread.run_sync(
            lambda: self._vault().revoke(candidate_id, key_id)
        )

    async def resolver(self, candidate_id: str) -> str | None:
        """The decrypted key, for a call about to be made with it."""
        return await anyio.to_thread.run_sync(
            lambda: self._vault().resolver()(candidate_id)
        )
