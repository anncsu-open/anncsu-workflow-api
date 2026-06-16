"""Tests for x-executor.foreach: before the `before` step, iterate `over`, bind the
loop variable, and invoke a sub-workflow per item — sequentially and fail-fast."""

from pathlib import Path

import pytest

from app.executor.engine import StepFailedError, WorkflowExecutor
from app.executor.spec import load_spec
from app.ports.transport import Response
from tests.executor.support import ScriptedTransport

SPECS_DIR = Path(__file__).resolve().parent.parent.parent / "specs"
ARAZZO_SPEC = SPECS_DIR / "anncsu-workflow.arazzo.yaml"


def _foreach_spec() -> dict:
    return {
        "workflows": [
            {
                "workflowId": "parent",
                "steps": [
                    {
                        "stepId": "list",
                        "operationId": "src.list",
                        "requestBody": {"contentType": "application/json", "payload": {}},
                        "successCriteria": [{"condition": "$statusCode == 200"}],
                        "outputs": {"items": "$response.body.items"},
                    },
                    {
                        "stepId": "final",
                        "operationId": "src.final",
                        "requestBody": {"contentType": "application/json", "payload": {}},
                        "successCriteria": [{"condition": "$statusCode == 200"}],
                        "outputs": {"done": "$response.body.ok"},
                    },
                ],
                "outputs": {"done": "$steps.final.outputs.done"},
                "x-executor": {
                    "foreach": {
                        "over": "$steps.list.outputs.items",
                        "as": "item",
                        "before": "final",
                        "invoke": {"workflowId": "sub", "inputs": {"civ": "$item.id"}},
                    }
                },
            },
            {
                "workflowId": "sub",
                "steps": [
                    {
                        "stepId": "do",
                        "operationId": "src.sub",
                        "requestBody": {
                            "contentType": "application/json",
                            "payload": {"id": "$inputs.civ"},
                        },
                        "successCriteria": [
                            {"condition": "$statusCode == 200"},
                            {"condition": '$response.body.esito == "0"'},
                        ],
                        "outputs": {"esito": "$response.body.esito"},
                    }
                ],
            },
        ]
    }


async def test_foreach_invokes_subworkflow_per_item_before_the_step():
    spec = load_spec(_foreach_spec())
    transport = ScriptedTransport(
        {
            "src.list": Response(200, {"items": [{"id": "1"}, {"id": "2"}]}),
            "src.sub": Response(200, {"esito": "0"}),
            "src.final": Response(200, {"ok": True}),
        }
    )

    run = await WorkflowExecutor(spec, transport).run("parent", {})

    assert run.status == "completed"
    assert [op for op, _ in transport.calls] == ["src.list", "src.sub", "src.sub", "src.final"]
    # The loop variable feeds each sub-workflow's input, in order.
    assert transport.calls[1][1] == {"id": "1"}
    assert transport.calls[2][1] == {"id": "2"}


async def test_foreach_is_fail_fast_and_skips_the_step():
    spec = load_spec(_foreach_spec())
    transport = ScriptedTransport(
        {
            "src.list": Response(200, {"items": [{"id": "1"}]}),
            "src.sub": Response(200, {"esito": "9"}),  # sub-workflow fails
            "src.final": Response(200, {"ok": True}),
        }
    )

    with pytest.raises(StepFailedError):
        await WorkflowExecutor(spec, transport).run("parent", {})

    # The `before` step must not run if any iteration failed.
    assert "src.final" not in [op for op, _ in transport.calls]


# Live contract (collaudo): the odonimo S (suppression) operation returns HTTP 200
# with a RispostaOperazione carrying idRichiesta + dati (the suppressed odonimo, with
# data_fine_valid_amm set) and NO `esito` field — unlike the I (create) operation,
# which does return esito == "0". Success must hinge on HTTP 200, not on esito.
_SUPPRESS_ODONIMO_OK = Response(
    200,
    {
        "idRichiesta": "317922",
        "dati": [
            {
                "codcom": "H501",
                "progr_nazionale": "1342715",
                "dug": "VIA",
                "data_fine_valid_amm": "16/06/2026",
            }
        ],
    },
)


async def test_real_spec_suppress_odonimo_accepts_the_real_s_response_without_esito():
    # CONTRACT (collaudo-observed): the odonimo S operation reports success as HTTP 200
    # + idRichiesta + dati, with no `esito`; the workflow must not require esito == "0".
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "1342715", "duf": "VIA ROMA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(200, {"data": []}),
            "anncsu-odonimi.gestioneAnncsuOdonimiPdnd": _SUPPRESS_ODONIMO_OK,
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "sopprimi-odonimo-completo",
        {"codcom": "H501", "denom_odonimo": "ROMA", "data_soppressione": "16/06/2026"},
    )

    assert run.status == "completed"
    assert run.outputs["esito"]["idRichiesta"] == "317922"


async def test_real_spec_suppress_odonimo_suppresses_accessi_first():
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "2000449", "duf": "VIA ROMA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200, {"data": [{"prognazacc": "a1"}, {"prognazacc": "a2"}]}
            ),
            "anncsu-accessi.gestioneAnncsuPdnd": Response(200, {"esito": "0"}),
            "anncsu-odonimi.gestioneAnncsuOdonimiPdnd": _SUPPRESS_ODONIMO_OK,
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "sopprimi-odonimo-completo",
        {"codcom": "H501", "denom_odonimo": "ROMA", "data_soppressione": "08/10/2024"},
    )

    assert run.status == "completed"
    ops = [op for op, _ in transport.calls]
    assert ops == [
        "anncsu-consultazione.elencoodonimiprogPost",
        "anncsu-consultazione.elencoaccessiprogPost",
        "anncsu-accessi.gestioneAnncsuPdnd",  # sopprimi-accesso for a1
        "anncsu-accessi.gestioneAnncsuPdnd",  # sopprimi-accesso for a2
        "anncsu-odonimi.gestioneAnncsuOdonimiPdnd",  # then sopprimi-odonimo
    ]
    # Each accesso suppression carried its own progr_civico from the loop variable.
    suppress_calls = [p for op, p in transport.calls if op == "anncsu-accessi.gestioneAnncsuPdnd"]
    assert suppress_calls[0]["richiesta"]["accesso"]["progr_civico"] == "a1"
    assert suppress_calls[1]["richiesta"]["accesso"]["progr_civico"] == "a2"


async def test_real_spec_suppress_odonimo_with_no_accessi_still_suppresses():
    # ANNCSU answers 404 when the odonimo has zero accessi (the same "zero results =
    # 404" convention as the searches, ADR 0014); the suppression must treat that as
    # an empty list and proceed straight to suppressing the odonimo, not fail the
    # elenca-accessi step. Regression: surfaced by the odonimo create/suppress dry-run.
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "1342715", "duf": "VIA ROMA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                404, {"title": "non trovati accessi per valori forniti"}
            ),
            "anncsu-odonimi.gestioneAnncsuOdonimiPdnd": _SUPPRESS_ODONIMO_OK,
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "sopprimi-odonimo-completo",
        {"codcom": "H501", "denom_odonimo": "ROMA", "data_soppressione": "08/10/2024"},
    )

    assert run.status == "completed"
    ops = [op for op, _ in transport.calls]
    assert ops == [
        "anncsu-consultazione.elencoodonimiprogPost",
        "anncsu-consultazione.elencoaccessiprogPost",
        "anncsu-odonimi.gestioneAnncsuOdonimiPdnd",  # straight to the odonimo, no accessi
    ]
    assert "anncsu-accessi.gestioneAnncsuPdnd" not in ops  # nothing to suppress
