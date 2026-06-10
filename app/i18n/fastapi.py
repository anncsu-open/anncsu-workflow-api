"""Wire a localized, versioned OpenAPI document and docs UIs onto a FastAPI app.

Registers ``<prefix>/openapi.json`` (descriptions overlaid per requested language),
``<prefix>/docs`` (Swagger UI) and ``<prefix>/redoc`` (ReDoc). The language is chosen
from the ``lang`` query parameter, then ``Accept-Language``, then the English baseline.
See ADR 0005.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from app.i18n.catalog import available_languages, load_translations
from app.i18n.openapi import localize_schema, resolve_language


def setup_localized_docs(app: FastAPI, *, prefix: str = "/v1") -> None:
    """Mount the localized OpenAPI endpoint and Swagger/ReDoc UIs under ``prefix``."""
    openapi_url = f"{prefix}/openapi.json"

    @app.get(openapi_url, include_in_schema=False)
    def localized_openapi(request: Request) -> JSONResponse:
        language = resolve_language(
            query=request.query_params.get("lang"),
            accept_language=request.headers.get("accept-language"),
            supported=available_languages(),
        )
        schema = localize_schema(app.openapi(), load_translations(language))
        return JSONResponse(schema)

    @app.get(f"{prefix}/docs", include_in_schema=False)
    def swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(openapi_url=openapi_url, title=f"{app.title} — Swagger UI")

    @app.get(f"{prefix}/redoc", include_in_schema=False)
    def redoc() -> HTMLResponse:
        return get_redoc_html(openapi_url=openapi_url, title=f"{app.title} — ReDoc")
