"""Guards on the Italian catalog.

The catalog has two kinds of key:
- ``<Schema>.<field>`` keys for model field descriptions — must match a real model
  field, or a rename would leave a stale, silently ignored translation;
- free-text keys (the English source string of an operation summary/description or
  an example summary) — must appear verbatim in the generated OpenAPI document,
  or the English text changed and the translation went stale.

English is the in-code baseline, so only non-default catalogs are checked.
"""

import inspect
import re

from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.i18n.catalog import load_translations
from app.main import app
from app.models import workflows

# A field key looks like ``CreaIndirizzoCompletoInput.codcom`` (the field part may be
# mixedCase, e.g. ``AccessoResult.coordX``); free text contains spaces and does not match.
_FIELD_KEY = re.compile(r"^[A-Z][A-Za-z0-9]*\.[a-zA-Z][A-Za-z0-9_]*$")


def _field_keys() -> set[str]:
    keys: set[str] = set()
    for _, obj in inspect.getmembers(workflows, inspect.isclass):
        if issubclass(obj, BaseModel) and obj is not BaseModel:
            keys |= {f"{obj.__name__}.{field}" for field in obj.model_fields}
    return keys


def _openapi_free_text() -> set[str]:
    """Every operation summary/description and example summary in the /v1 contract."""
    doc = TestClient(app).get("/v1/openapi.json").json()
    text: set[str] = set()
    for path_item in doc["paths"].values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            text.update(operation.get(k) for k in ("summary", "description") if operation.get(k))
            content = operation.get("requestBody", {}).get("content", {})
            for media in content.values():
                for example in media.get("examples", {}).values():
                    if example.get("summary"):
                        text.add(example["summary"])
    return text


def test_italian_catalog_is_present():
    assert load_translations("it"), "it.json should provide Italian translations"


def test_italian_field_keys_match_model_fields():
    field_keys = {k for k in load_translations("it") if _FIELD_KEY.match(k)}
    unknown = field_keys - _field_keys()
    assert not unknown, f"it.json has field keys not matching any model field: {sorted(unknown)}"


def test_italian_free_text_keys_exist_in_the_openapi():
    free_text = {k for k in load_translations("it") if not _FIELD_KEY.match(k)}
    stale = free_text - _openapi_free_text()
    assert not stale, f"it.json free-text keys not found in the OpenAPI (stale?): {sorted(stale)}"


def test_known_field_is_translated():
    assert "CreaIndirizzoCompletoInput.codcom" in load_translations("it")
