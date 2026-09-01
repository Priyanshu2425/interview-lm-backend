"""OpenRouter transport, and a scripted stand-in.

ADR-0008: OpenRouter is the only route. No vendor SDKs — one route, or the
metering chokepoint is a fiction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import httpx

from .client import ProviderFailure, ProviderResponse

MODELS = {
    "deepseek": "deepseek/deepseek-chat",
    "gemini": "google/gemini-2.0-flash-001",
    "claude": "anthropic/claude-3.5-sonnet",
}


class OpenRouterTransport:
    def __init__(self, platform_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        self._key = platform_key
        self._base = base_url

    def send(self, *, provider, api_key, system, user, max_tokens) -> ProviderResponse:
        model = MODELS[provider]
        key = api_key or self._key
        if not key:
            # An empty Bearer is not a network failure and must not be reported
            # as one: httpx would raise a transport error and we would tell the
            # Candidate the Provider is down.
            raise ProviderFailure("platform_key_missing", provider)
        try:
            r = httpx.post(
                f"{self._base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "usage": {"include": True},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=90.0,
            )
        except httpx.TimeoutException as e:
            raise ProviderFailure("provider_timeout", provider) from e
        except httpx.HTTPError as e:
            raise ProviderFailure("provider_unavailable", provider) from e

        if r.status_code == 401:
            raise ProviderFailure("key_revoked", provider)
        if r.status_code == 402:
            raise ProviderFailure("key_unfunded", provider)
        if r.status_code == 429:
            raise ProviderFailure("key_rate_limited", provider)
        if r.status_code >= 500:
            raise ProviderFailure("provider_unavailable", provider)
        r.raise_for_status()

        body = r.json()
        usage = body.get("usage") or {}
        cost = usage.get("cost")
        return ProviderResponse(
            text=body["choices"][0]["message"]["content"],
            model_id=body.get("model", model),
            # A cost the provider did not report is None — unpriced, never zero.
            cost_usd=Decimal(str(cost)) if cost is not None else None,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )


@dataclass
class ScriptedTransport:
    """Deterministic. Cost is supplied, so metering is testable without network."""

    replies: dict[str, list[str]] = field(default_factory=dict)
    default: str = "SCORE: 0.8\nWHY: fine."
    cost_usd: Decimal | None = Decimal("0.06")
    fail_with: str | None = None
    sent: list[dict] = field(default_factory=list)

    def send(self, *, provider, api_key, system, user, max_tokens) -> ProviderResponse:
        self.sent.append({"provider": provider, "api_key": api_key,
                          "system": system, "user": user})
        if self.fail_with:
            raise ProviderFailure(self.fail_with, provider)
        return ProviderResponse(
            text=self.default, model_id=f"{provider}/scripted",
            cost_usd=self.cost_usd, prompt_tokens=100, completion_tokens=50,
        )
