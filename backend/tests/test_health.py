"""The two health questions, and why they are two.

`/v1/health/live` asks whether there is a process here. `/v1/health` asks
whether that process can do anything. They are separate because they cost
different things: the second reads a row, and a row read on a timer holds
Neon's compute awake for a database nobody is using.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from interviewer import deps
from interviewer.app import create_app


class _Unreachable:
    """An engine that behaves like a database that has gone away."""

    def connect(self):
        raise OSError("connection refused")


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def stub_embedder(monkeypatch):
    """Nothing here is asking about the embedder, and building one is paid for.

    The health endpoint reports whatever it is given; a test that let it build
    the configured one would be a test that downloads weights or opens a
    Provider client to assert on a key it already knows the name of.
    """
    class Stub:
        model_name = "stub"
        dim = 8

    monkeypatch.setattr(deps, "get_embedder", lambda: Stub())


@pytest.fixture()
def reachable(engine, monkeypatch):
    """The probe, pointed at the suite's own Postgres rather than a second pool."""
    monkeypatch.setattr(deps, "get_probe_engine", lambda: engine)
    return engine


@pytest.fixture()
def unreachable(monkeypatch):
    monkeypatch.setattr(deps, "get_probe_engine", _Unreachable)


# -- liveness ---------------------------------------------------------------

def test_liveness_needs_no_authentication(client):
    response = client.get("/v1/health/live")
    assert response.status_code == 200
    assert response.json()["service"] == "interview-lm"


def test_liveness_reports_a_version(client):
    assert client.get("/v1/health/live").json()["version"]


def test_liveness_answers_without_reaching_the_database(client, unreachable):
    """The whole reason it exists apart from `/v1/health`.

    A poller on a timer — a process supervisor, a reverse proxy's upstream
    check, an uptime monitor — would otherwise wake Neon's compute every few
    minutes and hold it awake for a database no Candidate is using. If this
    test starts failing, that cost has come back.
    """
    response = client.get("/v1/health/live")

    assert response.status_code == 200
    assert response.json()["version"]


def test_liveness_does_not_reach_for_the_embedder(client, monkeypatch):
    """Constructing one is the paid Provider's client, on a ten-minute timer."""
    def refuse():
        raise AssertionError("liveness built an embedder")

    monkeypatch.setattr(deps, "get_embedder", refuse)
    assert client.get("/v1/health/live").status_code == 200


# -- readiness --------------------------------------------------------------

def test_health_reports_the_database_it_can_reach(client, reachable, stub_embedder):
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["database"] is True


def test_health_still_says_what_it_always_said(client, reachable, stub_embedder):
    """`ok`, `ready` and `embedder` are the contract that was already there."""
    body = client.get("/v1/health").json()
    assert body["ok"] is True
    assert body["ready"] is True
    assert body["embedder"]["model"] == "stub"


def test_a_process_that_cannot_reach_its_database_is_not_healthy(
    client, unreachable, stub_embedder
):
    """It can serve no Session, no Corpus and no upload.

    Reporting it healthy is how the caller finds out one request at a time.
    """
    response = client.get("/v1/health")

    assert response.status_code == 503
    assert response.json()["database"] is False


def test_a_cold_embedder_is_reported_and_is_not_an_outage(client, reachable, monkeypatch):
    """`MODEL_WARM_AT_BOOT` is off in most deployments.

    A 503 for an embedder that was never asked to warm would be a 503 for every
    ordinary deploy, which is an alarm nobody would be left reading.
    """
    def refuse():
        raise RuntimeError("no weights here")

    monkeypatch.setattr(deps, "get_embedder", refuse)
    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json()["embedder"]["error"] == "RuntimeError"


def test_the_status_survives_the_embedder_reporting_first(client, unreachable, monkeypatch):
    """The embedder branch returns early, and the 503 must outlive it."""
    def refuse():
        raise RuntimeError("no weights here")

    monkeypatch.setattr(deps, "get_embedder", refuse)
    response = client.get("/v1/health")

    assert response.status_code == 503
    assert response.json()["database"] is False


# -- neither answer may be kept ---------------------------------------------

def test_liveness_may_not_be_cached(client):
    """A cached liveness check is the failure it was built to prevent.

    Both hosts are served through Cloudflare. A 200 from the edge never reaches
    the origin, so a dead process keeps answering healthy — and every party to
    it reports success.
    """
    assert client.get("/v1/health/live").headers["cache-control"] == "no-store"


def test_health_may_not_be_cached(client, reachable, stub_embedder):
    assert client.get("/v1/health").headers["cache-control"] == "no-store"


def test_a_refusal_may_not_be_cached_either(client, unreachable, stub_embedder):
    """The 503 is the one an edge holding it for four hours would hurt most."""
    response = client.get("/v1/health")
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
