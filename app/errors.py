"""RFC 7807 Problem Details: response model and exception handlers (ADR 0008).

Domain outcomes never reach these handlers: the spec's ``successCriteria``/
``onFailure`` consume them as data inside the engine. What surfaces here is what
the workflow could not absorb — an invalid request payload, a step failing its
criteria with no matching action, a transport failure below the Arazzo contract,
or an engine error.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.executor.engine import StepFailedError, WorkflowError
from app.ports.transport import TransportError

PROBLEM_CONTENT_TYPE = "application/problem+json"


class Problem(BaseModel):
    """An RFC 7807 Problem Details body."""

    type: str = Field("about:blank", description="URI reference identifying the problem type")
    title: str = Field(..., description="Short, human-readable summary of the problem type")
    status: int = Field(..., description="HTTP status code")
    detail: str = Field(..., description="Human-readable explanation of this occurrence")
    errors: list[Any] | None = Field(
        None, description="Validation errors (extension member), when applicable"
    )


def _problem(
    status: int, title: str, detail: str, *, errors: list[Any] | None = None
) -> JSONResponse:
    problem = Problem(title=title, status=status, detail=detail, errors=errors)
    return JSONResponse(
        status_code=status,
        media_type=PROBLEM_CONTENT_TYPE,
        content=problem.model_dump(exclude_none=True),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Map validation, executor, and transport failures to Problem Details."""

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(
            422,
            "Invalid request",
            "The request payload failed validation.",
            errors=list(exc.errors()),
        )

    @app.exception_handler(StepFailedError)
    async def step_failed(request: Request, exc: StepFailedError) -> JSONResponse:
        return _problem(422, "Workflow step failed", str(exc))

    @app.exception_handler(TransportError)
    async def transport_failed(request: Request, exc: TransportError) -> JSONResponse:
        return _problem(502, "Upstream ANNCSU call failed", str(exc))

    @app.exception_handler(WorkflowError)
    async def workflow_failed(request: Request, exc: WorkflowError) -> JSONResponse:
        return _problem(500, "Workflow execution error", str(exc))
