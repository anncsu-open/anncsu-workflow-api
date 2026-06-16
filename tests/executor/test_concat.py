"""Tests for x-concat and x-join: compose a request payload value from parts.

The expression language has no string concatenation. ``x-concat`` builds the full
odonimo name (DUG + " " + DENOMUFF) that esisteOdonimo requires (ADR 0019).
``x-join`` joins parts with a separator but skips null/empty parts (and their
separators), so it builds ANNCSU's ``accparz`` from civico + optional esponente:
``"42/A"`` with both, ``"42"`` with the civic alone (no dangling "/", which would
break the contains-match search)."""

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


def _join_spec(parts: list) -> dict:
    # First operand is the separator; the rest are the parts to join.
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
                            "payload": {"accparz": {"x-join": parts}},
                        },
                        "successCriteria": [{"condition": "$statusCode == 200"}],
                    }
                ],
            }
        ]
    }


async def test_x_join_joins_parts_with_separator():
    spec = load_spec(_join_spec(["/", "$inputs.civico", "$inputs.esp"]))
    transport = ScriptedTransport({"src.op": Response(200, {})})

    await WorkflowExecutor(spec, transport).run("wf", {"civico": "42", "esp": "A"})

    assert transport.calls[0][1] == {"accparz": "42/A"}


async def test_x_join_skips_absent_part_without_trailing_separator():
    # No esponente -> just the civico, no dangling "/" (which would break the
    # ANNCSU contains-match search).
    spec = load_spec(_join_spec(["/", "$inputs.civico", "$inputs.esp"]))
    transport = ScriptedTransport({"src.op": Response(200, {})})

    await WorkflowExecutor(spec, transport).run("wf", {"civico": "42"})

    assert transport.calls[0][1] == {"accparz": "42"}


async def test_x_join_treats_empty_string_part_as_absent():
    spec = load_spec(_join_spec(["/", "$inputs.civico", "$inputs.esp"]))
    transport = ScriptedTransport({"src.op": Response(200, {})})

    await WorkflowExecutor(spec, transport).run("wf", {"civico": "42", "esp": ""})

    assert transport.calls[0][1] == {"accparz": "42"}
