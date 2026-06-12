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

from anncsu.accessi import AnncsuAccessi
from anncsu.coordinate import AnncsuCoordinate
from anncsu.odonimi import AnncsuOdonimi
from anncsu.pa import AnncsuConsultazione

from app.config import Settings


class AnncsuClientManager:
    """Holds the per-source SDK clients and their dispatch locks."""

    def __init__(self, clients: Mapping[str, Any]) -> None:
        self._clients = dict(clients)
        self._locks: dict[str, asyncio.Lock] = {}

    @classmethod
    def from_settings(cls, settings: Settings) -> AnncsuClientManager:
        """Build the four sub-SDK clients with the configured server URLs."""
        validation = settings.use_validation_env
        return cls(
            clients={
                "anncsu-consultazione": AnncsuConsultazione(
                    server_url=settings.anncsu_consultazione_val_url
                    if validation
                    else settings.anncsu_consultazione_url
                ),
                "anncsu-odonimi": AnncsuOdonimi(
                    server_url=settings.anncsu_odonimi_val_url
                    if validation
                    else settings.anncsu_odonimi_url
                ),
                "anncsu-accessi": AnncsuAccessi(server_url=settings.anncsu_accessi_url),
                "anncsu-coordinate": AnncsuCoordinate(server_url=settings.anncsu_coordinate_url),
            }
        )

    def client(self, source: str) -> Any:
        """The SDK client serving ``source``."""
        return self._clients[source]

    def lock(self, source: str) -> asyncio.Lock:
        """The dispatch lock for ``source`` (created on first use, then stable)."""
        return self._locks.setdefault(source, asyncio.Lock())
