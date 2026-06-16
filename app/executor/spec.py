"""Arazzo spec loader: parse the canonical YAML into a typed, indexed model.

The engine reads from these immutable structures rather than from raw dicts. Only
the slice the engine needs is modelled (steps, criteria, actions, outputs); the
``x-executor`` block is carried verbatim for the coalesce/foreach stages.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Action:
    """An ``onSuccess``/``onFailure`` action (``goto`` a step or ``end``)."""

    name: str
    kind: str  # "goto" | "end"
    step_id: str | None = None
    criteria: tuple[str, ...] = ()


@dataclass(frozen=True)
class Step:
    """A single workflow step bound to one API operation."""

    step_id: str
    operation_id: str | None
    content_type: str | None
    payload: Any
    success_criteria: tuple[str, ...]
    on_success: tuple[Action, ...]
    on_failure: tuple[Action, ...]
    outputs: Mapping[str, str]
    # `x-when`: when set and false at runtime, the step is skipped without
    # dispatching and execution falls through to the next step (ADR 0021).
    condition: str | None = None


@dataclass(frozen=True)
class Workflow:
    """A workflow: an ordered sequence of steps plus its outputs and extensions."""

    workflow_id: str
    steps: tuple[Step, ...]
    outputs: Mapping[str, str]
    x_executor: Mapping[str, Any] | None = None

    def position(self, step_id: str) -> int | None:
        """Return the index of ``step_id`` in the step sequence, or ``None``."""
        for index, step in enumerate(self.steps):
            if step.step_id == step_id:
                return index
        return None


@dataclass(frozen=True)
class ArazzoSpec:
    """An indexed Arazzo document."""

    workflows: Mapping[str, Workflow]

    def workflow(self, workflow_id: str) -> Workflow:
        """Return the workflow by id, raising ``KeyError`` if unknown."""
        return self.workflows[workflow_id]


def load_spec(source: Mapping[str, Any] | str | Path) -> ArazzoSpec:
    """Load and index an Arazzo spec from a mapping or a YAML file path."""
    if isinstance(source, (str, Path)):
        document: Mapping[str, Any] = _read_yaml(Path(source))
    else:
        document = source
    workflows = {raw["workflowId"]: _parse_workflow(raw) for raw in document.get("workflows", [])}
    return ArazzoSpec(workflows=workflows)


def _read_yaml(path: Path) -> Mapping[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _parse_workflow(raw: Mapping[str, Any]) -> Workflow:
    return Workflow(
        workflow_id=raw["workflowId"],
        steps=tuple(_parse_step(step) for step in raw.get("steps", [])),
        outputs=dict(raw.get("outputs", {})),
        x_executor=raw.get("x-executor"),
    )


def _parse_step(raw: Mapping[str, Any]) -> Step:
    request_body = raw.get("requestBody") or {}
    return Step(
        step_id=raw["stepId"],
        operation_id=raw.get("operationId"),
        content_type=request_body.get("contentType"),
        payload=request_body.get("payload"),
        success_criteria=_parse_criteria(raw.get("successCriteria", [])),
        on_success=tuple(_parse_action(a) for a in raw.get("onSuccess", [])),
        on_failure=tuple(_parse_action(a) for a in raw.get("onFailure", [])),
        outputs=dict(raw.get("outputs", {})),
        condition=raw.get("x-when"),
    )


def _parse_action(raw: Mapping[str, Any]) -> Action:
    return Action(
        name=raw.get("name", ""),
        kind=raw["type"],
        step_id=raw.get("stepId"),
        criteria=_parse_criteria(raw.get("criteria", [])),
    )


def _parse_criteria(raw: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(item["condition"] for item in raw)
