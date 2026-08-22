"""Concrete embedding providers, and the machinery they share.

The port they satisfy lives in `corpus/adapters/notebook/embedding.py`. Nothing
in `corpus/` may import this package — it opens sockets and loads models, and
the Corpus is source material rather than the system (ADR-0007). `api/deps.py`
is where the two are joined.
"""

from .base import BaseEmbedder, normalise
from .errors import (
    EmbeddingContractError,
    EmbeddingError,
    EmbeddingTimeout,
    EmbeddingUnavailable,
    PaidProviderRefused,
    UnsupportedModality,
)
from .registry import images_enabled, make_embedder, register, registered

__all__ = [
    "BaseEmbedder", "EmbeddingContractError", "EmbeddingError",
    "EmbeddingTimeout", "EmbeddingUnavailable", "PaidProviderRefused",
    "UnsupportedModality", "images_enabled", "make_embedder", "normalise",
    "register", "registered",
]
