"""The commercial swap: anything speaking the OpenAI embeddings wire format.

One class covers OpenAI, Azure OpenAI, Voyage-compatible gateways, and a
self-hosted text-embeddings-inference or vLLM server, because they all answer
`POST /v1/embeddings` with `{"data": [{"index": i, "embedding": [...]}]}`.

This is the only module in the package that opens a socket, which is why
`test_architecture.py` names it specifically rather than widening its rule.
"""

from __future__ import annotations

from typing import ClassVar, Sequence

import httpx

from .base import BaseEmbedder
from .errors import EmbeddingContractError, EmbeddingTimeout, EmbeddingUnavailable
from .registry import register


@register("http")
class HttpEmbedder(BaseEmbedder):
    """Text only. An image tower over this wire format is not a standard."""

    default_model: ClassVar[str] = "text-embedding-3-small"
    supports_images: ClassVar[bool] = False

    def __init__(self, *, endpoint: str = "", api_key: str = "", **kw) -> None:
        super().__init__(**kw)
        self.endpoint = (endpoint or "https://api.openai.com/v1").rstrip("/")
        self._api_key = api_key
        self._client: httpx.Client | None = None

    @classmethod
    def options_from(cls, env: dict) -> dict:
        return {
            "endpoint": env.get("EMBEDDING_ENDPOINT") or "",
            "api_key": env.get("EMBEDDING_API_KEY") or "",
        }

    def warm(self) -> None:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        super().warm()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        super().close()

    def _encode_texts(self, batch: Sequence[str]) -> list[Sequence[float]]:
        self.warm()
        assert self._client is not None
        payload = {"model": self.model, "input": list(batch)}
        # Providers that support Matryoshka truncation are asked for our width
        # directly, which is cheaper and better than truncating client-side.
        payload["dimensions"] = self.dim
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        try:
            response = self._client.post(
                f"{self.endpoint}/embeddings", json=payload, headers=headers
            )
        except httpx.TimeoutException as exc:
            raise EmbeddingTimeout(
                f"{self.endpoint} did not answer within {self.timeout}s",
                provider=self.provider, model=self.model,
            ) from exc
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailable(
                f"{self.endpoint} unreachable: {exc}",
                provider=self.provider, model=self.model,
            ) from exc

        # 429 and 5xx are about this moment; a 400 is about the request and will
        # fail identically on every retry.
        if response.status_code == 429 or response.status_code >= 500:
            raise EmbeddingTimeout(
                f"{self.endpoint} returned {response.status_code}",
                provider=self.provider, model=self.model,
            )
        if response.status_code >= 400:
            raise EmbeddingUnavailable(
                f"{self.endpoint} returned {response.status_code}: "
                f"{response.text[:200]}",
                provider=self.provider, model=self.model,
            )

        body = response.json()
        rows = body.get("data")
        if not isinstance(rows, list):
            raise EmbeddingContractError(
                f"{self.endpoint} returned no data array",
                provider=self.provider, model=self.model,
            )
        # Sorted by index rather than trusted in arrival order: the base class
        # zips these against the input positionally.
        rows = sorted(rows, key=lambda r: r.get("index", 0))
        return [r["embedding"] for r in rows]
