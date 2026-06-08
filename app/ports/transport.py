"""The ``WorkflowTransport`` port: the async seam between the executor and the world.

The executor never talks to the ANNCSU SDK or to PDND directly. It dispatches a
step's resolved request through this port and
receives a normalized :class:`Response`. Production wires an SDK-backed adapter; tests
wire a scripted/mock adapter. This keeps the engine domain-agnostic and unit-pure.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Response:
    """Normalized result of a single API operation.

    Attributes mirror the runtime-expression surface the Arazzo spec reads
    (``$statusCode``, ``$response.body.*``, ``$response.headers.*``).
    """

    status_code: int
    body: Any = None
    headers: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class WorkflowTransport(Protocol):
    """Async port that executes one Arazzo operation and returns a :class:`Response`."""

    async def dispatch(
        self,
        *,
        operation_id: str,
        payload: Any,
        content_type: str | None,
    ) -> Response:
        """Execute ``operation_id`` with the already-resolved ``payload``."""
        ...
