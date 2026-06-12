"""``WorkflowApplicationService``: runs Arazzo workflows for the driving adapters.

Deliberately thin (ADR 0004): domain logic lives in the canonical Arazzo spec and
is executed by the generic engine; transport detail lives behind the
``WorkflowTransport`` port. The service is the seam the routes depend on — and the
one tests override to inject a scripted transport.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.executor.engine import WorkflowExecutor, WorkflowRun


class WorkflowApplicationService:
    """Runs workflows against the configured executor."""

    def __init__(self, executor: WorkflowExecutor) -> None:
        self._executor = executor

    async def run(self, workflow_id: str, inputs: Mapping[str, Any]) -> WorkflowRun:
        """Execute ``workflow_id`` with ``inputs`` and return the run."""
        return await self._executor.run(workflow_id, inputs)
