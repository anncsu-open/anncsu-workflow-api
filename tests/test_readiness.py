"""Tests for the liveness/readiness probes (ADR 0015).

``/health`` is liveness (always ok, no dependency). ``/ready`` exercises the PDND
auth engine across all four sources using cached tokens; here the managers are
faked, and ``app.state`` is populated directly (bare ``TestClient`` does not run
the lifespan), so no credentials or network are involved.
"""

import asyncio

from fastapi.testclient import TestClient

from app import main
from app.adapters.anncsu.auth import SOURCES


class _FakeManager:
    def __init__(self, *, fail: bool = False, ttl: int = 3600) -> None:
        self.fail = fail
        self.ttl = ttl
        self.calls = 0

    def get_access_token(self) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError("token endpoint unreachable")
        return "voucher"

    def access_token_ttl(self) -> int:
        return self.ttl


class _FakeClientManager:
    """Holds per-source asyncio locks, like AnncsuClientManager."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, source: str) -> asyncio.Lock:
        return self._locks.setdefault(source, asyncio.Lock())


def _set_state(auth_managers) -> None:
    main.app.state.auth_managers = auth_managers
    main.app.state.client_manager = _FakeClientManager()


def test_health_is_liveness_and_always_ok():
    response = TestClient(main.app).get("/anncsu/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_is_200_with_per_source_ttls_when_all_authenticate():
    managers = {source: _FakeManager(ttl=1234) for source in SOURCES}
    _set_state(managers)

    response = TestClient(main.app).get("/anncsu/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert {entry["source"] for entry in body["sources"]} == set(SOURCES)
    assert all(entry["ok"] and entry["token_ttl"] == 1234 for entry in body["sources"])
    assert all(manager.calls == 1 for manager in managers.values())  # cached, fetched once


def test_ready_is_503_when_a_source_cannot_authenticate():
    managers = {source: _FakeManager() for source in SOURCES}
    managers["anncsu-accessi"] = _FakeManager(fail=True)
    _set_state(managers)

    response = TestClient(main.app).get("/anncsu/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not-ready"
    failing = [entry["source"] for entry in body["sources"] if not entry["ok"]]
    assert failing == ["anncsu-accessi"]


def test_ready_is_503_when_auth_is_not_initialized():
    main.app.state.auth_managers = None
    response = TestClient(main.app).get("/anncsu/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not-ready"
