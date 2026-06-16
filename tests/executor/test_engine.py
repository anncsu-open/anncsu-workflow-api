"""Tests for the generic Arazzo workflow engine (loader + step runner).

Covers sequential execution, ``onSuccess``/``onFailure`` + ``goto``/``end``
branching, output capture and workflow-level outputs, and graceful handling of
a failed step with and without a matching ``onFailure`` action. A final
integration test drives the real consolidated ANNCSU spec with a scripted
transport.
"""

from pathlib import Path

import pytest
from structlog.testing import capture_logs

from app.config import Settings
from app.executor.engine import StepFailedError, WorkflowExecutor
from app.executor.spec import load_spec
from app.logging import configure_logging
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


async def test_failed_step_without_handler_logs_status_and_body():
    # The upstream error body is the only clue why a step failed (e.g. a non-200
    # from ANNCSU); ADR 0014 says do not lose it. The unmatched-failure path must
    # log status + body at warning level so collaudo failures are diagnosable.
    configure_logging(Settings(log_level="INFO", log_format="json"))
    spec = load_spec(
        {
            "workflows": [
                {
                    "workflowId": "wf",
                    "steps": [
                        _step("s1", "src.op", success_criteria=["$statusCode == 200"]),
                    ],
                }
            ]
        }
    )
    transport = ScriptedTransport(
        {"src.op": Response(400, {"esito": "1", "messaggio": "civico inesistente"})}
    )

    with capture_logs() as logs:
        with pytest.raises(StepFailedError):
            await WorkflowExecutor(spec, transport).run("wf", {})

    failed = [e for e in logs if e.get("event") == "workflow.step_failed"]
    assert failed, "expected a warning event when a step fails with no handler"
    assert failed[0]["log_level"] == "warning"
    assert failed[0]["step_id"] == "s1"
    assert failed[0]["status_code"] == 400
    assert failed[0]["response_body"]["messaggio"] == "civico inesistente"


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


async def test_real_spec_search_by_progressivo_nazionale_resolves_via_prognazarea():
    # progressivo_nazionale (ADR 0021): resolve the odonimo directly via prognazarea,
    # skip the denomination search, then list its accessi by the given progressive.
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.prognazareaPost": Response(
                200, {"data": [{"prognaz": "919572", "dug": "VIA", "denomuff": "ROMA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200, {"data": [{"prognazacc": "1", "civico": "42"}]}
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "ricerca-indirizzo-completo",
        {"codcom": "H501", "progressivo_nazionale": "919572", "numero_civico": "42"},
    )

    ops = [op for op, _ in transport.calls]
    assert ops == [
        "anncsu-consultazione.prognazareaPost",
        "anncsu-consultazione.elencoaccessiprogPost",
    ]  # the denomination search is skipped
    accessi_call = next(p for op, p in transport.calls if op.endswith("elencoaccessiprogPost"))
    assert accessi_call["prognaz"] == "919572"  # uses the input progressive
    assert [o["prognaz"] for o in run.outputs["odonimi"]] == ["919572"]
    assert [a["prognazacc"] for a in run.outputs["accessi"]] == ["1"]


async def test_real_spec_search_by_progressivo_nazionale_without_civico_skips_accessi():
    # progressivo_nazionale and no numero_civico: resolve the odonimo and stop, with
    # empty accessi (no elencoaccessiprog), mirroring the denomination no-civico path.
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.prognazareaPost": Response(
                200, {"data": [{"prognaz": "919572", "denomuff": "ROMA"}]}
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "ricerca-indirizzo-completo", {"codcom": "H501", "progressivo_nazionale": "919572"}
    )

    assert run.status == "ended"
    assert [op for op, _ in transport.calls] == ["anncsu-consultazione.prognazareaPost"]
    assert [o["prognaz"] for o in run.outputs["odonimi"]] == ["919572"]
    assert not run.outputs.get("accessi")  # None/empty -> the route maps it to []


async def test_real_spec_search_by_denominazione_skips_prognazarea():
    # Regression: in denomination mode the prognazarea step is skipped (x-when false).
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "919572", "duf": "ROMA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200, {"data": [{"prognazacc": "1"}]}
            ),
        }
    )

    await WorkflowExecutor(spec, transport).run(
        "ricerca-indirizzo-completo",
        {"codcom": "H501", "denom_odonimo": "ROMA", "numero_civico": "42"},
    )

    ops = [op for op, _ in transport.calls]
    assert "anncsu-consultazione.prognazareaPost" not in ops
    assert ops[0] == "anncsu-consultazione.elencoodonimiprogPost"


