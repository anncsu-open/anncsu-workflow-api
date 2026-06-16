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

# A dispatch holds the per-source lock for its whole duration, so it MUST be
# time-bounded: a stuck PDND call (token refresh, voucher fetch, or the operation
# itself) would otherwise hold the lock forever and block every later call to that
# source. The bound is generous (the cold first call chains a voucher fetch + the
# operation, each with the SDK's own 5s HTTP timeout) but finite.
DISPATCH_TIMEOUT_SECONDS = 30.0


class AnncsuSdkTransport:
    """Executes Arazzo operations through the typed anncsu-sdk clients."""

    def __init__(
        self, manager: AnncsuClientManager, *, timeout: float = DISPATCH_TIMEOUT_SECONDS
    ) -> None:
        self._manager = manager
        self._timeout = timeout

    async def dispatch(
        self,
        *,
        operation_id: str,
        payload: Any,
        content_type: str | None,
    ) -> Response:
        """Run ``operation_id`` with ``payload`` as keyword arguments to the SDK."""
        operation = operation_for(operation_id)
        kwargs = dict(payload) if payload else {}

        start = time.perf_counter()
        async with self._manager.lock(operation.source):
            try:
                # Resolve the client inside the thread: building it lazily fetches a
                # voucher to discover the server URL (ADR 0017), a blocking call that
                # must not run on the event loop, and is serialized by the lock.
                # Bounded by a timeout so a hung call cannot hold the lock forever
                # (the worker thread may outlive the await, but the lock is released).
                model = await asyncio.wait_for(
                    asyncio.to_thread(self._invoke, operation, kwargs), self._timeout
                )
            except TimeoutError as error:
                raise TransportError(
                    f"call for {operation_id!r} timed out after {self._timeout}s"
                ) from error
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

    def _invoke(self, operation: Any, kwargs: dict[str, Any]) -> Any:
        """Resolve the (possibly lazily built) client and call the SDK method.

        Synchronous — runs in a worker thread, because resolving the client may
        build it lazily, which fetches a voucher (a blocking call, ADR 0017).
        """
        client = self._manager.client(operation.source)
        method = resolve_method(client, operation.method_path)
        return method(**kwargs)


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
