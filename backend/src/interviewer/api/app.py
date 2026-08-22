"""FastAPI application. Versioned under /v1 (SPEC-0000 §4)."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from .errors import install as install_refusals
from .routes_candidate import router as candidate_router
from .routes_corpus import router as corpus_router
from .routes_notebooks import router as notebooks_router
from .routes_operator import router as operator_router
from .routes_sessions import router as sessions_router


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
        title="Cortex Interviewer",
        version="0.1.0",
        docs_url="/v1/docs",
        openapi_url="/v1/openapi.json",
        lifespan=lifespan,
    )
    _allow_origins(app)
    install_refusals(app)
    app.include_router(corpus_router, prefix="/v1")
    app.include_router(sessions_router, prefix="/v1")
    app.include_router(candidate_router, prefix="/v1")
    app.include_router(notebooks_router, prefix="/v1")
    app.include_router(operator_router, prefix="/v1")

    @app.get("/v1/health")
    def health() -> dict:
        """Liveness, plus what the embedder is and whether it is loaded.

        `ready` is deliberately not `ok`: a process warming a model is alive and
        answering, and should not be restarted — it should not be sent traffic
        yet, which is a different question and needs a different field.
        """
        from .deps import get_embedder

        body: dict = {"ok": True, "ready": getattr(app.state, "ready", True)}
        try:
            embedder = get_embedder()
        except Exception as exc:
            body["embedder"] = {"error": type(exc).__name__, "message": str(exc)}
            return body
        report = getattr(embedder, "health", None)
        body["embedder"] = report() if callable(report) else {
            "model": getattr(embedder, "model_name", "unknown"),
            "dim": getattr(embedder, "dim", None),
        }
        return body

    # The surface is served from the same origin as the API, which is what
    # removes the CORS and cookie decision SPEC-0000 §7 left open — at least
    # until auth lands (SPEC-0003 §1a).
    #
    # The surface is a client-routed application, so a deep link like
    # /examination/s_2148 is a real address the server has never heard of.
    # StaticFiles alone would 404 it; SPAFiles hands back index.html instead
    # and lets the client resolve the route. Anything under /v1 is mounted
    # first and is unaffected.
    root = Path(__file__).resolve().parents[4]
    surface = Path(os.environ.get("SURFACE_DIR", root / "frontend" / "dist"))
    if surface.is_dir():
        app.mount("/", SPAFiles(directory=str(surface), html=True), name="surface")

    return app


def allowed_origins() -> list[str]:
    """Origins permitted to call this API from a browser.

    Empty is the original deployment and stays the default: SPEC-0000 §7 chose
    same-origin, the API mounts the surface at `/`, and a browser never makes a
    cross-origin request to it. Setting this is what reverses that decision
    (ADR-0020), and it has to be set deliberately.
    """
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


def _allow_origins(app: FastAPI) -> None:
    origins = allowed_origins()
    if not origins:
        return
    if "*" in origins:
        # Credentials and a wildcard cannot both be true — the browser refuses
        # it — and silently dropping credentials would break auth in a way that
        # only shows up once auth exists. Refusing here is the honest failure.
        raise ValueError(
            "ALLOWED_ORIGINS may not be '*': this API sends credentials, and a "
            "wildcard origin with credentials is refused by every browser. "
            "Name the surface's origin explicitly."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        # The surface will need to send a session credential once ISSUE-0011
        # lands. Allowing it now costs nothing and means auth does not arrive
        # needing a CORS change at the same time.
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["content-type", "authorization", "idempotency-key"],
    )


class SPAFiles(StaticFiles):
    """Static files, with the client router's routes falling back to the shell.

    A 404 for a path the client owns is a wrong answer, not a missing file. A
    404 for a missing asset is still a 404 — swallowing that would turn a
    broken build into a blank page with no signal.
    """

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except HTTPException as missing:
            if missing.status_code != 404 or "." in Path(path).name:
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and "." not in Path(path).name:
            return await super().get_response("index.html", scope)
        return response


app = create_app()