async def test_real_spec_search_returns_empty_accessi_on_404():
    # ANNCSU answers 404 when an accessi search finds nothing; for a read-only
    # search that is "zero results", not a failure -> the workflow must complete
    # with the odonimi found and no accessi (collaudo returns this problem+json).
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "919572", "duf": "ROMA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                404,
                {
                    "title": "non trovati accessi per valori forniti alla funzione elencoaccessiprog",
                    "detail": "non trovati accessi per progressivo nazionale odonimo '919572'",
                },
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "ricerca-indirizzo-completo",
        {"codcom": "H501", "denom_odonimo": "ROMA", "numero_civico": "1"},
    )

    assert run.status in ("completed", "ended")
    assert run.outputs["odonimi"][0]["prognaz"] == "919572"
    assert not run.outputs.get("accessi")  # None/empty -> the route maps it to []


async def test_real_spec_search_returns_empty_on_odonimi_404():
    # The same "zero results = 404" convention applies to the odonimi search: a
    # query that matches nothing must return empty lists, not a 422.
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                404, {"title": "non trovati odonimi per valori forniti"}
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "ricerca-indirizzo-completo",
        {"codcom": "H501", "denom_odonimo": "ZZZNONESISTE", "numero_civico": "1"},
    )

    assert run.status in ("completed", "ended")
    assert not run.outputs.get("odonimi")
    assert not run.outputs.get("accessi")
    # The accessi search is never attempted once odonimi are absent.
    assert [op for op, _ in transport.calls] == ["anncsu-consultazione.elencoodonimiprogPost"]


async def test_real_spec_search_combines_civico_and_esponente_in_accparz():
    # accparz carries civic + optional esponente as one partial filter value
    # (anncsu-sdk), separated by "/" (validated on collaudo: "15/C" matches, "15C"
    # does not); build it via x-join so civic "42" + esponente "A" -> accparz "42/A".
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "2000449", "duf": "ROMA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200, {"data": [{"prognazacc": "1"}]}
            ),
        }
    )

    await WorkflowExecutor(spec, transport).run(
        "ricerca-indirizzo-completo",
        {"codcom": "H501", "denom_odonimo": "ROMA", "numero_civico": "42", "esponente": "A"},
    )

    accparz = next(p for op, p in transport.calls if op.endswith("elencoaccessiprogPost"))[
        "accparz"
    ]
    assert accparz == "42/A"


async def test_real_spec_search_accparz_is_civico_only_without_esponente():
    # No esponente -> accparz is just the civic (x-join drops the null and its "/").
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "2000449", "duf": "ROMA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200, {"data": [{"prognazacc": "1"}]}
            ),
        }
    )

    await WorkflowExecutor(spec, transport).run(
        "ricerca-indirizzo-completo",
        {"codcom": "H501", "denom_odonimo": "ROMA", "numero_civico": "42"},
    )

    accparz = next(p for op, p in transport.calls if op.endswith("elencoaccessiprogPost"))[
        "accparz"
    ]
    assert accparz == "42"


async def test_real_spec_search_appends_specificita_with_hyphen():
    # Full AdE accparz format: civico/esponente-specificità (ADR 0020).
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "2000449", "duf": "ROMA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200, {"data": [{"prognazacc": "1"}]}
            ),
        }
    )

    await WorkflowExecutor(spec, transport).run(
        "ricerca-indirizzo-completo",
        {
            "codcom": "H501",
            "denom_odonimo": "ROMA",
            "numero_civico": "42",
            "esponente": "A",
            "specificita": "ROSSO",
        },
    )

    accparz = next(p for op, p in transport.calls if op.endswith("elencoaccessiprogPost"))[
        "accparz"
    ]
    assert accparz == "42/A-ROSSO"


async def test_real_spec_ricerca_accessi_per_odonimo_combines_civico_and_esponente():
    # The by-prognaz search also folds the optional esponente into accparz.
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.prognazareaPost": Response(
                200, {"data": [{"prognaz": "907720", "duf": "AURELIA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200, {"data": [{"prognazacc": "1"}]}
            ),
        }
    )

    await WorkflowExecutor(spec, transport).run(
        "ricerca-accessi-per-odonimo",
        {"codcom": "H501", "prognaz": "907720", "numero_civico": "42", "esponente": "A"},
    )

    accparz = next(p for op, p in transport.calls if op.endswith("elencoaccessiprogPost"))[
        "accparz"
    ]
    assert accparz == "42/A"


