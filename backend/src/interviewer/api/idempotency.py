"""Idempotency for mutating requests (SPEC-0000 §4).

A retried turn returns the original result rather than submitting twice — the
mechanism ADR-0011 chose a request for in the first place.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

_lock = threading.Lock()
_seen: dict[str, Any] = {}


def once(key: str, fn: Callable[[], Any]) -> Any:
    with _lock:
        if key in _seen:
            return _seen[key]
    result = fn()
    with _lock:
        _seen.setdefault(key, result)
        return _seen[key]


def reset() -> None:
    with _lock:
        _seen.clear()
