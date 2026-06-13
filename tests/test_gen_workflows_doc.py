"""Tests for the workflows documentation generator (scripts/gen_workflows_doc.py).

The generated page must carry one heading per Arazzo workflow (the gap apitapviz
left), each followed by that workflow's steps and a Mermaid graph. The script is
run exactly as scripts/gen-docs.sh invokes it.
"""

import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "gen_workflows_doc.py"
ARAZZO_SPEC = REPO_ROOT / "specs" / "anncsu-workflow.arazzo.yaml"


def _spec() -> dict:
    return yaml.safe_load(ARAZZO_SPEC.read_text())


def _generate(tmp_path: Path) -> str:
    out = tmp_path / "workflows.md"
    subprocess.run([sys.executable, str(SCRIPT), "--out", str(out)], check=True, cwd=REPO_ROOT)
    return out.read_text()


def test_one_heading_per_workflow(tmp_path):
    markdown = _generate(tmp_path)
    for workflow in _spec()["workflows"]:
        assert f"## {workflow['workflowId']}" in markdown


def test_workflow_section_lists_its_own_steps_under_its_heading(tmp_path):
    sections = _generate(tmp_path).split("\n## ")
    # The aggiorna-accesso-da-progressivo section holds its read-modify-write steps
    # and not steps from other workflows.
    section = next(s for s in sections if s.startswith("aggiorna-accesso-da-progressivo"))
    assert "leggi-accesso" in section
    assert "aggiorna-accesso" in section
    assert "verifica-odonimo" not in section


def test_each_workflow_has_a_mermaid_graph(tmp_path):
    markdown = _generate(tmp_path)
    assert markdown.count("```mermaid") == len(_spec()["workflows"])


def test_summary_and_step_operations_are_rendered(tmp_path):
    sections = _generate(tmp_path).split("\n## ")
    accesso = next(s for s in sections if s.startswith("aggiorna-accesso-da-progressivo"))
    assert "anncsu-consultazione.prognazaccPost" in accesso
    assert "anncsu-accessi.gestioneAnncsuPdnd" in accesso


def test_removed_coordinate_workflow_is_absent(tmp_path):
    assert "aggiorna-coordinate" not in _generate(tmp_path)
