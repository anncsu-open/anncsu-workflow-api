"""Pure helpers for localizing the OpenAPI document.

``resolve_language`` picks the language from the ``lang`` query parameter, then the
``Accept-Language`` header, then the default. ``localize_schema`` overlays
translations from the catalog, leaving the English baseline where a key is absent:

- field descriptions, by the ``"<Schema>.<field>"`` catalog key;
- operation ``summary``/``description`` and request-example ``summary``, by their
  **English source string** (gettext-style), so free text in the contract is
  localized too.

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
    """Return a copy of ``schema`` with translations overlaid from ``translations``."""
    if not translations:
        return schema

    result = copy.deepcopy(schema)
    _localize_field_descriptions(result, translations)
    _localize_free_text(result, translations)
    return result


def _localize_field_descriptions(schema: dict[str, Any], translations: Mapping[str, str]) -> None:
    """Overlay ``components.schemas.<Schema>.properties.<field>`` descriptions by key."""
    schemas = schema.get("components", {}).get("schemas")
    if not isinstance(schemas, dict):
        return
    for name, model in schemas.items():
        properties = model.get("properties")
        if not isinstance(properties, dict):
            continue
        for field, prop in properties.items():
            translated = translations.get(f"{name}.{field}")
            if translated is not None and isinstance(prop, dict):
                prop["description"] = translated


def _localize_free_text(schema: dict[str, Any], translations: Mapping[str, str]) -> None:
    """Translate operation summary/description and example summaries by source string."""
    for path_item in schema.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            _translate_in_place(operation, "summary", translations)
            _translate_in_place(operation, "description", translations)
            for example in _request_examples(operation):
                _translate_in_place(example, "summary", translations)


def _request_examples(operation: dict[str, Any]) -> list[dict[str, Any]]:
    content = operation.get("requestBody", {}).get("content", {})
    examples: list[dict[str, Any]] = []
    for media_type in content.values():
        for example in (media_type or {}).get("examples", {}).values():
            if isinstance(example, dict):
                examples.append(example)
    return examples


def _translate_in_place(obj: dict[str, Any], key: str, translations: Mapping[str, str]) -> None:
    value = obj.get(key)
    if isinstance(value, str) and value in translations:
        obj[key] = translations[value]


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
