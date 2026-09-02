"""Liveness and readiness. Two endpoints because they are two questions."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

router = APIRouter(tags=["health"])


#: Health answers are about this process at this moment, so nothing may keep one.
#:
#: The API is served through Cloudflare, which will hold a JSON body at the edge and
#: answer from it. A cached health check is worse than none: a monitor gets its 200
#: without the request ever reaching the origin, so a dead process keeps reporting
#: healthy — silently, because everything reported success. An operator curling the
#: endpoint reads a body hours old for the same reason.
NO_STORE = "no-store"


def _database_reachable() -> bool:
    """Whether Postgres answers, as a bool rather than an exception.

    Every kind of failure means the same thing to the caller — the database is
    not there — and a health check that raises is a health check that returns
    500 instead of the 503 it meant.
    """
    from sqlalchemy import text

    from ...deps import get_probe_engine

    try:
        with get_probe_engine().connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@router.get("/health")
def health(request: Request, response: Response) -> dict:
    """Alive, and separately, able to do the job.

    `ready` is deliberately not `ok`: a process warming a model is alive and
    answering, and should not be restarted — it should not be sent traffic
    yet, which is a different question and needs a different field.

    `database` is a third question again, and the only one that decides the
    status code. A process that cannot reach Postgres can serve no Session,
    no Corpus and no upload; reporting that as healthy is how a caller finds
    out one request at a time. Whether the embedder is warm is not a reason
    to refuse traffic — `MODEL_WARM_AT_BOOT` is off in most deployments, so
    a 503 for a cold model would be a 503 for every ordinary deploy.
    """
    from ...deps import get_embedder

    # Asked first, and the status set with it, because the embedder block
    # below returns early and a status set after it would never be reached.
    response.headers["cache-control"] = NO_STORE

    reachable = _database_reachable()
    if not reachable:
        response.status_code = 503

    body: dict = {
        "ok": True,
        "ready": getattr(request.app.state, "ready", True),
        "database": reachable,
    }
    try:
        embedder = get_embedder()
    except Exception as exc:
        body["embedder"] = {"error": type(exc).__name__, "message": str(exc)}
        return body
    report = getattr(embedder, "health", None)
    body["embedder"] = (
        report()
        if callable(report)
        else {
            "model": getattr(embedder, "model_name", "unknown"),
            "dim": getattr(embedder, "dim", None),
        }
    )
    return body


@router.get("/health/live")
def live(request: Request, response: Response) -> dict:
    """Up, without asking anything else whether it agrees.

    Separate from `/v1/health` because the two questions have different
    costs. Reading a row wakes Neon's compute and then holds it awake, so
    anything asking on a timer — a process supervisor, a reverse proxy's
    upstream check, an uptime monitor — would spend a database allowance on
    a database nobody is using. This
    answers what those callers are actually asking: is there a process here
    to serve the next request. Whether it can serve it is still
    `/v1/health`.

    It does not reach for the embedder either, for the same reason in a
    different currency: constructing one is the paid provider's client, and
    a liveness check should cost a process being awake and nothing else.
    """
    response.headers["cache-control"] = NO_STORE
    return {"service": "interview-lm", "version": request.app.version}
