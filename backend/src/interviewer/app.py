"""FastAPI application. Versioned under /v1 (SPEC-0000 §4)."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import config
from .exception.definitions import install as install_refusals
from .middleware import (
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from .routes.v1.candidate_router import router as candidate_router
from .routes.v1.skills_router import router as skills_router
from .routes.v1.health_router import router as health_router
from .routes.v1.notebooks_router import router as notebooks_router
from .routes.v1.operator_router import router as operator_router
from .routes.v1.sessions_router import router as sessions_router

# Re-exported: `allowed_origins` is read as configuration by callers that know
# this module as the API.
from .util.app_utils import allowed_origins, install_cors

__all__ = ["allowed_origins", "app", "create_app"]

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the model before serving, when the deployment asks for it.

    Off by default, because dev and the test suite want a process that starts
    instantly and never touches a bucket. On, it is the difference between a
    Candidate's first upload paying for a 1.5GB download and a rolling deploy
    paying for it — and readiness below is what stops traffic arriving at a
    process still in the middle of that.
    """
    app.state.ready = True
    # Applied here so a deployment has its schema before it takes traffic. It
    # is idempotent, and `wiring.sync_engine()` applies it too for the scripts
    # and the CLI, which never run a lifespan.
    try:
        from .wiring import apply_schema, sync_engine

        apply_schema(sync_engine())
    except Exception:
        log.warning("could not apply the schema at boot", exc_info=True)
    # No worker survives a restart, so anything still marked `ingesting` is
    # stale by definition rather than by a guess about how long is too long
    # (ISSUE-0035). Reset before serving, so the first poll after a deploy tells
    # the truth. A database that is not reachable yet is not a reason to refuse
    # to start: every other route still works, and the next boot will do this.
    try:
        from .ingest_worker import reset_stale

        reset_stale()
    except Exception:
        log.warning("could not reset interrupted ingests", exc_info=True)
    if os.environ.get("MODEL_WARM_AT_BOOT") == "1":
        from .deps import get_embedder

        app.state.ready = False
        try:
            get_embedder().warm()
            app.state.ready = True
        except Exception:
            # Left not-ready and logged. A process that cannot embed can still
            # serve every Session that does not ingest, so it stays up.
            log.exception("model warm-up failed; ingest will be unavailable")
    yield
    try:
        from .deps import get_embedder

        get_embedder().close()
    except Exception:  # pragma: no cover - shutdown is best effort
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="InterviewLM",
        version="0.1.0",
        docs_url="/v1/docs",
        openapi_url="/v1/openapi.json",
        lifespan=lifespan,
    )

    # 1. Security headers (outermost - applied to all responses)
    #
    # No `csp_policy=` argument. It used to pass `default-src 'self'` here,
    # which is the same string the middleware's default *was* — so when
    # ISSUE-0052 widened the default to permit the transcriber's WebAssembly,
    # this call silently kept serving the old one. The header the app actually
    # sent and the policy the class documented had drifted apart, and the test
    # covering it constructed the middleware directly and so agreed with the
    # class rather than with the app (ISSUE-0054).
    app.add_middleware(SecurityHeadersMiddleware)

    # 2. Rate limit (before auth/logging)
    rl = config.rate_limit
    app.add_middleware(
        RateLimitMiddleware,
        enabled=rl.enabled,
        requests_per_minute=rl.requests_per_minute,
        window_seconds=rl.window_seconds,
        workflow_path_prefix=rl.workflow_path_prefix,
        workflow_requests_per_minute=rl.workflow_requests_per_minute,
    )

    # 3. Request logging (inner)
    app.add_middleware(RequestLoggingMiddleware)

    # 4. CORS (existing)
    install_cors(app)

    install_refusals(app)
    app.include_router(skills_router, prefix="/v1")
    app.include_router(sessions_router, prefix="/v1")
    app.include_router(candidate_router, prefix="/v1")
    app.include_router(notebooks_router, prefix="/v1")
    app.include_router(operator_router, prefix="/v1")
    app.include_router(health_router, prefix="/v1")

    return app


app = create_app()
