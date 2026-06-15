"""The client manager: one authenticated sub-SDK client per Arazzo source.

A client is either supplied pre-built (``clients=`` — used by tests and the
real-SDK regression, which wire clients onto a fake transport) or built lazily on
first use from a per-source ``builders`` callable (production: the builder fetches
the voucher and derives the server URL from its audience — ADR 0017). Either way
the client is cached and reused across dispatches, so each API keeps its own PDND
auth state.

The per-source ``asyncio.Lock`` serializes calls into one client: the SDK's token
refresh is sync-only and not safe to run concurrently (anncsu-sdk#35). Because the
lazy build performs a blocking voucher fetch, the transport resolves the client
inside ``asyncio.to_thread`` under that lock, off the event loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any


class AnncsuClientManager:
    """Holds the per-source SDK clients (pre-built or lazily built) and their locks."""

    def __init__(
        self,
        clients: Mapping[str, Any] | None = None,
        builders: Mapping[str, Callable[[], Any]] | None = None,
    ) -> None:
        self._clients = dict(clients or {})
        self._builders = dict(builders or {})
        self._built: dict[str, Any] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def client(self, source: str) -> Any:
        """The SDK client serving ``source``, building it lazily on first use.

        Blocking when it builds (voucher fetch), so call it off the event loop —
        the transport invokes it inside ``asyncio.to_thread`` under the lock.
        """
        if source in self._clients:
            return self._clients[source]
        if source not in self._built:
            self._built[source] = self._builders[source]()
        return self._built[source]

    def lock(self, source: str) -> asyncio.Lock:
        """The dispatch lock for ``source`` (created on first use, then stable)."""
        return self._locks.setdefault(source, asyncio.Lock())
