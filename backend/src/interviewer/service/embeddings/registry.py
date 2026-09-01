"""Which embedder this deployment runs, and how a new one joins.

`@register("name")` is the whole extension point. A new provider is a module, a
decorator and an entry in the import list below — no call site changes, because
nothing outside this package names a provider class.

Selection is by explicit flag, never by inference. `INTERVIEWER_FAKE_MODEL`
already set that precedent for the chat provider: serving stand-in vectors
because a key happened to be missing is a decision, and decisions are taken in
the open.
"""

from __future__ import annotations

import os
from typing import Callable, Type

from interviewer.adapters.internal.embedding import DIM, HashingEmbedder

from .base import BaseEmbedder
from .errors import PaidProviderRefused

_REGISTRY: dict[str, Type[BaseEmbedder]] = {}


def register(name: str) -> Callable[[Type[BaseEmbedder]], Type[BaseEmbedder]]:
    def decorate(cls: Type[BaseEmbedder]) -> Type[BaseEmbedder]:
        cls.provider = name
        _REGISTRY[name] = cls
        return cls
    return decorate


def registered() -> list[str]:
    _load()
    return sorted(["hashing", *_REGISTRY])


def _load() -> None:
    """Import the provider modules so their decorators run.

    Deliberately inside a function: importing `siglip` at module scope would
    make every process that touches the registry pay for the import, and the
    whole point of the lazy loading below is that it does not.
    """
    from . import http, openrouter, siglip  # noqa: F401


def make_embedder(env: dict | None = None) -> object:
    """The configured embedder, or the stub. Never a silent fallback."""
    env = os.environ if env is None else env
    name = (env.get("EMBEDDING_PROVIDER") or "hashing").strip()
    dim = int(env.get("EMBEDDING_DIM") or DIM)

    if name == "hashing":
        # The stand-in. Zero dependencies, so the test suite never loads a model.
        return HashingEmbedder(dim=dim)

    _load()
    if name not in _REGISTRY:
        raise ValueError(
            f"unknown EMBEDDING_PROVIDER {name!r}; registered: {registered()}"
        )

    cls = _REGISTRY[name]
    credits = float(env.get("EMBEDDING_CREDITS_PER_1K") or 0.0)
    if credits > 0 and (env.get("EMBEDDING_ALLOW_PAID") or "") != "1":
        raise PaidProviderRefused(
            f"{name} would bill {credits} Credits per 1k tokens, and who pays "
            "for a BYOK Candidate's ingest is undecided (ADR-0016, proposed). "
            "Set EMBEDDING_ALLOW_PAID=1 once that ADR is signed.",
            provider=name,
        )

    return cls(
        model=env.get("EMBEDDING_MODEL") or cls.default_model,
        dim=dim,
        revision=env.get("EMBEDDING_REVISION") or "",
        batch_size=int(env.get("EMBEDDING_BATCH_SIZE") or 32),
        timeout=float(env.get("EMBEDDING_TIMEOUT") or 30.0),
        max_retries=int(env.get("EMBEDDING_MAX_RETRIES") or 3),
        credits_per_1k_tokens=credits,
        **cls.options_from(env),
    )


def images_enabled(env: dict | None = None) -> bool:
    """Whether PDF figures are extracted and embedded at all.

    Off by default: it is new behaviour, it costs extraction time on every PDF,
    and a deployment whose embedder has no image tower must not be asked for one.
    """
    env = os.environ if env is None else env
    return (env.get("EMBEDDING_IMAGES") or "") == "1"
