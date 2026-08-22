"""Embeddings through OpenRouter — the route ADR-0008 already chose.

When ADR-0008 said "OpenRouter is the only route" and ADR-0016 recorded the BYOK
gap, OpenRouter served chat completions and nothing else. It now serves
embeddings too, at `/api/v1/embeddings`, which quietly dissolves the problem
ADR-0016 was written about: a Candidate's own key can embed after all. See
ADR-0019.

Practical consequence for this file: the platform key is `OPENROUTER_API_KEY` —
the same key the Interviewer already grades with — so a deployment configures
one credential rather than two, and every provider call still passes through one
chokepoint where it can be metered (SPEC-0005).
"""

from __future__ import annotations

from typing import ClassVar, Sequence

from .base import normalise
from .errors import EmbeddingContractError
from .http import HttpEmbedder
from .registry import register

#: What OpenRouter charges, in US dollars per million tokens, for the models
#: worth naming here. Used only to report what an ingest cost — the authority is
#: the provider's own ledger, and ADR-0014 requires we compute our own number
#: rather than trust a figure we did not derive.
PRICES = {
    "google/gemini-embedding-2-preview": 0.20,
    "google/gemini-embedding-2": 0.20,
    "google/gemini-embedding-001": 0.15,
    "openai/text-embedding-3-small": 0.02,
    "openai/text-embedding-3-large": 0.13,
}


@register("openrouter")
class OpenRouterEmbedder(HttpEmbedder):
    """One gateway, one key, one place a call can be counted."""

    default_model: ClassVar[str] = "google/gemini-embedding-2-preview"
    supports_images: ClassVar[bool] = False

    def __init__(self, *, truncate: bool = True, **kw) -> None:
        kw.setdefault("endpoint", "https://openrouter.ai/api/v1")
        super().__init__(**kw)
        # Gemini's embedding models are Matryoshka-trained: the first N
        # dimensions of a longer vector are a usable embedding on their own,
        # provided the result is re-normalised. That is what makes a 3072-wide
        # model storable in a 768-wide column without a migration.
        self.truncate = truncate

    @classmethod
    def options_from(cls, env: dict) -> dict:
        return {
            "endpoint": env.get("EMBEDDING_ENDPOINT") or "https://openrouter.ai/api/v1",
            # The key the Interviewer already grades with. ADR-0008: one route.
            "api_key": (
                env.get("EMBEDDING_API_KEY")
                or env.get("OPENROUTER_API_KEY")
                or ""
            ),
            "truncate": (env.get("EMBEDDING_TRUNCATE") or "1") == "1",
        }

    @property
    def dollars_per_million(self) -> float:
        return PRICES.get(self.model, 0.0)

    def _post(self, batch: Sequence[str]) -> list[Sequence[float]]:
        """The wire call, named so a test can stand in front of it."""
        return HttpEmbedder._encode_texts(self, batch)

    def _encode_texts(self, batch: Sequence[str]) -> list[Sequence[float]]:
        vectors = self._post(batch)
        if not vectors:
            return vectors

        width = len(vectors[0])
        if width == self.dim:
            return vectors
        if width < self.dim:
            raise EmbeddingContractError(
                f"{self.model} returned {width} dimensions and the store holds "
                f"{self.dim}; a narrower vector cannot be widened",
                provider=self.provider, model=self.model,
            )
        if not self.truncate:
            raise EmbeddingContractError(
                f"{self.model} returned {width} dimensions, the store holds "
                f"{self.dim}, and EMBEDDING_TRUNCATE is off",
                provider=self.provider, model=self.model,
            )
        # Matryoshka truncation. Re-normalised because a prefix of a unit vector
        # is not one, and every similarity in this system is a dot product that
        # assumes it is.
        return [normalise(list(vector[: self.dim])) for vector in vectors]
