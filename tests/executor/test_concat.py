"""Tests for x-concat: compose a request payload value from parts. The expression
language has no string concatenation; x-concat builds the full odonimo name
(DUG + " " + DENOMUFF) that esisteOdonimo requires (ADR 0019)."""

from app.executor.engine import WorkflowExecutor
from app.executor.spec import load_spec
from app.ports.transport import Response
from tests.executor.support import ScriptedTransport


def _concat_spec(parts: list) -> dict:
    return {
        "workflows": [
            {
                "workflowId": "wf",
                "steps": [
                    {
                        "stepId": "only",
                        "operationId": "src.op",
                        "requestBody": {
                            "contentType": "application/json",
                            "payload": {"denom": {"x-concat": parts}},
                        },
                        "successCriteria": [{"condition": "$statusCode == 200"}],
                    }
                ],
            }
        ]
    }


async def test_x_concat_joins_inputs_and_literals():
    spec = load_spec(_concat_spec(["$inputs.dug", " ", "$inputs.denom"]))
    transport = ScriptedTransport({"src.op": Response(200, {})})

    await WorkflowExecutor(spec, transport).run("wf", {"dug": "VIA", "denom": "AURELIA"})

    assert transport.calls[0][1] == {"denom": "VIA AURELIA"}


async def test_x_concat_treats_null_operand_as_empty_string():
    spec = load_spec(_concat_spec(["$inputs.missing", "$inputs.denom"]))
    transport = ScriptedTransport({"src.op": Response(200, {})})

    await WorkflowExecutor(spec, transport).run("wf", {"denom": "AURELIA"})

    assert transport.calls[0][1] == {"denom": "AURELIA"}
