"""Tests for x-executor.coalesce: resolve a workflow output to the first non-null
value across alternative branches (Arazzo 1.0 cannot express this natively)."""

from pathlib import Path

from app.executor.engine import WorkflowExecutor
from app.executor.spec import load_spec
from app.ports.transport import Response
from tests.executor.support import ScriptedTransport

SPECS_DIR = Path(__file__).resolve().parent.parent.parent / "specs"
ARAZZO_SPEC = SPECS_DIR / "anncsu-workflow.arazzo.yaml"


def _coalesce_spec() -> dict:
    """Two alternative branches; only one runs, coalesce picks the live one."""
    return {
        "workflows": [
            {
                "workflowId": "wf",
                "steps": [
                    {
                        "stepId": "check",
                        "operationId": "src.check",
                        "requestBody": {"contentType": "application/json", "payload": {}},
                        "successCriteria": [{"condition": "$statusCode == 200"}],
                        "outputs": {"found": "$response.body.found"},
                        "onSuccess": [
                            {
                                "name": "go-search",
                                "type": "goto",
                                "stepId": "search",
                                "criteria": [{"condition": "$response.body.found == true"}],
                            }
                        ],
                    },
                    {
                        "stepId": "create",
                        "operationId": "src.create",
                        "requestBody": {"contentType": "application/json", "payload": {}},
                        "successCriteria": [{"condition": "$statusCode == 200"}],
                        "outputs": {"prog": "$response.body.prog"},
                        "onSuccess": [{"name": "end", "type": "end"}],
                    },
                    {
                        "stepId": "search",
                        "operationId": "src.search",
                        "requestBody": {"contentType": "application/json", "payload": {}},
                        "successCriteria": [{"condition": "$statusCode == 200"}],
                        "outputs": {"prog": "$response.body.prog"},
                    },
                ],
                "outputs": {},
                "x-executor": {
                    "coalesce": {
                        "prog": [
                            "$steps.search.outputs.prog",
                            "$steps.create.outputs.prog",
                        ]
                    }
                },
            }
        ]
    }


async def test_coalesce_picks_create_branch_when_search_skipped():
    spec = load_spec(_coalesce_spec())
    transport = ScriptedTransport(
        {
            "src.check": Response(200, {"found": False}),  # -> fall through to create
            "src.create": Response(200, {"prog": "CREATED"}),
        }
    )

    run = await WorkflowExecutor(spec, transport).run("wf", {})

    assert run.outputs["prog"] == "CREATED"


async def test_coalesce_picks_search_branch_when_taken():
    spec = load_spec(_coalesce_spec())
    transport = ScriptedTransport(
        {
            "src.check": Response(200, {"found": True}),  # -> goto search
            "src.search": Response(200, {"prog": "SEARCHED"}),
        }
    )

    run = await WorkflowExecutor(spec, transport).run("wf", {})

    assert run.outputs["prog"] == "SEARCHED"


async def test_real_spec_create_path_coalesces_progressivi():
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            # odonimo does not exist -> create; accesso does not exist -> create
            "anncsu-consultazione.esisteOdonimoPost": Response(200, {"data": False}),
            "anncsu-odonimi.gestioneAnncsuOdonimiPdnd": Response(
                200, {"esito": "0", "dati": [{"progr_nazionale": "2000449"}]}
            ),
            "anncsu-consultazione.esisteAccessoPost": Response(200, {"data": False}),
            "anncsu-accessi.gestioneAnncsuPdnd": Response(
                200, {"esito": "0", "dati": [{"progr_civico": "1370588"}]}
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "verifica-e-crea-indirizzo-completo",
        {"codcom": "H501", "denom_odonimo": "ROMA", "numero_civico": "42"},
    )

    # The "cerca" branches never ran; coalesce resolves from the "crea" branches.
    assert run.outputs["progressivo_nazionale"] == "2000449"
    assert run.outputs["progressivo_civico"] == "1370588"
