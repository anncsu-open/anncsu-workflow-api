"""Conformance net: every payload key the Arazzo spec sends must exist in the SDK.

The SDK request models silently drop unknown keys at serialization, so a spec
payload field that does not exist in the ANNCSU OpenAPI never reaches the wire
— a silent contract bug. This pins every write payload in the canonical spec
against the anncsu-sdk request models (which are generated from the same OAS).
"""

from pathlib import Path

import yaml
from anncsu.accessi import models as accessi_models
from anncsu.coordinate import models as coordinate_models
from anncsu.odonimi import models as odonimi_models

SPECS_DIR = Path(__file__).resolve().parent.parent / "specs"
ARAZZO_SPEC = SPECS_DIR / "anncsu-workflow.arazzo.yaml"

# operationId prefix -> (model of `richiesta`, model of `richiesta.accesso` or None)
REQUEST_MODELS = {
    "anncsu-accessi": (accessi_models.Richiesta, accessi_models.Accesso),
    "anncsu-coordinate": (coordinate_models.Richiesta, coordinate_models.Accesso),
    "anncsu-odonimi": (odonimi_models.Richiesta, None),
}


def _write_steps():
    document = yaml.safe_load(ARAZZO_SPEC.read_text())
    for workflow in document["workflows"]:
        for step in workflow["steps"]:
            source = step.get("operationId", "").split(".")[0]
            payload = (step.get("requestBody") or {}).get("payload") or {}
            if source in REQUEST_MODELS and "richiesta" in payload:
                yield workflow["workflowId"], step["stepId"], source, payload["richiesta"]


def test_every_spec_payload_key_exists_in_the_sdk_models():
    problems = []
    for workflow_id, step_id, source, richiesta in _write_steps():
        richiesta_model, accesso_model = REQUEST_MODELS[source]
        unknown = set(richiesta) - set(richiesta_model.model_fields)
        problems += [f"{workflow_id}/{step_id}: richiesta.{k}" for k in sorted(unknown)]
        if accesso_model is not None and isinstance(richiesta.get("accesso"), dict):
            unknown = set(richiesta["accesso"]) - set(accesso_model.model_fields)
            problems += [f"{workflow_id}/{step_id}: accesso.{k}" for k in sorted(unknown)]
    assert not problems, f"spec payload keys unknown to the SDK (silently dropped): {problems}"
