"""Identifiers for rows we create.

Here rather than in a store because three stores and a transcript mint them,
and a helper that lives in one of them makes the other three import a
repository to write their own rows.
"""

from __future__ import annotations

import uuid

__all__ = ["new_id"]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:22]}"
