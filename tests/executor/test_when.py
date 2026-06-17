"""Tests for the `x-when` step guard: a step whose condition is false is skipped
without dispatching, and execution falls through to the next step (ADR 0021)."""

from app.executor.engine import WorkflowExecutor
from app.executor.spec import load_spec
from app.ports.transport import Response
from tests.executor.support import ScriptedTransport


def _when_spec(condition: str) -> dict:
    return {
        "workflows": [
            {
                "workflowId": "guarded",
                "steps": [
                    {
                        "stepId": "maybe",
                        "operationId": "src.maybe",
                        "x-when": condition,
                        "requestBody": {"contentType": "application/json", "payload": {}},
                        "successCriteria": [{"condition": "$statusCode == 200"}],
                        "outputs": {"v": "$response.body.v"},
                    },
                    {
                        "stepId": "always",
                        "operationId": "src.always",
                        "requestBody": {"contentType": "application/json", "payload": {}},
                        "successCriteria": [{"condition": "$statusCode == 200"}],
                        "outputs": {"w": "$response.body.w"},
                    },
                ],
                "outputs": {"v": "$steps.maybe.outputs.v", "w": "$steps.always.outputs.w"},
            }
        ]
    }


def _transport() -> ScriptedTransport:
    return ScriptedTransport(
        {
            "src.maybe": Response(200, {"v": "ran"}),
            "src.always": Response(200, {"w": "ok"}),
        }
    )


async def test_step_runs_when_x_when_is_true():
    spec = load_spec(_when_spec("$inputs.flag != null"))
    run = await WorkflowExecutor(spec, _transport()).run("guarded", {"flag": "x"})
    assert run.outputs["v"] == "ran"
    assert run.outputs["w"] == "ok"


async def test_step_is_skipped_without_dispatch_when_x_when_is_false():
    spec = load_spec(_when_spec("$inputs.flag != null"))
    transport = _transport()
    run = await WorkflowExecutor(spec, transport).run("guarded", {})  # flag absent -> skipped

    ops = [op for op, _ in transport.calls]
    assert ops == ["src.always"]  # 'maybe' never dispatched
    assert run.outputs["v"] is None  # skipped step captured no outputs
    assert run.outputs["w"] == "ok"


async def test_run_trace_records_executed_steps_only():
    # The per-step trace (ADR 0022) lists executed steps in order, with their upstream
    # status; a step skipped by x-when leaves no trace entry.
    spec = load_spec(_when_spec("$inputs.flag != null"))

    skipped = await WorkflowExecutor(spec, _transport()).run("guarded", {})
    assert [t.step_id for t in skipped.trace] == ["always"]  # 'maybe' skipped
    assert skipped.trace[0].status_code == 200

    ran = await WorkflowExecutor(spec, _transport()).run("guarded", {"flag": "x"})
    assert [t.step_id for t in ran.trace] == ["maybe", "always"]
