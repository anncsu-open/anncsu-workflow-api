"""FastAPI application: tooling for the ANNCSU Arazzo workflows.

Development run:  uv run uvicorn app.main:app --reload

Endpoints:
  - GET /health                health check
  - GET /workflows/ui          interactive workflow UI (arazzo-ui)
  - GET /workflows/spec/...     Arazzo spec + source OpenAPI files (StaticFiles)
  - POST /v1/workflows/...     workflow execution (one route per Arazzo workflow)
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from anncsu.common.config import ClientAssertionSettings
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.errors import register_exception_handlers
from app.i18n.fastapi import setup_localized_docs
from app.logging import RequestContextMiddleware, configure_logging
from app.routers import health, visualizer, workflows
from app.routers.workflows import build_workflow_service

# Structured logging + per-request correlation id (ADR 0014), before the app.
configure_logging(settings)

# Specs directory (Arazzo + the 4 OpenAPI files), next to the repo root.
SPECS_DIR = Path(__file__).resolve().parent.parent / "specs"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build PDND auth + the authenticated workflow service once (ADR 0015).

    ``ClientAssertionSettings()`` fails fast if the ``PDND_*`` configuration is
    missing or invalid; tokens are fetched lazily on first request, not here.
    """
    # pydantic-settings loads the required PDND_* fields from the environment;
    # the no-arg call is the intended usage (ty sees them as constructor args).
    assertion_settings = ClientAssertionSettings()  # ty: ignore[missing-argument]
    service, auth_managers, client_manager = build_workflow_service(settings, assertion_settings)
    app.state.workflow_service = service
    app.state.auth_managers = auth_managers
    app.state.client_manager = client_manager
    yield


# The API contract is published under /v1 with a per-request localized OpenAPI
# document (ADR 0005), so the unversioned default docs are disabled here.
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Exposes and visualizes the ANNCSU Arazzo workflows.",
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

# Correlation-id + request logging (outermost middleware: wraps the handlers too).
app.add_middleware(RequestContextMiddleware)

# Versioned, language-aware OpenAPI + Swagger/ReDoc under /v1.
setup_localized_docs(app, prefix="/v1")


@app.get("/", include_in_schema=False)
async def root_index() -> dict[str, str]:
    """Service index: make the docs/OpenAPI entry points discoverable from the root.

    The contract lives under ``/v1`` (the unversioned default docs are disabled),
    so a bare ``GET /`` would otherwise 404 with no hint of where the docs are.
    """
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/v1/docs",
        "redoc": "/v1/redoc",
        "openapi": "/v1/openapi.json",
        "workflows_ui": "/workflows/ui",
        "health": "/health",
        "ready": "/ready",
    }


# Executor/transport failures -> RFC 7807 Problem Details (ADR 0008).
register_exception_handlers(app)

app.include_router(health.router)
app.include_router(visualizer.router)
app.include_router(workflows.router)

# Serve the Arazzo spec and the 4 source OpenAPI files: arazzo-ui (in the browser)
# fetches them from here, resolving the relative sourceDescriptions.
app.mount("/workflows/spec", StaticFiles(directory=SPECS_DIR), name="arazzo-spec")
