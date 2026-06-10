"""FastAPI application: tooling for the ANNCSU Arazzo workflows.

Development run:  uv run uvicorn app.main:app --reload

Endpoints:
  - GET /health                health check
  - GET /workflows/ui          interactive workflow UI (arazzo-ui)
  - GET /workflows/spec/...     Arazzo spec + source OpenAPI files (StaticFiles)
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.i18n.fastapi import setup_localized_docs
from app.routers import visualizer

# Specs directory (Arazzo + the 4 OpenAPI files), next to the repo root.
SPECS_DIR = Path(__file__).resolve().parent.parent / "specs"

# The API contract is published under /v1 with a per-request localized OpenAPI
# document (ADR 0005), so the unversioned default docs are disabled here.
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Exposes and visualizes the ANNCSU Arazzo workflows.",
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
)

# Versioned, language-aware OpenAPI + Swagger/ReDoc under /v1.
# Domain endpoints (the workflow-execution routes) attach under /v1 in a later phase.
setup_localized_docs(app, prefix="/v1")

app.include_router(visualizer.router)

# Serve the Arazzo spec and the 4 source OpenAPI files: arazzo-ui (in the browser)
# fetches them from here, resolving the relative sourceDescriptions.
app.mount("/workflows/spec", StaticFiles(directory=SPECS_DIR), name="arazzo-spec")


@app.get("/health", tags=["health"], summary="Health check")
async def health() -> dict[str, str]:
    """Service status."""
    return {"status": "ok"}
