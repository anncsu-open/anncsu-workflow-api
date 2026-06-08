"""Tests for the generic Arazzo workflow engine (loader + step runner).

Covers sequential execution, ``onSuccess``/``onFailure`` + ``goto``/``end``
branching, output capture and workflow-level outputs, and graceful handling of
a failed step with and without a matching ``onFailure`` action. A final
integration test drives the real consolidated ANNCSU spec with a scripted
transport.
"""

from pathlib import Path

import pytest

from app.executor.engine import StepFailedError, WorkflowExecutor
from app.executor.spec import load_spec
from app.ports.transport import Response
from tests.executor.support import ScriptedTransport

SPECS_DIR = Path(__file__).resolve().parent.parent.parent / "specs"
ARAZZO_SPEC = SPECS_DIR / "anncsu-workflow.arazzo.yaml"


def _step(
    step_id, operation_id, *, success_criteria, outputs=None, on_success=None, on_failure=None
):
    step: dict = {
        "stepId": step_id,
        "operationId": operation_id,
        "requestBody": {"contentType": "application/json", "payload": {"x": "$inputs.a"}},
        "successCriteria": [{"condition": c} for c in success_criteria],
    }
    if outputs:
        step["outputs"] = outputs
    if on_success:
        step["onSuccess"] = on_success
    if on_failure:
        step["onFailure"] = on_failure
    return step


# --- linear flow ------------------------------------------------------------


@pytest.fixture
def linear_spec() -> dict:
    return {
        "workflows": [
            {
                "workflowId": "wf",
                "steps": [
                    _step(
                        "s1",
                        "src.op1",
                        success_criteria=["$statusCode == 200"],
                        outputs={"out1": "$response.body.v"},
                    ),
                    _step(
                        "s2",
                        "src.op2",
                        success_criteria=["$statusCode == 200"],
                        outputs={"out2": "$response.body.v"},
                    ),
                ],
                "outputs": {"final": "$steps.s2.outputs.out2"},
            }
        ]
    }


async def test_linear_runs_all_steps_and_resolves_outputs(linear_spec):
    spec = load_spec(linear_spec)
    transport = ScriptedTransport(
        {
            "src.op1": Response(200, {"v": "A"}),
            "src.op2": Response(200, {"v": "B"}),
        }
    )

    run = await WorkflowExecutor(spec, transport).run("wf", {"a": 1})

    assert run.status == "completed"
    assert run.outputs == {"final": "B"}
    assert run.steps["s1"].outputs == {"out1": "A"}
    assert [op for op, _ in transport.calls] == ["src.op1", "src.op2"]


async def test_payload_is_resolved_before_dispatch(linear_spec):
    spec = load_spec(linear_spec)
    transport = ScriptedTransport(
        {
            "src.op1": Response(200, {"v": "A"}),
            "src.op2": Response(200, {"v": "B"}),
        }
    )

    await WorkflowExecutor(spec, transport).run("wf", {"a": 42})

    assert transport.calls[0][1] == {"x": 42}  # $inputs.a resolved


# --- branching: goto / end / fall-through -----------------------------------


@pytest.fixture
def branching_spec() -> dict:
    return {
        "workflows": [
            {
                "workflowId": "wf",
                "steps": [
                    _step(
                        "check",
                        "src.check",
                        success_criteria=["$statusCode == 200"],
                        outputs={"exists": "$response.body.data"},
                        on_success=[
                            {
                                "name": "go-search",
                                "type": "goto",
                                "stepId": "search",
                                "criteria": [{"condition": "$response.body.data == true"}],
                            }
                        ],
                    ),
                    _step(
                        "create",
                        "src.create",
                        success_criteria=["$statusCode == 200"],
                        outputs={"via": "$response.body.via"},
                        on_success=[{"name": "done", "type": "end"}],
                    ),
                    _step(
                        "search",
                        "src.search",
                        success_criteria=["$statusCode == 200"],
                        outputs={"via": "$response.body.via"},
                    ),
                ],
                "outputs": {
                    "via_search": "$steps.search.outputs.via",
                    "via_create": "$steps.create.outputs.via",
                },
            }
        ]
    }


