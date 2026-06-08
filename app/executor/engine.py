"""The generic Arazzo workflow engine.

Drives a workflow's sequential steps: dispatch each step through the
:class:`WorkflowTransport` port, capture its outputs, evaluate ``successCriteria``,
then follow the first matching ``onSuccess``/``onFailure`` action (``goto``/``end``)
or fall through to the next step. No ANNCSU rules live here — branching and
invariants come from the spec. Output coalescing and ``foreach`` are layered on
separately (they consume the ``x-executor`` block).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.executor.context import ExecutionContext, StepResult
from app.executor.expressions import (
    evaluate_condition,
    evaluate_expression,
    resolve_value,
)
from app.executor.spec import Action, ArazzoSpec, Step, Workflow
from app.ports.transport import WorkflowTransport

# Backstop against a `goto` cycle that never terminates.
MAX_STEPS = 1000


class WorkflowError(Exception):
    """Base class for workflow execution errors."""


class StepFailedError(WorkflowError):
    """A step failed its ``successCriteria`` and no ``onFailure`` action matched."""


class UnknownStepError(WorkflowError):
    """A ``goto`` action targets a step that does not exist."""


@dataclass
class WorkflowRun:
    """The result of executing a workflow."""

    workflow_id: str
    status: str  # "completed" (ran off the end) | "ended" (an `end` action fired)
    outputs: dict[str, Any]
    steps: dict[str, StepResult]


class WorkflowExecutor:
    """Executes Arazzo workflows against an injected async transport."""

    def __init__(self, spec: ArazzoSpec, transport: WorkflowTransport) -> None:
        self._spec = spec
        self._transport = transport

    async def run(self, workflow_id: str, inputs: Mapping[str, Any]) -> WorkflowRun:
        """Run ``workflow_id`` with ``inputs`` and return the :class:`WorkflowRun`."""
        workflow = self._spec.workflow(workflow_id)
        ctx = ExecutionContext(inputs=dict(inputs))
        position = 0

        for _ in range(MAX_STEPS):
            if position >= len(workflow.steps):
                return self._finish(workflow, ctx, "completed")

            step = workflow.steps[position]
            await self._execute_step(step, ctx)
            succeeded = self._succeeded(step, ctx)
            action = self._select_action(step, succeeded=succeeded, ctx=ctx)

            if action is None:
                if not succeeded:
                    raise StepFailedError(
                        f"step {step.step_id!r} failed and no onFailure action matched"
                    )
                position += 1
                continue
            if action.kind == "end":
                return self._finish(workflow, ctx, "ended")
            position = self._goto(workflow, action)

        raise WorkflowError(
            f"workflow {workflow_id!r} exceeded {MAX_STEPS} steps (possible goto loop)"
        )

    async def _execute_step(self, step: Step, ctx: ExecutionContext) -> None:
        if step.operation_id is None:
            raise WorkflowError(f"step {step.step_id!r} has no operationId")
        payload = resolve_value(step.payload, ctx) if step.payload is not None else None
        ctx.response = await self._transport.dispatch(
            operation_id=step.operation_id,
            payload=payload,
            content_type=step.content_type,
        )
        if step.outputs:
            ctx.steps[step.step_id] = StepResult(
                outputs={
                    name: evaluate_expression(expr, ctx) for name, expr in step.outputs.items()
                }
            )

    @staticmethod
    def _succeeded(step: Step, ctx: ExecutionContext) -> bool:
        return all(evaluate_condition(c, ctx) for c in step.success_criteria)

    @staticmethod
    def _select_action(step: Step, *, succeeded: bool, ctx: ExecutionContext) -> Action | None:
        actions = step.on_success if succeeded else step.on_failure
        for action in actions:
            if all(evaluate_condition(c, ctx) for c in action.criteria):
                return action
        return None

    @staticmethod
    def _goto(workflow: Workflow, action: Action) -> int:
        position = workflow.position(action.step_id) if action.step_id else None
        if position is None:
            raise UnknownStepError(f"goto targets unknown step {action.step_id!r}")
        return position

    @staticmethod
    def _finish(workflow: Workflow, ctx: ExecutionContext, status: str) -> WorkflowRun:
        outputs = {name: evaluate_expression(expr, ctx) for name, expr in workflow.outputs.items()}
        return WorkflowRun(
            workflow_id=workflow.workflow_id,
            status=status,
            outputs=outputs,
            steps=ctx.steps,
        )
