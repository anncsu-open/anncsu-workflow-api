"""Execution context: the mutable state a workflow run accumulates.

Runtime expressions read from here: ``$inputs.*``, ``$steps.<id>.outputs.*``,
``$response.body.*`` / ``$statusCode`` (the current step's response), and loop
variables ``$<as>.*`` (populated by ``foreach``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.ports.transport import Response


@dataclass
class StepResult:
    """Outputs captured from a single executed step."""

    outputs: dict[str, Any]


@dataclass
class ExecutionContext:
    """State threaded through a workflow run."""

    inputs: Mapping[str, Any]
    steps: dict[str, StepResult] = field(default_factory=dict)
    response: Response | None = None
    loop_vars: dict[str, Any] = field(default_factory=dict)
