"""Test doubles for the executor tests."""

from __future__ import annotations

from typing import Any

from app.ports.transport import Response


class ScriptedTransport:
    """A :class:`WorkflowTransport` double returning scripted responses.

    Responses are keyed by ``operation_id``; each ``dispatch`` is recorded in
    :attr:`calls` so tests can assert what the engine sent and in which order.
    """

    def __init__(self, responses: dict[str, Response]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, Any]] = []

    async def dispatch(
        self,
        *,
        operation_id: str,
        payload: Any,
        content_type: str | None,
    ) -> Response:
        self.calls.append((operation_id, payload))
        return self._responses[operation_id]
