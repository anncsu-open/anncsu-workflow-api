"""Tests for AnncsuClientManager: pre-built or lazily built clients + per-API locks.

A client is either supplied pre-built (tests/regression) or built lazily on first
use from a per-source builder (production discovers the URL from the voucher, ADR
0017). The per-source ``asyncio.Lock`` serializes calls into each API.
"""

from app.adapters.anncsu.client_manager import AnncsuClientManager


def test_client_returns_a_prebuilt_client():
    manager = AnncsuClientManager(clients={"a": "client-a"})
    assert manager.client("a") == "client-a"


def test_client_builds_lazily_once_and_caches():
    calls: list[int] = []

    def builder():
        calls.append(1)
        return "built"

    manager = AnncsuClientManager(builders={"a": builder})
    assert manager.client("a") == "built"
    assert manager.client("a") == "built"  # second call reuses the cache
    assert len(calls) == 1  # the builder ran exactly once


def test_lock_is_one_per_source_and_stable():
    manager = AnncsuClientManager(clients={"a": object(), "b": object()})
    assert manager.lock("a") is manager.lock("a")
    assert manager.lock("a") is not manager.lock("b")
