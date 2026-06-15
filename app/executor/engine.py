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
from app.logging import get_logger
from app.ports.transport import WorkflowTransport

_log = get_logger("app.executor")

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
            await self._run_foreach(workflow, step, ctx)
            await self._execute_step(step, ctx)
            succeeded = self._succeeded(step, ctx)
            action = self._select_action(step, succeeded=succeeded, ctx=ctx)
            _log.debug(
                "workflow.step",
                workflow_id=workflow_id,
                step_id=step.step_id,
                operation_id=step.operation_id,
                status_code=ctx.response.status_code if ctx.response else None,
                succeeded=succeeded,
            )

            if action is None:
                if not succeeded:
                    # The upstream body is the only clue why a step failed; keep it
                    # (redacted by the logging pipeline) so collaudo/PDND failures
                    # are diagnosable instead of a silent 422 (ADR 0014).
                    _log.warning(
                        "workflow.step_failed",
                        workflow_id=workflow_id,
                        step_id=step.step_id,
                        operation_id=step.operation_id,
                        status_code=ctx.response.status_code if ctx.response else None,
                        response_body=ctx.response.body if ctx.response else None,
                    )
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
        # A payload entry that resolves to null (an unset workflow input) is
        # omitted from the request: an explicit null and an absent field can
        # mean different things to the upstream API.
        payload = _without_unset(payload)
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

    async def _run_foreach(self, workflow: Workflow, step: Step, ctx: ExecutionContext) -> None:
        """Run an ``x-executor.foreach`` before its ``before`` step.

        Iterates ``over`` (a list resolved from the context), binds each item to the
        loop variable ``as``, and invokes the named sub-workflow per item. Sequential
        and fail-fast: a failing sub-workflow raises and aborts before the step runs.
        """
        foreach = (workflow.x_executor or {}).get("foreach")
        if not foreach or foreach.get("before") != step.step_id:
            return
        items = evaluate_expression(foreach["over"], ctx) or []
        loop_var = foreach["as"]
        invoke = foreach["invoke"]
        for item in items:
            ctx.loop_vars[loop_var] = item
            sub_inputs = resolve_value(invoke.get("inputs", {}), ctx)
            await self.run(invoke["workflowId"], sub_inputs)
        ctx.loop_vars.pop(loop_var, None)

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
        # x-executor.coalesce resolves outputs across alternative branches (the
        # value of whichever branch actually ran); these keys override/extend the
        # declared outputs. See ADR 0003.
        outputs.update(_coalesced_outputs(workflow, ctx))
        return WorkflowRun(
            workflow_id=workflow.workflow_id,
            status=status,
            outputs=outputs,
            steps=ctx.steps,
        )


def _without_unset(value: Any) -> Any:
    """Drop ``None`` values from request payloads, recursively.

    A nested object whose entries are all unset prunes to nothing and is dropped
    too, so an all-empty block (e.g. ``coordinate`` with no values) never reaches
    the wire as an empty object.
    """
    if isinstance(value, dict):
        pruned: dict[Any, Any] = {}
        for key, item in value.items():
            if item is None:
                continue
            cleaned = _without_unset(item)
            if isinstance(item, dict) and not cleaned:
                continue
            pruned[key] = cleaned
        return pruned
    if isinstance(value, list):
        return [_without_unset(item) for item in value]
    return value


def _coalesced_outputs(workflow: Workflow, ctx: ExecutionContext) -> dict[str, Any]:
    """Resolve each ``x-executor.coalesce`` output to the first non-null branch value."""
    coalesce = (workflow.x_executor or {}).get("coalesce", {})
    resolved: dict[str, Any] = {}
    for name, expressions in coalesce.items():
        resolved[name] = None
        for expr in expressions:
            value = evaluate_expression(expr, ctx)
            if value is not None:
                resolved[name] = value
                break
    return resolved
