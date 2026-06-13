"""Tests for the Arazzo runtime-expression evaluator.

The evaluator covers the finite expression surface used by the ANNCSU workflows:
references (`$inputs`, `$steps.<id>.outputs`, `$response.body`, `$statusCode`,
loop variables), path navigation (dotted keys, `[index]`, `.length`), payload
resolution, and conditions (comparisons against literals).
"""

import pytest

from app.executor.context import ExecutionContext, StepResult
from app.executor.expressions import (
    evaluate_condition,
    evaluate_expression,
    resolve_value,
)
from app.ports.transport import Response


@pytest.fixture
def ctx() -> ExecutionContext:
    """A context with inputs, one prior step's outputs, and a current response."""
    return ExecutionContext(
        inputs={"codcom": "H501", "denom_odonimo": "ROMA", "numero_civico": None},
        steps={
            "cerca-odonimo": StepResult(outputs={"progressivo_nazionale": "2000449"}),
        },
        response=Response(
            status_code=200,
            body={
                "esito": "0",
                "data": [{"prognaz": "2000449"}, {"prognaz": "2000450"}],
                "dati": [{"progr_civico": "1370588"}],
                "flag": True,
            },
            headers={"x-correlation-id": "abc"},
        ),
    )


# --- references -------------------------------------------------------------


def test_inputs_reference(ctx):
    assert evaluate_expression("$inputs.codcom", ctx) == "H501"


def test_missing_input_is_none(ctx):
    assert evaluate_expression("$inputs.nonexistent", ctx) is None


def test_status_code_reference(ctx):
    assert evaluate_expression("$statusCode", ctx) == 200


def test_response_body_scalar(ctx):
    assert evaluate_expression("$response.body.esito", ctx) == "0"


def test_response_body_index_then_key(ctx):
    assert evaluate_expression("$response.body.data[0].prognaz", ctx) == "2000449"
    assert evaluate_expression("$response.body.dati[0].progr_civico", ctx) == "1370588"


def test_length_pseudo_property(ctx):
    assert evaluate_expression("$response.body.data.length", ctx) == 2


def test_response_header_reference(ctx):
    assert evaluate_expression("$response.headers.x-correlation-id", ctx) == "abc"


def test_steps_outputs_reference(ctx):
    expr = "$steps.cerca-odonimo.outputs.progressivo_nazionale"
    assert evaluate_expression(expr, ctx) == "2000449"


def test_unknown_step_resolves_to_none(ctx):
    # A branch that did not execute -> graceful None (coalesce handles this later).
    assert evaluate_expression("$steps.crea-odonimo.outputs.progressivo_nazionale", ctx) is None


def test_loop_variable_reference():
    ctx = ExecutionContext(inputs={}, loop_vars={"accesso": {"prognazacc": "999"}})
    assert evaluate_expression("$accesso.prognazacc", ctx) == "999"


# --- conditions -------------------------------------------------------------


def test_condition_equals_number(ctx):
    assert evaluate_condition("$statusCode == 200", ctx) is True
    assert evaluate_condition("$statusCode == 500", ctx) is False


def test_condition_equals_quoted_string(ctx):
    assert evaluate_condition('$response.body.esito == "0"', ctx) is True
    assert evaluate_condition('$response.body.esito == "23"', ctx) is False


def test_condition_equals_true_literal(ctx):
    assert evaluate_condition("$response.body.flag == true", ctx) is True


def test_condition_equals_null(ctx):
    # numero_civico is None in inputs -> equals null.
    assert evaluate_condition("$inputs.numero_civico == null", ctx) is True
    assert evaluate_condition("$inputs.codcom == null", ctx) is False


def test_condition_not_equals(ctx):
    assert evaluate_condition('$response.body.esito != "0"', ctx) is False


def test_condition_greater_than(ctx):
    assert evaluate_condition("$response.body.data.length > 0", ctx) is True
    assert evaluate_condition("$response.body.data.length > 5", ctx) is False


def test_condition_ordering_operators(ctx):
    assert evaluate_condition("$response.body.data.length >= 2", ctx) is True
    assert evaluate_condition("$response.body.data.length <= 2", ctx) is True
    assert evaluate_condition("$response.body.data.length < 2", ctx) is False


def test_bare_reference_is_truthy(ctx):
    assert evaluate_condition("$response.body.flag", ctx) is True


# --- payload resolution -----------------------------------------------------


def test_resolve_value_nested_payload(ctx):
    payload = {
        "req": "esisteodonimo",  # literal, kept as-is
        "codcom": "$inputs.codcom",
        "richiesta": {
            "denom": "$inputs.denom_odonimo",
            "tipo_operazione": "I",
            "nested": {"prognaz": "$steps.cerca-odonimo.outputs.progressivo_nazionale"},
            "list": ["$inputs.codcom", "literal"],
        },
    }
    resolved = resolve_value(payload, ctx)
    assert resolved == {
        "req": "esisteodonimo",
        "codcom": "H501",
        "richiesta": {
            "denom": "ROMA",
            "tipo_operazione": "I",
            "nested": {"prognaz": "2000449"},
            "list": ["H501", "literal"],
        },
    }


def test_resolve_value_passes_through_non_expressions(ctx):
    assert resolve_value("plain", ctx) == "plain"
    assert resolve_value(42, ctx) == 42
    assert resolve_value(None, ctx) is None


def test_x_coalesce_picks_the_first_non_null(ctx):
    # numero_civico input is None -> falls back to the read step's output.
    payload = {
        "numero": {
            "x-coalesce": [
                "$inputs.numero_civico",
                "$steps.cerca-odonimo.outputs.progressivo_nazionale",
            ]
        },
        "codcom": {"x-coalesce": ["$inputs.codcom", "$inputs.denom_odonimo"]},
    }
    resolved = resolve_value(payload, ctx)
    assert resolved == {"numero": "2000449", "codcom": "H501"}


def test_x_coalesce_is_all_null_when_nothing_resolves(ctx):
    resolved = resolve_value(
        {"x": {"x-coalesce": ["$inputs.numero_civico", "$inputs.missing"]}}, ctx
    )
    assert resolved == {"x": None}


def test_x_coalesce_accepts_literal_fallbacks(ctx):
    resolved = resolve_value({"op": {"x-coalesce": ["$inputs.numero_civico", "R"]}}, ctx)
    assert resolved == {"op": "R"}
