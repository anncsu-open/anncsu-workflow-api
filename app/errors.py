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
from app.logging import current_request_id, get_logger
from app.models.workflows import StepMessage
from app.ports.transport import TransportError

PROBLEM_CONTENT_TYPE = "application/problem+json"

_log = get_logger("app.error")


class Problem(BaseModel):
    """An RFC 7807 Problem Details body."""

    type: str = Field("about:blank", description="URI reference identifying the problem type")
    title: str = Field(..., description="Short, human-readable summary of the problem type")
    status: int = Field(..., description="HTTP status code")
    detail: str = Field(..., description="Human-readable explanation of this occurrence")
    request_id: str | None = Field(
        None, description="Correlation id of the request (extension member)"
    )
    errors: list[Any] | None = Field(
        None, description="Validation errors (extension member), when applicable"
    )
    upstream: dict[str, Any] | None = Field(
        None,
        description="The failing upstream ANNCSU response (status + body), when a step failed",
    )
    messages: list[StepMessage] | None = Field(
        None,
        description="Partial per-step trace up to the failure (extension member, ADR 0022)",
    )


def _problem(status: int, title: str, detail: str, **extensions: Any) -> JSONResponse:
    # `extensions` are the optional RFC 7807 extension members (errors, upstream,
    # messages); they flow into and are validated by the Problem model.
    problem = Problem(
        title=title,
        status=status,
        detail=detail,
        request_id=current_request_id(),
        **extensions,
    )
    content = problem.model_dump(exclude_none=True)
    # exclude_none drops the optional top-level members (errors/upstream/messages/...)
    # but also recurses into the per-step messages and strips their null status/title/
    # detail; keep them as null there, consistent with the success-path messages.
    if problem.messages is not None:
        content["messages"] = [message.model_dump() for message in problem.messages]
    return JSONResponse(
        status_code=status,
        media_type=PROBLEM_CONTENT_TYPE,
        content=content,
    )


def _summarize_upstream(body: Any) -> str | None:
    """Pull a human-readable reason from an ANNCSU error body, if there is one.

    ANNCSU surfaces the reason under different keys: ``messaggio`` (gestione ops),
    ``detail``/``title`` (problem+json on 4xx). Returns ``None`` when the body has
    no obvious message (the raw body is still attached as the ``upstream`` member).
    """
    if isinstance(body, dict):
        for key in ("detail", "messaggio", "message", "title"):
            value = body.get(key)
            if value:
                return str(value)
    elif isinstance(body, str) and body.strip():
        return body
    return None


def register_exception_handlers(app: FastAPI) -> None:
    """Map validation, executor, and transport failures to Problem Details."""

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Keep only the JSON-safe keys: pydantic's ctx may carry the original
        # exception object (e.g. from model validators).
        errors = [
            {"loc": list(error.get("loc", ())), "msg": error.get("msg"), "type": error.get("type")}
            for error in exc.errors()
        ]
        return _problem(
            422,
            "Invalid request",
            "The request payload failed validation.",
            errors=errors,
        )

    @app.exception_handler(StepFailedError)
    async def step_failed(request: Request, exc: StepFailedError) -> JSONResponse:
        _log.warning(
            "workflow.step_failed",
            path=request.url.path,
            detail=str(exc),
            upstream_status=exc.status_code,
        )
        # Export the real upstream reason, not just "step X failed": enrich the
        # detail with the ANNCSU message and attach the raw upstream response.
        detail = str(exc)
        reason = _summarize_upstream(exc.body)
        if reason:
            detail = f"{detail}: {reason}"
        upstream = (
            {"status": exc.status_code, "body": exc.body} if exc.status_code is not None else None
        )
        messages = StepMessage.from_trace(exc.trace) or None
        return _problem(422, "Workflow step failed", detail, upstream=upstream, messages=messages)

    @app.exception_handler(TransportError)
    async def transport_failed(request: Request, exc: TransportError) -> JSONResponse:
        _log.error("transport.failed", path=request.url.path, detail=str(exc))
        messages = StepMessage.from_trace(exc.trace) or None
        return _problem(502, "Upstream ANNCSU call failed", str(exc), messages=messages)

    @app.exception_handler(WorkflowError)
    async def workflow_failed(request: Request, exc: WorkflowError) -> JSONResponse:
        _log.error("workflow.error", path=request.url.path, detail=str(exc))
        return _problem(500, "Workflow execution error", str(exc))
