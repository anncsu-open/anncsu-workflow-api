#!/usr/bin/env bash
# Regenerate docs/workflows.md from the Arazzo spec.
#
# Renders one section per workflow (heading, summary, per-workflow Mermaid graph,
# steps) via scripts/gen_workflows_doc.py. The generated page is committed; rerun
# this script after changing the Arazzo spec.
#
# (Replaces the previous apitapviz clone-and-run, which labelled every workflow
# "ANNCSU Workflow" and listed all steps in one flat sequence.)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

uv run python "$REPO_ROOT/scripts/gen_workflows_doc.py"
