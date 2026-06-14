"""Liveness and readiness probes (ADR 0015).

``/health`` is a cheap liveness check (the process is up) with no external
dependency, so an orchestrator never restarts the pod over a transient PDND blip.
``/ready`` is readiness: it confirms every Arazzo source can obtain a PDND voucher,
using the auth managers' cached tokens (refreshed only near expiry), run off the
event loop under the per-source lock (the SDK token refresh is sync-only).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request, Response

from app.adapters.anncsu.auth import SOURCES

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness check")
async def health() -> dict[str, str]:
    """Liveness: the process is up. No external dependency is checked."""
    return {"status": "ok"}


async def _check_source(source: str, manager: Any, lock: asyncio.Lock) -> dict[str, Any]:
    """Confirm one source can authenticate, serialized with its dispatches."""
    async with lock:
        try:
            await asyncio.to_thread(manager.get_access_token)
        except Exception as error:  # noqa: BLE001 - any auth failure means not-ready
            return {"source": source, "ok": False, "detail": str(error)}
    return {"source": source, "ok": True, "token_ttl": manager.access_token_ttl()}


@router.get("/ready", summary="Readiness check (PDND authentication)")
async def ready(request: Request, response: Response) -> dict[str, Any]:
    """Readiness: every source can obtain a PDND voucher (cached, refreshed near expiry)."""
    auth_managers = getattr(request.app.state, "auth_managers", None)
    client_manager = getattr(request.app.state, "client_manager", None)
    if not auth_managers or client_manager is None:
        response.status_code = 503
        return {"status": "not-ready", "detail": "authentication not initialized"}

    sources = await asyncio.gather(
        *(
            _check_source(source, auth_managers[source], client_manager.lock(source))
            for source in SOURCES
        )
    )
    is_ready = all(entry["ok"] for entry in sources)
    response.status_code = 200 if is_ready else 503
    return {"status": "ready" if is_ready else "not-ready", "sources": sources}