# --- crea-accesso-per-odonimo (ADR 0020) -----------------------------------


async def test_real_spec_crea_accesso_per_odonimo_creates_when_absent():
    # Existence is checked from the odonimo's prognaz (elencoaccessiprog) with the
    # AdE accparz; a 404 means the accesso is absent -> create it (ADR 0020).
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.prognazareaPost": Response(
                200, {"data": [{"prognaz": "907720", "duf": "AURELIA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                404, {"title": "non trovati accessi"}
            ),
            "anncsu-accessi.gestioneAnncsuPdnd": Response(
                200, {"esito": "0", "dati": [{"progr_civico": "1370588"}]}
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "crea-accesso-per-odonimo",
        {
            "codcom": "H501",
            "prognaz": "907720",
            "numero_civico": "42",
            "esponente": "A",
            "sezione_censimento": "580911010001",
        },
    )

    assert run.outputs["progressivo_nazionale_odonimo"] == "907720"
    assert run.outputs["progressivo_civico"] == "1370588"
    accparz = next(p for op, p in transport.calls if op.endswith("elencoaccessiprogPost"))[
        "accparz"
    ]
    assert accparz == "42/A"


async def test_real_spec_crea_accesso_per_odonimo_returns_existing_without_creating():
    # Exactly one match -> the accesso already exists -> return its prognazacc, no write.
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.prognazareaPost": Response(
                200, {"data": [{"prognaz": "907720"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200, {"data": [{"prognazacc": "5400478", "civico": "42", "esp": "A"}]}
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "crea-accesso-per-odonimo",
        {
            "codcom": "H501",
            "prognaz": "907720",
            "numero_civico": "42",
            "esponente": "A",
            "sezione_censimento": "580911010001",
        },
    )

    assert run.outputs["progressivo_civico"] == "5400478"
    assert "anncsu-accessi.gestioneAnncsuPdnd" not in [op for op, _ in transport.calls]


async def test_real_spec_crea_accesso_per_odonimo_refuses_ambiguous():
    # More than one accparz match -> ambiguous -> fail, never create (ADR 0020).
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.prognazareaPost": Response(
                200, {"data": [{"prognaz": "907720"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200, {"data": [{"prognazacc": "1"}, {"prognazacc": "2"}]}
            ),
            "anncsu-accessi.gestioneAnncsuPdnd": Response(
                200, {"esito": "0", "dati": [{"progr_civico": "X"}]}
            ),
        }
    )

    with pytest.raises(StepFailedError, match="verifica-accesso"):
        await WorkflowExecutor(spec, transport).run(
            "crea-accesso-per-odonimo",
            {
                "codcom": "H501",
                "prognaz": "907720",
                "numero_civico": "42",
                "sezione_censimento": "580911010001",
            },
        )
    assert "anncsu-accessi.gestioneAnncsuPdnd" not in [op for op, _ in transport.calls]


# --- verifica-e-crea-odonimo-completo (odonimo-only create) ----------------


async def test_real_spec_verifica_e_crea_odonimo_creates_when_absent():
    # Verify-then-create the odonimo alone: esisteOdonimo (full name) says no -> create.
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.esisteOdonimoPost": Response(200, {"data": False}),
            "anncsu-odonimi.gestioneAnncsuOdonimiPdnd": Response(
                200, {"esito": "0", "dati": [{"progr_nazionale": "2000449"}]}
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "verifica-e-crea-odonimo-completo",
        {"codcom": "H501", "denom_odonimo": "ROMA NUOVA", "dug": "VIA"},
    )

    assert run.outputs["progressivo_nazionale_odonimo"] == "2000449"
    esiste = next(p for op, p in transport.calls if op.endswith("esisteOdonimoPost"))
    assert esiste["denom"] == "VIA ROMA NUOVA"  # full name (ADR 0019)
    assert "anncsu-consultazione.elencoodonimiprogPost" not in [op for op, _ in transport.calls]


async def test_real_spec_verifica_e_crea_odonimo_returns_existing_without_creating():
    # esisteOdonimo says yes -> resolve the existing prognaz, do not create.
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.esisteOdonimoPost": Response(200, {"data": True}),
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "907720"}]}
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "verifica-e-crea-odonimo-completo",
        {"codcom": "H501", "denom_odonimo": "AURELIA", "dug": "VIA"},
    )

    assert run.outputs["progressivo_nazionale_odonimo"] == "907720"
    assert "anncsu-odonimi.gestioneAnncsuOdonimiPdnd" not in [op for op, _ in transport.calls]


