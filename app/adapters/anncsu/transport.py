"""``AnncsuSdkTransport``: the production adapter behind the ``WorkflowTransport`` port.

Dispatches one Arazzo operation through the registered typed SDK method and
normalizes the outcome at the boundary (ADR 0008):

- any HTTP outcome — a 200 model or a documented 4xx/5xx the SDK raises as
  ``AnncsuBaseError`` — becomes a :class:`Response`, so the spec's
  ``successCriteria``/``onFailure`` keep deciding what it means;
- failures of the call itself (network, no response, PDND token refresh)
  raise :class:`TransportError`.

The SDK call runs in a worker thread (``asyncio.to_thread``) under the
per-API lock because the PDND token refresh hook is sync-only and would
otherwise block the event loop (anncsu-sdk#35); swap to the ``*_async``
SDK methods once async hooks land upstream.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from anncsu.common.errors import AnncsuBaseError, NoResponseError
from anncsu.common.hooks.token_validation import TokenRefreshError

from app.adapters.anncsu.client_manager import AnncsuClientManager
from app.adapters.anncsu.registry import operation_for, resolve_method
from app.logging import get_logger
from app.ports.transport import Response, TransportError

_log = get_logger("app.transport")


class AnncsuSdkTransport:
    """Executes Arazzo operations through the typed anncsu-sdk clients."""

    def __init__(self, manager: AnncsuClientManager) -> None:
        self._manager = manager

    async def dispatch(
        self,
        *,
        operation_id: str,
        payload: Any,
        content_type: str | None,
    ) -> Response:
        """Run ``operation_id`` with ``payload`` as keyword arguments to the SDK."""
        operation = operation_for(operation_id)
        method = resolve_method(self._manager.client(operation.source), operation.method_path)
        kwargs = dict(payload) if payload else {}

        start = time.perf_counter()
        async with self._manager.lock(operation.source):
            try:
                model = await asyncio.to_thread(method, **kwargs)
            except AnncsuBaseError as error:
                response = _response_from_error(error)
                _log.debug(
                    "transport.dispatch",
                    operation_id=operation_id,
                    status_code=response.status_code,
                    duration_ms=round((time.perf_counter() - start) * 1000, 1),
                )
                return response
            except (httpx.HTTPError, NoResponseError, TokenRefreshError) as error:
                raise TransportError(
                    f"call for {operation_id!r} failed before an HTTP outcome: {error}"
                ) from error

        _log.debug(
            "transport.dispatch",
            operation_id=operation_id,
            status_code=200,
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        return Response(status_code=200, body=model.model_dump(mode="json", by_alias=True))


def _response_from_error(error: AnncsuBaseError) -> Response:
    """Map a documented HTTP error (the SDK raises it typed) back to a ``Response``."""
    try:
        body = error.raw_response.json()
    except ValueError:
        body = error.body
    return Response(
        status_code=error.status_code,
        body=body,
        headers=dict(error.headers),
    )
