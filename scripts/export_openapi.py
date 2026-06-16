"""Export the /v1 OpenAPI contract for the documentation site.

Writes one ``openapi.<lang>.json`` per supported language (the English baseline
plus every catalog in ``app/i18n/locales/``) exactly as the running service
would serve it from ``/anncsu/v1/openapi.json``. The Docs workflow runs this before
``zensical build``, so the published site always reflects the current code;
the files are build artifacts and are not committed.

Usage: uv run python scripts/export_openapi.py [--out-dir docs/api]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.i18n.catalog import (  # noqa: E402
    available_languages,
    load_translations,
)
from app.i18n.openapi import localize_schema  # noqa: E402
from app.main import app  # noqa: E402


def export(out_dir: Path) -> list[Path]:
    """Write one localized contract per language and return the paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    written: list[Path] = []
    for language in available_languages():
        localized = localize_schema(schema, load_translations(language))
        path = out_dir / f"openapi.{language}.json"
        path.write_text(json.dumps(localized, indent=2, ensure_ascii=False) + "\n")
        written.append(path)
    return written


def main(
    out_dir: Annotated[
        Path,
        typer.Option(
            "--out-dir",
            help="Directory the openapi.<lang>.json files are written to",
        ),
    ] = REPO_ROOT / "docs" / "api",
) -> None:
    """Export the localized /v1 OpenAPI contracts for the docs site."""
    for path in export(out_dir):
        typer.echo(str(path))


if __name__ == "__main__":
    typer.run(main)