async def test_real_spec_verifica_e_crea_odonimo_refuses_ambiguous():
    # The existing odonimo resolves ambiguously (>1 match) -> fail, never create.
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.esisteOdonimoPost": Response(200, {"data": True}),
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "1"}, {"prognaz": "2"}]}
            ),
            "anncsu-odonimi.gestioneAnncsuOdonimiPdnd": Response(
                200, {"esito": "0", "dati": [{"progr_nazionale": "X"}]}
            ),
        }
    )

    with pytest.raises(StepFailedError, match="cerca-odonimo"):
        await WorkflowExecutor(spec, transport).run(
            "verifica-e-crea-odonimo-completo",
            {"codcom": "H501", "denom_odonimo": "AURELIA", "dug": "VIA"},
        )
    assert "anncsu-odonimi.gestioneAnncsuOdonimiPdnd" not in [op for op, _ in transport.calls]


async def test_real_spec_search_disambiguates_multiple_odonimi():
    # The SDK never silently picks the first match; when the denomination matches
    # more than one odonimo, return all candidates with empty accessi so the caller
    # can re-query a specific prognaz (ADR 0018) instead of querying data[0].
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200,
                {
                    "data": [
                        {"prognaz": "907719", "dug": "CIRCONVALLAZIONE", "duf": "AURELIA"},
                        {"prognaz": "907720", "dug": "VIA", "duf": "AURELIA"},
                    ]
                },
            ),
            # Scripted but must never be reached on an ambiguous match.
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200, {"data": [{"prognazacc": "1"}]}
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "ricerca-indirizzo-completo",
        {"codcom": "H501", "denom_odonimo": "AURELIA", "numero_civico": "1"},
    )

    assert run.status in ("completed", "ended")
    assert len(run.outputs["odonimi"]) == 2
    assert not run.outputs.get("accessi")
    assert [op for op, _ in transport.calls] == ["anncsu-consultazione.elencoodonimiprogPost"]


async def test_real_spec_ricerca_accessi_per_odonimo_resolves_odonimo_and_accessi():
    # The by-prognaz search (ADR 0018): resolve the odonimo via prognazarea, then
    # list its accessi. accparz carries the optional numero_civico (civic or metric).
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.prognazareaPost": Response(
                200, {"data": [{"prognaz": "907720", "dug": "VIA", "duf": "AURELIA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200, {"data": [{"prognazacc": "5400478", "civico": "1", "coordX": "12.4"}]}
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "ricerca-accessi-per-odonimo",
        {"codcom": "H501", "prognaz": "907720", "numero_civico": "1"},
    )

    assert run.status in ("completed", "ended")
    assert run.outputs["odonimi"][0]["prognaz"] == "907720"
    assert run.outputs["odonimi"][0]["duf"] == "AURELIA"
    assert run.outputs["accessi"][0]["prognazacc"] == "5400478"
    # accparz must carry the supplied civic/metric value.
    accessi_call = next(p for op, p in transport.calls if op.endswith("elencoaccessiprogPost"))
    assert accessi_call["accparz"] == "1"
    assert accessi_call["prognaz"] == "907720"


async def test_real_spec_ricerca_accessi_per_odonimo_empty_accessi_on_404():
    # A by-prognaz search that finds no accessi (404) returns the resolved odonimo
    # with an empty accessi list, not a 422.
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.prognazareaPost": Response(
                200, {"data": [{"prognaz": "907720", "dug": "VIA", "duf": "AURELIA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                404, {"title": "non trovati accessi per valori forniti"}
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "ricerca-accessi-per-odonimo",
        {"codcom": "H501", "prognaz": "907720", "numero_civico": "999"},
    )

    assert run.status in ("completed", "ended")
    assert run.outputs["odonimi"][0]["prognaz"] == "907720"
    assert not run.outputs.get("accessi")


async def test_real_spec_ricerca_accessi_per_odonimo_unknown_prognaz_is_empty():
    # An unknown prognaz (prognazarea 404) returns empty lists, not a 422.
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.prognazareaPost": Response(
                404, {"title": "non trovata area per progressivo nazionale"}
            ),
        }
    )

    run = await WorkflowExecutor(spec, transport).run(
        "ricerca-accessi-per-odonimo",
        {"codcom": "H501", "prognaz": "999999999", "numero_civico": "1"},
    )

    assert run.status in ("completed", "ended")
    assert not run.outputs.get("odonimi")
    assert not run.outputs.get("accessi")
    # The accessi search is never attempted when the odonimo does not resolve.
    assert [op for op, _ in transport.calls] == ["anncsu-consultazione.prognazareaPost"]


async def test_real_spec_create_sends_full_name_to_esiste_odonimo():
    # esisteOdonimo needs DUG + " " + DENOMUFF, not the bare denomination (ADR 0019).
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.esisteOdonimoPost": Response(200, {"data": True}),
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "2000449"}]}
            ),
            "anncsu-consultazione.esisteAccessoPost": Response(200, {"data": False}),
            "anncsu-accessi.gestioneAnncsuPdnd": Response(
                200, {"esito": "0", "dati": [{"progr_civico": "1370588"}]}
            ),
        }
    )

    await WorkflowExecutor(spec, transport).run(
        "verifica-e-crea-indirizzo-completo",
        {"codcom": "H501", "denom_odonimo": "AURELIA", "dug": "VIA", "numero_civico": "42"},
    )

    esiste_payload = next(p for op, p in transport.calls if op.endswith("esisteOdonimoPost"))
    assert esiste_payload["denom"] == "VIA AURELIA"


