"""Operator console. Authenticated separately from Candidate access."""

from __future__ import annotations

import os
from dataclasses import asdict

from fastapi import APIRouter, Header, HTTPException

from interviewer.metering.operator import OperatorService

from .wiring import wiring

router = APIRouter(tags=["operator"])


def _guard(token: str | None) -> None:
    expected = os.environ.get("OPERATOR_TOKEN", "dev-operator-token")
    if token != expected:
        raise HTTPException(401, "operator access required")


@router.get("/operator/pool")
def pool(x_operator_token: str | None = Header(default=None)) -> dict:
    _guard(x_operator_token)
    return asdict(OperatorService(wiring().engine).pool())


@router.get("/operator/providers")
def providers(x_operator_token: str | None = Header(default=None)) -> dict:
    _guard(x_operator_token)
    svc = OperatorService(wiring().engine)
    return {
        "unpriced_rate": svc.unpriced_rate(),
        "providers": [asdict(p) for p in svc.by_provider()],
        # Weights are set by Grading Mode alone. No normaliser is applied to
        # any figure here, and none will be invented.
        "normaliser": None,
    }


@router.get("/operator/sessions")
def sessions(x_operator_token: str | None = Header(default=None)) -> dict:
    _guard(x_operator_token)
    return {"sessions": OperatorService(wiring().engine).sessions()}