async def test_goto_branch_taken_when_criteria_match(branching_spec):
    spec = load_spec(branching_spec)
    transport = ScriptedTransport(
        {
            "src.check": Response(200, {"data": True}),
            "src.search": Response(200, {"via": "SEARCHED"}),
        }
    )

    run = await WorkflowExecutor(spec, transport).run("wf", {})

    # check -> goto search (create is skipped); falls off the end -> completed
    assert run.status == "completed"
    assert [op for op, _ in transport.calls] == ["src.check", "src.search"]
    assert run.outputs["via_search"] == "SEARCHED"
    assert run.outputs["via_create"] is None


async def test_fall_through_then_end_action(branching_spec):
    spec = load_spec(branching_spec)
    transport = ScriptedTransport(
        {
            "src.check": Response(200, {"data": False}),
            "src.create": Response(200, {"via": "CREATED"}),
        }
    )

    run = await WorkflowExecutor(spec, transport).run("wf", {})

    # check (data false) -> fall through to create -> end
    assert run.status == "ended"
    assert [op for op, _ in transport.calls] == ["src.check", "src.create"]
    assert run.outputs["via_create"] == "CREATED"


# --- failure handling -------------------------------------------------------


async def test_on_failure_end_handles_failed_step():
    spec = load_spec(
        {
            "workflows": [
                {
                    "workflowId": "wf",
                    "steps": [
                        _step(
                            "suppress",
                            "src.suppress",
                            success_criteria=["$statusCode == 200", '$response.body.esito == "0"'],
                            outputs={"esito": "$response.body.esito"},
                            on_failure=[
                                {
                                    "name": "residual",
                                    "type": "end",
                                    "criteria": [{"condition": '$response.body.esito == "23"'}],
                                }
                            ],
                        ),
                    ],
                    "outputs": {"esito": "$steps.suppress.outputs.esito"},
                }
            ]
        }
    )
    transport = ScriptedTransport({"src.suppress": Response(200, {"esito": "23"})})

    run = await WorkflowExecutor(spec, transport).run("wf", {})

    assert run.status == "ended"
    assert run.outputs["esito"] == "23"  # outputs captured even on the failure branch


async def test_failed_step_without_handler_raises():
    spec = load_spec(
        {
            "workflows": [
                {
                    "workflowId": "wf",
                    "steps": [
                        _step("s1", "src.op", success_criteria=['$response.body.esito == "0"']),
                    ],
                }
            ]
        }
    )
    transport = ScriptedTransport({"src.op": Response(200, {"esito": "99"})})

    with pytest.raises(StepFailedError, match="s1"):
        await WorkflowExecutor(spec, transport).run("wf", {})


# --- integration against the real ANNCSU spec -------------------------------


async def test_real_spec_search_skips_accessi_when_no_civico():
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "2000449"}]}
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "ricerca-indirizzo-completo", {"codcom": "H501", "denom_odonimo": "ROMA"}
    )

    # numero_civico is absent -> the onSuccess `end` criteria fires after step 1.
    assert run.status == "ended"
    assert [op for op, _ in transport.calls] == ["anncsu-consultazione.elencoodonimiprogPost"]


async def test_real_spec_create_address_exists_path_resolves_outputs():
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.esisteOdonimoPost": Response(200, {"data": True}),
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "2000449"}]}
            ),
            "anncsu-consultazione.esisteAccessoPost": Response(200, {"data": True}),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200, {"data": [{"prognazacc": "1370588"}]}
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "verifica-e-crea-indirizzo-completo",
        {"codcom": "H501", "denom_odonimo": "ROMA", "numero_civico": "42"},
    )

    # Both odonimo and accesso exist -> the two "cerca" branches run.
    assert run.status == "completed"
    assert run.outputs["progressivo_nazionale_odonimo"] == "2000449"
    assert run.outputs["progressivo_civico"] == "1370588"
