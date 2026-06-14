"""The client manager: one authenticated sub-SDK client per Arazzo source.

Clients are built once and reused across dispatches so each API keeps its own
PDND auth state. The per-source ``asyncio.Lock`` serializes calls into one
client: the SDK's token refresh is sync-only and not safe to run concurrently
(anncsu-sdk#35); once async hooks land upstream the locks can be dropped
together with the ``asyncio.to_thread`` seam in the transport.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from app.config import Settings


def server_urls_from_settings(settings: Settings) -> dict[str, str]:
    """Per-source server URL, honoring the validation environment (ADR 0015).

    The single source of truth for the source-to-URL mapping, consumed by the
    authenticated client build in the application lifespan.
    """
    validation = settings.use_validation_env
    return {
        "anncsu-consultazione": (
            settings.anncsu_consultazione_val_url
            if validation
            else settings.anncsu_consultazione_url
        ),
        "anncsu-odonimi": (
            settings.anncsu_odonimi_val_url if validation else settings.anncsu_odonimi_url
        ),
        "anncsu-accessi": settings.anncsu_accessi_url,
        "anncsu-coordinate": settings.anncsu_coordinate_url,
    }


class AnncsuClientManager:
    """Holds the per-source SDK clients and their dispatch locks."""

    def __init__(self, clients: Mapping[str, Any]) -> None:
        self._clients = dict(clients)
        self._locks: dict[str, asyncio.Lock] = {}

    def client(self, source: str) -> Any:
        """The SDK client serving ``source``."""
        return self._clients[source]

    def lock(self, source: str) -> asyncio.Lock:
        """The dispatch lock for ``source`` (created on first use, then stable)."""
        return self._locks.setdefault(source, asyncio.Lock())
