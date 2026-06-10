"""Translation catalog: discover locales and load per-language description maps.

Catalog files live in ``app/i18n/locales/<lang>.json`` as flat maps keyed by
``"<SchemaName>.<field>"``. English is the in-code baseline (the Pydantic field
descriptions), so it has no catalog file and ``load_translations("en")`` is empty.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.i18n import DEFAULT_LANGUAGE

_LOCALES_DIR = Path(__file__).parent / "locales"


def available_languages(locales_dir: Path | None = None) -> set[str]:
    """Return the supported languages: the default plus every ``<lang>.json`` present."""
    directory = locales_dir if locales_dir is not None else _LOCALES_DIR
    languages = {DEFAULT_LANGUAGE}
    if directory.is_dir():
        languages |= {path.stem for path in directory.glob("*.json")}
    return languages


def load_translations(lang: str, locales_dir: Path | None = None) -> dict[str, str]:
    """Load the ``<SchemaName>.<field>`` → text map for ``lang`` (empty for the default)."""
    if lang == DEFAULT_LANGUAGE:
        return {}
    directory = locales_dir if locales_dir is not None else _LOCALES_DIR
    path = directory / f"{lang}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
