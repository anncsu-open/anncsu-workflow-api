"""Tests for the operationId registry (decision D2: typed SDK per operation).

The registry is the adapter-side contract that binds every ``sourceName.operationId``
referenced by the canonical Arazzo spec to a concrete method on one of the four
authenticated sub-SDK clients. Both directions are pinned here: every operation the
spec uses must be registered, and every registered path must resolve on the real SDK.
"""

from pathlib import Path

import yaml

from app.adapters.anncsu.registry import OPERATION_REGISTRY, resolve_method

SPECS_DIR = Path(__file__).resolve().parent.parent.parent / "specs"
ARAZZO_SPEC = SPECS_DIR / "anncsu-workflow.arazzo.yaml"


def _spec_operation_ids() -> set[str]:
    document = yaml.safe_load(ARAZZO_SPEC.read_text())
    return {
        step["operationId"]
        for workflow in document["workflows"]
        for step in workflow["steps"]
        if "operationId" in step
    }


def test_every_spec_operation_is_registered():
    missing = _spec_operation_ids() - OPERATION_REGISTRY.keys()
    assert not missing, f"operationIds used by the Arazzo spec but unregistered: {missing}"


def test_registry_sources_match_operation_id_prefixes():
    for operation_id, operation in OPERATION_REGISTRY.items():
        assert operation_id.startswith(f"{operation.source}.")


def test_every_registered_method_resolves_on_the_real_sdk():
    """Ground the registry against anncsu-sdk: each dotted path must be callable."""
    from anncsu.accessi import AnncsuAccessi
    from anncsu.coordinate import AnncsuCoordinate
    from anncsu.odonimi import AnncsuOdonimi
    from anncsu.pa import AnncsuConsultazione

    clients = {
        "anncsu-consultazione": AnncsuConsultazione(server_url="https://example.test/v1"),
        "anncsu-odonimi": AnncsuOdonimi(server_url="https://example.test/v1"),
        "anncsu-accessi": AnncsuAccessi(server_url="https://example.test/v1"),
        "anncsu-coordinate": AnncsuCoordinate(server_url="https://example.test/v1"),
    }
    for operation_id, operation in OPERATION_REGISTRY.items():
        method = resolve_method(clients[operation.source], operation.method_path)
        assert callable(method), f"{operation_id} -> {operation.method_path} is not callable"