async def test_real_spec_create_refuses_ambiguous_odonimo():
    # A denomination shared across several DUG matches many odonimi; the create must
    # NOT silently use data[0] -> it fails instead of writing to the wrong odonimo.
    spec = load_spec(ARAZZO_SPEC)
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.esisteOdonimoPost": Response(200, {"data": True}),
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200,
                {
                    "data": [
                        {"prognaz": "907719", "dug": "CIRCONVALLAZIONE", "duf": "AURELIA"},
                        {"prognaz": "907720", "dug": "VIA", "duf": "AURELIA"},
                    ]
                },
            ),
            "anncsu-consultazione.esisteAccessoPost": Response(200, {"data": False}),
            "anncsu-accessi.gestioneAnncsuPdnd": Response(
                200, {"esito": "0", "dati": [{"progr_civico": "1370588"}]}
            ),
        }
    )

    with pytest.raises(StepFailedError, match="cerca-odonimo"):
        await WorkflowExecutor(spec, transport).run(
            "verifica-e-crea-indirizzo-completo",
            {"codcom": "H501", "denom_odonimo": "AURELIA", "dug": "VIA", "numero_civico": "42"},
        )
    # The accesso write must never be attempted on an ambiguous match.
    assert "anncsu-accessi.gestioneAnncsuPdnd" not in [op for op, _ in transport.calls]


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


async def test_payload_entries_resolving_to_null_are_omitted():
    """An unset workflow input must disappear from the request payload: an
    explicit null and an absent field can mean different things upstream."""
    spec = load_spec(
        {
            "workflows": [
                {
                    "workflowId": "wf",
                    "steps": [
                        {
                            "stepId": "step",
                            "operationId": "src.op",
                            "requestBody": {
                                "contentType": "application/json",
                                "payload": {
                                    "kept": "$inputs.present",
                                    "dropped": "$inputs.missing",
                                    "nested": {
                                        "kept": "fixed",
                                        "dropped": "$inputs.missing",
                                    },
                                },
                            },
                            "successCriteria": [{"condition": "$statusCode == 200"}],
                        }
                    ],
                }
            ]
        }
    )
    transport = ScriptedTransport({"src.op": Response(200, {})})

    await WorkflowExecutor(spec, transport).run("wf", {"present": "x", "missing": None})

    assert transport.calls == [("src.op", {"kept": "x", "nested": {"kept": "fixed"}})]


async def test_run_logs_a_structured_event_per_step():
    # Per-step events are DEBUG; raise the threshold so capture_logs sees them
    # even when an earlier test configured logging at INFO.
    configure_logging(Settings(log_level="DEBUG", log_format="json"))
    spec = load_spec(
        {
            "workflows": [
                {
                    "workflowId": "wf",
                    "steps": [
                        {
                            "stepId": "only",
                            "operationId": "src.op",
                            "requestBody": {"contentType": "application/json", "payload": {}},
                            "successCriteria": [{"condition": "$statusCode == 200"}],
                        }
                    ],
                }
            ]
        }
    )
    transport = ScriptedTransport({"src.op": Response(200, {})})

    with capture_logs() as logs:
        await WorkflowExecutor(spec, transport).run("wf", {})

    steps = [e for e in logs if e.get("event") == "workflow.step"]
    assert steps, "expected a per-step log event"
    assert steps[0]["operation_id"] == "src.op"
    assert steps[0]["succeeded"] is True
