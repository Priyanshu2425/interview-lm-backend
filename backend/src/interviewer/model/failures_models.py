"""The Failure Classifier — pure, and the honesty rule made structural.

Two failures look alike and must never be confused. A BYOK Candidate spends no
Credits, so telling them their Credits ran out sends them to fix something that
is not broken.

`route` is a required input and there is **no code path from a BYOK Session to a
Credit-flavoured event**. Enforcing that in a message template is how it
eventually leaks.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Route(str, Enum):
    CREDITS = "credits"
    BYOK = "byok"
    MCP = "mcp"


class Cause(str, Enum):
    BALANCE_EXHAUSTED = "balance_exhausted"
    BALANCE_EXHAUSTED_MID_VISIT = "balance_exhausted_mid_visit"
    KEY_REVOKED = "key_revoked"
    KEY_UNFUNDED = "key_unfunded"
    KEY_RATE_LIMITED = "key_rate_limited"
    KEY_INVALID = "key_invalid"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    PLATFORM_KEY_MISSING = "platform_key_missing"


class Event(str, Enum):
    CREDITS_EXHAUSTED = "CREDITS_EXHAUSTED"
    CREDITS_EXHAUSTED_MID_VISIT = "CREDITS_EXHAUSTED_MID_VISIT"
    BYOK_KEY_REVOKED = "BYOK_KEY_REVOKED"
    BYOK_KEY_UNFUNDED = "BYOK_KEY_UNFUNDED"
    BYOK_KEY_RATE_LIMITED = "BYOK_KEY_RATE_LIMITED"
    BYOK_KEY_INVALID = "BYOK_KEY_INVALID"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PLATFORM_KEY_MISSING = "PLATFORM_KEY_MISSING"


CREDIT_EVENTS = frozenset(
    {Event.CREDITS_EXHAUSTED, Event.CREDITS_EXHAUSTED_MID_VISIT}
)


@dataclass(frozen=True, slots=True)
class UserFacingEvent:
    code: Event
    message: str
    route: Route
    recoverable: bool
    provider: str | None = None

    @classmethod
    def of(
        cls, *, route: Route, cause: Cause, provider: str | None = None
    ) -> "UserFacingEvent":
        p = provider or "your provider"

        if route is Route.CREDITS:
            if cause is Cause.BALANCE_EXHAUSTED:
                return cls(
                    Event.CREDITS_EXHAUSTED,
                    "Your Credits have run out. Top up and this Session picks up "
                    "exactly where it stopped.",
                    route, True,
                )
            if cause is Cause.PLATFORM_KEY_MISSING:
                # Ours, not theirs. Only the Credits route can reach this: BYOK
                # supplies a key per call and an MCP host holds its own. Blaming a
                # Candidate's key for our missing one sends them to fix something
                # that is not broken — the failure this module exists to prevent.
                return cls(
                    Event.PLATFORM_KEY_MISSING,
                    "This deployment has no provider key configured, so the Session "
                    "cannot run on Credits. Attach your own OpenRouter key and start "
                    "a new Session.",
                    route, False, provider,
                )
            if cause is Cause.BALANCE_EXHAUSTED_MID_VISIT:
                # Reports a completed Visit and a negative balance — the opposite of
                # what an engineer would write by reflex.
                return cls(
                    Event.CREDITS_EXHAUSTED_MID_VISIT,
                    "Your Credits ran out part-way through that Topic, so we let it "
                    "finish rather than cutting it off. Your balance is negative; "
                    "top up to carry on.",
                    route, True,
                )

        if route is Route.BYOK:
            # There is deliberately no branch here that can reach a Credit event.
            key_events = {
                Cause.KEY_REVOKED: (
                    Event.BYOK_KEY_REVOKED,
                    f"{p} refused your key — it has been revoked at OpenRouter.",
                ),
                Cause.KEY_UNFUNDED: (
                    Event.BYOK_KEY_UNFUNDED,
                    f"{p} refused your key — its balance at OpenRouter is empty. "
                    f"Add funds there, or switch this Session to another provider.",
                ),
                Cause.KEY_RATE_LIMITED: (
                    Event.BYOK_KEY_RATE_LIMITED,
                    f"{p} is rate-limiting your key. Wait a moment and resume.",
                ),
                Cause.KEY_INVALID: (
                    Event.BYOK_KEY_INVALID,
                    "That key was refused by OpenRouter. Check it and try again.",
                ),
            }
            if cause in key_events:
                code, msg = key_events[cause]
                return cls(code, msg, route, True, provider)

        if cause is Cause.PROVIDER_UNAVAILABLE:
            return cls(
                Event.PROVIDER_UNAVAILABLE,
                f"{p} is unavailable right now. The Session is parked; the next "
                f"Topic will run on whichever provider is live.",
                route, True, provider,
            )
        if cause is Cause.PROVIDER_TIMEOUT:
            return cls(
                Event.PROVIDER_TIMEOUT,
                f"{p} did not respond in time. The Session is parked and nothing "
                f"was lost.",
                route, True, provider,
            )

        raise ValueError(f"cause {cause} is not classifiable on route {route}")
