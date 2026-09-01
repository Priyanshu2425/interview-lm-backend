"""Everything non-deterministic is injected, never called.

PRD-0003 makes replay a requirement rather than a nicety: it is the only way to
know whether grading is any good. So randomness, the clock and model responses
all arrive through these ports, and nothing in `graph/` reaches for them
directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class Clock(Protocol):
    def now(self) -> float:
        """Seconds, monotonic enough for a duration check."""


class SystemClock:
    def now(self) -> float:
        import time

        return time.time()


@dataclass
class FrozenClock:
    """A clock a test drives by hand."""

    t: float = 0.0

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@dataclass(frozen=True, slots=True)
class ModelReply:
    text: str
    call_id: str | None = None
    provider: str | None = None
    model_id: str | None = None


@runtime_checkable
class ModelClient(Protocol):
    """The single chokepoint. Every model call in the system goes through one of
    these, carrying the topic_visit_id it belongs to (SPEC-0005 I1)."""

    def complete(
        self,
        *,
        topic_visit_id: str,
        role: str,
        system: str,
        user: str,
        max_tokens: int = 800,
    ) -> ModelReply: ...


@dataclass
class ScriptedModel:
    """A deterministic stand-in. Replies are keyed by role, consumed in order.

    Used by tests and by replay. Records every call it received so a test can
    assert on what the Judge was *given* rather than on prompt text.
    """

    replies: dict[str, list[str]] = field(default_factory=dict)
    default: str = "ok"
    calls: list[dict] = field(default_factory=list)

    def complete(
        self, *, topic_visit_id: str, role: str, system: str, user: str,
        max_tokens: int = 800,
    ) -> ModelReply:
        if not topic_visit_id:
            raise ValueError("a model call must carry a topic_visit_id")
        self.calls.append(
            {
                "topic_visit_id": topic_visit_id,
                "role": role,
                "system": system,
                "user": user,
            }
        )
        queue = self.replies.get(role)
        text = queue.pop(0) if queue else self.default
        return ModelReply(text=text, call_id=f"call_{len(self.calls)}",
                          provider="deepseek", model_id="scripted")


@dataclass(frozen=True, slots=True)
class Ports:
    """The injected world. A Session replays exactly when these do."""

    clock: Clock
    rng: np.random.Generator
    model: ModelClient

    @staticmethod
    def deterministic(seed: int = 0, model: ModelClient | None = None) -> "Ports":
        return Ports(
            clock=FrozenClock(),
            rng=np.random.default_rng(seed),
            model=model or ScriptedModel(),
        )
