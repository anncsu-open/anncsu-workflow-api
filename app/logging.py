"""Structured logging setup (ADR 0014): structlog with request correlation.

``configure_logging`` wires structlog so application logs and the stdlib/uvicorn
loggers share one pipeline (JSON in production, console in dev). A central
``redact_sensitive`` processor masks tokens/JWT/secrets. A per-request id is bound
via ``contextvars`` (``bind_request_id``) and flows into every event with no
manual threading.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog
from starlette.requests import Request
from starlette.types import ASGIApp

from app.config import Settings

REQUEST_ID_HEADER = "X-Request-ID"

# Substrings that mark a value as sensitive: never log its content.
_SENSITIVE = (
    "authorization",
    "token",
    "jwt",
    "assertion",
    "secret",
    "password",
    "pdnd_client",
    "private_key",
)
_REDACTED = "***"


def redact_sensitive(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor: mask values whose key looks like a credential."""
    for key in list(event_dict):
        if any(token in key.lower() for token in _SENSITIVE):
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib so all logs render through one pipeline.

    Idempotent: safe to call repeatedly (it replaces the root handler), which also
    lets tests reconfigure under a captured stream.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=False,
    )

    # Console format is colorized only when stdout is a terminal, so logs stay
    # plain when redirected to a file or captured in CI.
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    # Route uvicorn's loggers through the root handler (single format).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers[:] = []
        uvicorn_logger.propagate = True


def get_logger(name: str | None = None) -> Any:
    """Return a structlog logger (bound to ``name`` if given)."""
    return structlog.get_logger(name)


@contextmanager
def bind_request_id(request_id: str) -> Iterator[None]:
    """Bind ``request_id`` to the logging context for the duration of the block."""
    with structlog.contextvars.bound_contextvars(request_id=request_id):
        yield


def current_request_id() -> str | None:
    """The request id bound to the current logging context, if any."""
    return structlog.contextvars.get_contextvars().get("request_id")


class RequestContextMiddleware:
    """Bind a correlation id per request, log start/end, echo ``X-Request-ID``.

    Pure-ASGI so the bound contextvars stay active through the route, the engine,
    the transport, and the exception handlers (which run inside ``call_next``).
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request = Request(scope)
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        log = get_logger("app.request")
        status_code = 500
        start = time.perf_counter()

        async def send_wrapper(message: Any) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = message.setdefault("headers", [])
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
            await send(message)

        with bind_request_id(request_id):
            log.info("request.start", method=request.method, path=request.url.path)
            try:
                await self._app(scope, receive, send_wrapper)
            finally:
                log.info(
                    "request.end",
                    method=request.method,
                    path=request.url.path,
                    status_code=status_code,
                    duration_ms=round((time.perf_counter() - start) * 1000, 1),
                )
