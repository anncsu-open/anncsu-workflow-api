"""Pure helpers for localizing the OpenAPI document.

``resolve_language`` picks the language from the ``lang`` query parameter, then the
``Accept-Language`` header, then the default. ``localize_schema`` overlays translated
field descriptions onto ``components.schemas.<Schema>.properties.<field>`` by the
``"<Schema>.<field>"`` catalog key, leaving the English baseline where a key is absent.
Both are pure and perform no I/O.
"""

from __future__ import annotations

import copy
from collections.abc import Collection, Mapping
from typing import Any

from app.i18n import DEFAULT_LANGUAGE


def resolve_language(
    *,
    query: str | None,
    accept_language: str | None,
    supported: Collection[str],
    default: str = DEFAULT_LANGUAGE,
) -> str:
    """Resolve the response language: query param, then Accept-Language, then default."""
    if query:
        lang = query.strip().lower()
        if lang in supported:
            return lang
    if accept_language:
        for lang in _parse_accept_language(accept_language):
            if lang in supported:
                return lang
    return default


def localize_schema(schema: dict[str, Any], translations: Mapping[str, str]) -> dict[str, Any]:
    """Return a copy of ``schema`` with field descriptions overlaid from ``translations``."""
    schemas = schema.get("components", {}).get("schemas")
    if not schemas or not translations:
        return schema

    result = copy.deepcopy(schema)
    for name, model in result["components"]["schemas"].items():
        properties = model.get("properties")
        if not isinstance(properties, dict):
            continue
        for field, prop in properties.items():
            translated = translations.get(f"{name}.{field}")
            if translated is not None and isinstance(prop, dict):
                prop["description"] = translated
    return result


def _parse_accept_language(header: str) -> list[str]:
    """Return primary language subtags from an Accept-Language header, best quality first."""
    ranked: list[tuple[float, int, str]] = []
    for order, part in enumerate(header.split(",")):
        token, _, params = part.strip().partition(";")
        primary = token.strip().lower().split("-")[0]
        if not primary:
            continue
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                quality = 1.0
        ranked.append((quality, order, primary))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [primary for _, _, primary in ranked]
