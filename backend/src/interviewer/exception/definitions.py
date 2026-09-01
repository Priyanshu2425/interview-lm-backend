"""Refusals the surface can render.

The surface holds no invariant (ADR-0009) and composes no failure copy of its
own: it renders from the API's own `code` and `message`. FastAPI's default body
is `{"detail": ...}`, which carries neither — so a refusal that the surface has
to *say something specific about* is raised as a `Refusal` and lands at the top
level, where `api-client.ts` already looks for it.

Deliberately narrow. This is not a general error envelope: a 404 for an unknown
id needs no code, because there is one sentence to say and the client already
says it.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class Refusal(Exception):
    """A rule said no, and the surface has to name which rule."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def install(app: FastAPI) -> None:
    @app.exception_handler(Refusal)
    async def _refused(_: Request, exc: Refusal) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"code": exc.code, "message": exc.message},
        )
