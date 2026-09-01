"""Assembly details `create_app` uses: who may call it."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def allowed_origins() -> list[str]:
    """Origins permitted to call this API from a browser.

    Empty is the original deployment and stays the default: SPEC-0000 §7 chose
    same-origin, the API mounts the surface at `/`, and a browser never makes a
    cross-origin request to it. Setting this is what reverses that decision
    (ADR-0020), and it has to be set deliberately.
    """
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


def install_cors(app: FastAPI) -> None:
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
