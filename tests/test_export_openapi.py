"""Tests for ``scripts/export_openapi.py``: the docs-site OpenAPI export.

The Docs workflow runs the script before ``zensical build`` so the published
site always carries the contract generated from the current code (one JSON per
supported language). The script is exercised exactly as CI invokes it.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "export_openapi.py"

WORKFLOW_PATHS = (
    "/v1/workflows/verifica-e-crea-indirizzo-completo",
    "/v1/workflows/sopprimi-odonimo-completo",
    "/v1/workflows/ricerca-indirizzo-completo",
)


def _export(out_dir: Path) -> dict[str, dict]:
    subprocess.run(
        [sys.executable, str(SCRIPT), "--out-dir", str(out_dir)],
        check=True,
        cwd=REPO_ROOT,
    )
    return {
        lang: json.loads((out_dir / f"openapi.{lang}.json").read_text()) for lang in ("en", "it")
    }


def test_export_writes_one_contract_per_language(tmp_path):
    documents = _export(tmp_path)

    for lang, document in documents.items():
        assert document["openapi"].startswith("3."), lang
        for path in WORKFLOW_PATHS:
            assert path in document["paths"], f"{path} missing from {lang} contract"


def test_export_localizes_the_italian_contract(tmp_path):
    documents = _export(tmp_path)

    codcom = {
        lang: doc["components"]["schemas"]["CreaIndirizzoCompletoInput"]["properties"]["codcom"]
        for lang, doc in documents.items()
    }
    assert codcom["en"]["description"] == "Belfiore municipality code (codcom)"
    assert codcom["it"]["description"] == "Codice Belfiore del comune"
