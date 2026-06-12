"""RFC 7807 Problem Details exception handlers (ADR 0008).

Domain outcomes never reach these handlers: the spec's ``successCriteria``/
``onFailure`` consume them as data inside the engine. What surfaces here is what
the workflow could not absorb — a step failing its criteria with no matching
action, a transport failure below the Arazzo contract, or an engine error.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.executor.engine import StepFailedError, WorkflowError
from app.ports.transport import TransportError

PROBLEM_CONTENT_TYPE = "application/problem+json"


def _problem(status: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type=PROBLEM_CONTENT_TYPE,
        content={"type": "about:blank", "title": title, "status": status, "detail": detail},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Map executor and transport failures to Problem Details responses."""

    @app.exception_handler(StepFailedError)
    async def step_failed(request: Request, exc: StepFailedError) -> JSONResponse:
        return _problem(422, "Workflow step failed", str(exc))

    @app.exception_handler(TransportError)
    async def transport_failed(request: Request, exc: TransportError) -> JSONResponse:
        return _problem(502, "Upstream ANNCSU call failed", str(exc))

    @app.exception_handler(WorkflowError)
    async def workflow_failed(request: Request, exc: WorkflowError) -> JSONResponse:
        return _problem(500, "Workflow execution error", str(exc))
