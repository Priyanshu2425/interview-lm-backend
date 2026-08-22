"""Content addressing, in one place.

A chunk is keyed by the hash of its text, and that key decides whether it is
re-embedded, whether it is re-billed, and — through `topic_id_for` — what a
Notebook Topic is called. Two implementations of this function that disagree by
a byte would silently re-mint every id in the system, so there is one.
"""

from __future__ import annotations

import hashlib


def digest(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()
