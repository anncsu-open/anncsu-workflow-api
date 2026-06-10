"""Internationalization for the published API contract (OpenAPI/Swagger).

English is the in-code baseline (the Pydantic field descriptions). Other languages
live in ``locales/<lang>.json`` and are overlaid onto the generated OpenAPI schema
per request. See ADR 0005.
"""

DEFAULT_LANGUAGE = "en"
