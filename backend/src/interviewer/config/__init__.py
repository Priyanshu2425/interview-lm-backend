"""Centralized configuration from environment. All defaults in code."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class SyncDBConfig:
    """Synchronous database config (for LangGraph checkpointer only)."""
    url: str
    graph_url: str | None
    pool_size: int = 1
    max_overflow: int = 0
    pool_recycle: int = 300
    pool_pre_ping: bool = True


@dataclass(frozen=True, slots=True)
class AsyncDBConfig:
    """Asynchronous database config (for all API services)."""
    url: str
    pool_size: int = 20
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 300
    pool_pre_ping: bool = True


@dataclass(frozen=True, slots=True)
class GraphBridgeConfig:
    """Thread pool config for sync→async bridge (LangGraph nodes)."""
    workers: int = 4
    timeout: int = 30


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    """Embedding provider configuration."""
    provider: str = "hashing"
    model: str = "google/siglip2-base-patch16-224"
    revision: str = ""
    dim: int = 768
    device: str = "auto"
    batch_size: int = 32
    timeout: int = 30
    max_retries: int = 3
    images: bool = False
    endpoint: str = ""
    api_key: str = ""
    credits_per_1k: int = 0
    allow_paid: bool = False


@dataclass(frozen=True, slots=True)
class ObjectStoreConfig:
    """Object store (R2) configuration."""
    endpoint_url: str = ""
    access_key_id: str = ""
    secret_access_key: str = ""
    bucket: str = ""
    prefix: str = ""


@dataclass(frozen=True, slots=True)
class ModelArtifactsConfig:
    """Model artifacts (published weights) configuration."""
    bucket: str = ""
    prefix: str = ""
    cache_dir: str = ""
    warm_at_boot: bool = False


@dataclass(frozen=True, slots=True)
class BYOKConfig:
    """BYOK key encryption configuration."""
    kek: str = ""
    kek_ephemeral: bool = False


@dataclass(frozen=True, slots=True)
class IdentityConfig:
    """Gatehouse identity configuration."""
    issuer: str = "https://auth.buildspacelabs.com"
    audience: str = "interview-lm"
    jwks_url: str = ""


@dataclass(frozen=True, slots=True)
class SurfaceConfig:
    """Surface (frontend) configuration.

    No `surface_dir`. The API served the built surface at `/` until ADR-0020
    split the origins; the mount went and this setting stayed, read into
    configuration and used by nothing — while the Dockerfile, both env examples
    and `tools/preflight.mjs` all went on describing what it did. A setting
    nothing reads is worse than an absent one: it answers "why is the surface
    not being served?" with a plausible thing to try.
    """
    allowed_origins: str = ""


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    """Application-level rate limiting (sliding window, in-memory)."""
    enabled: bool = True
    requests_per_minute: int = 100
    window_seconds: int = 60
    workflow_path_prefix: str = "/v1/sessions"
    workflow_requests_per_minute: int = 300


@dataclass(frozen=True, slots=True)
class Config:
    """Complete application configuration."""
    sync_db: SyncDBConfig
    async_db: AsyncDBConfig
    graph_bridge: GraphBridgeConfig
    embedding: EmbeddingConfig
    object_store: ObjectStoreConfig
    model_artifacts: ModelArtifactsConfig
    byok: BYOKConfig
    identity: IdentityConfig
    surface: SurfaceConfig
    rate_limit: RateLimitConfig
    openrouter_api_key: str = ""
    interviewer_fake_model: bool = False
    corpus_path: str = ""
    index_build_mem: str = "128MB"
    operator_token: str = "dev-operator-token"


def _derive_async_url(sync_url: str) -> str:
    """Derive async URL from sync URL by swapping driver to asyncpg."""
    if sync_url.startswith("postgresql+psycopg://"):
        return "postgresql+asyncpg://" + sync_url[len("postgresql+psycopg://"):]
    if sync_url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + sync_url[len("postgresql://"):]
    return sync_url


def _load_sync_db() -> SyncDBConfig:
    url = os.environ.get("DATABASE_URL", "postgresql+psycopg://cortex:cortex@127.0.0.1:55432/cortex")
    graph_url = os.environ.get("GRAPH_DATABASE_URL") or None
    return SyncDBConfig(url=url, graph_url=graph_url)


def _load_async_db() -> AsyncDBConfig:
    async_url = os.environ.get("ASYNC_DATABASE_URL")
    if not async_url:
        sync_url = os.environ.get("DATABASE_URL", "postgresql+psycopg://cortex:cortex@127.0.0.1:55432/cortex")
        async_url = _derive_async_url(sync_url)
    return AsyncDBConfig(
        url=async_url,
        pool_size=int(os.environ.get("ASYNC_POOL_SIZE", "20")),
        max_overflow=int(os.environ.get("ASYNC_MAX_OVERFLOW", "10")),
        pool_timeout=int(os.environ.get("ASYNC_POOL_TIMEOUT", "30")),
        pool_recycle=int(os.environ.get("ASYNC_POOL_RECYCLE", "300")),
        pool_pre_ping=os.environ.get("ASYNC_POOL_PRE_PING", "true").lower() == "true",
    )


def _load_graph_bridge() -> GraphBridgeConfig:
    return GraphBridgeConfig(
        workers=int(os.environ.get("GRAPH_ASYNC_WORKERS", "4")),
        timeout=int(os.environ.get("GRAPH_ASYNC_TIMEOUT", "30")),
    )


def _load_embedding() -> EmbeddingConfig:
    return EmbeddingConfig(
        provider=os.environ.get("EMBEDDING_PROVIDER", "hashing"),
        model=os.environ.get("EMBEDDING_MODEL", "google/siglip2-base-patch16-224"),
        revision=os.environ.get("EMBEDDING_REVISION", ""),
        dim=int(os.environ.get("EMBEDDING_DIM", "768")),
        device=os.environ.get("EMBEDDING_DEVICE", "auto"),
        batch_size=int(os.environ.get("EMBEDDING_BATCH_SIZE", "32")),
        timeout=int(os.environ.get("EMBEDDING_TIMEOUT", "30")),
        max_retries=int(os.environ.get("EMBEDDING_MAX_RETRIES", "3")),
        images=os.environ.get("EMBEDDING_IMAGES", "false").lower() == "true",
        endpoint=os.environ.get("EMBEDDING_ENDPOINT", ""),
        api_key=os.environ.get("EMBEDDING_API_KEY", ""),
        credits_per_1k=int(os.environ.get("EMBEDDING_CREDITS_PER_1K", "0")),
        allow_paid=os.environ.get("EMBEDDING_ALLOW_PAID", "false").lower() == "true",
    )


def _load_object_store() -> ObjectStoreConfig:
    return ObjectStoreConfig(
        endpoint_url=os.environ.get("R2_ENDPOINT_URL", ""),
        access_key_id=os.environ.get("R2_ACCESS_KEY_ID", ""),
        secret_access_key=os.environ.get("R2_SECRET_ACCESS_KEY", ""),
        bucket=os.environ.get("CONTENT_BUCKET", ""),
        prefix=os.environ.get("CONTENT_PREFIX", ""),
    )


def _load_model_artifacts() -> ModelArtifactsConfig:
    return ModelArtifactsConfig(
        bucket=os.environ.get("MODEL_BUCKET", ""),
        prefix=os.environ.get("MODEL_PREFIX", ""),
        cache_dir=os.environ.get("MODEL_CACHE_DIR", ""),
        warm_at_boot=os.environ.get("MODEL_WARM_AT_BOOT", "false").lower() == "true",
    )


def _load_byok() -> BYOKConfig:
    return BYOKConfig(
        kek=os.environ.get("BYOK_KEK", ""),
        kek_ephemeral=os.environ.get("BYOK_KEK_EPHEMERAL", "false").lower() == "true",
    )


def _load_identity() -> IdentityConfig:
    return IdentityConfig(
        issuer=os.environ.get("GATEHOUSE_ISSUER", "https://auth.buildspacelabs.com"),
        audience=os.environ.get("GATEHOUSE_AUDIENCE", "interview-lm"),
        jwks_url=os.environ.get("GATEHOUSE_JWKS_URL", ""),
    )


def _load_surface() -> SurfaceConfig:
    return SurfaceConfig(
        allowed_origins=os.environ.get("ALLOWED_ORIGINS", ""),
    )


def _load_rate_limit() -> RateLimitConfig:
    return RateLimitConfig(
        enabled=os.environ.get("RATE_LIMIT_ENABLED", "true").lower() == "true",
        requests_per_minute=int(os.environ.get("RATE_LIMIT_RPM", "100")),
        window_seconds=int(os.environ.get("RATE_LIMIT_WINDOW", "60")),
        workflow_path_prefix=os.environ.get("RATE_LIMIT_WORKFLOW_PREFIX", "/v1/sessions"),
        workflow_requests_per_minute=int(os.environ.get("RATE_LIMIT_WORKFLOW_RPM", "300")),
    )


@lru_cache(maxsize=1)
def load_config() -> Config:
    """Load all configuration from environment. Cached singleton."""
    return Config(
        sync_db=_load_sync_db(),
        async_db=_load_async_db(),
        graph_bridge=_load_graph_bridge(),
        embedding=_load_embedding(),
        object_store=_load_object_store(),
        model_artifacts=_load_model_artifacts(),
        byok=_load_byok(),
        identity=_load_identity(),
        surface=_load_surface(),
        rate_limit=_load_rate_limit(),
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        interviewer_fake_model=os.environ.get("INTERVIEWER_FAKE_MODEL", "false").lower() == "true",
        corpus_path=os.environ.get("CORPUS_PATH", ""),
        index_build_mem=os.environ.get("INDEX_BUILD_MEM", "128MB"),
        operator_token=os.environ.get("OPERATOR_TOKEN", "dev-operator-token"),
    )


# Global singleton
config = load_config()