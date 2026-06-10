"""Guard: the Italian catalog keys must match real ``<Schema>.<field>`` pairs.

This catches a renamed model or field that would otherwise leave a stale, silently
ignored translation key. English is the in-code baseline, so only non-default
catalogs are checked.
"""

import inspect

from pydantic import BaseModel

from app.i18n.catalog import load_translations
from app.models import workflows


def _valid_keys() -> set[str]:
    keys: set[str] = set()
    for _, obj in inspect.getmembers(workflows, inspect.isclass):
        if issubclass(obj, BaseModel) and obj is not BaseModel:
            keys |= {f"{obj.__name__}.{field}" for field in obj.model_fields}
    return keys


def test_italian_catalog_is_present():
    assert load_translations("it"), "it.json should provide Italian translations"


def test_italian_catalog_keys_match_model_fields():
    unknown = set(load_translations("it")) - _valid_keys()
    assert not unknown, f"it.json has keys not matching any model field: {sorted(unknown)}"


def test_known_field_is_translated():
    assert "CreaIndirizzoCompletoInput.codcom" in load_translations("it")
