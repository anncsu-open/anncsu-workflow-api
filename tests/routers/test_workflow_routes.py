"""Tests for the workflow execution routes: ``POST /v1/workflows/<workflowId>``.

One typed route per public Arazzo workflow (the reusable ``sopprimi-accesso``
sub-workflow stays internal). The route layer validates input with the Phase A
models, runs the workflow through the application service, and maps the run's
declared outputs onto the typed Output models — synchronous in-band outcome
([BLOCK_REST]). Failures follow ADR 0008: engine/transport exceptions become
RFC 7807 Problem Details via the app-level exception handlers.
"""

from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.application.service import WorkflowApplicationService
from app.executor.engine import StepFailedError, WorkflowError, WorkflowExecutor
from app.executor.spec import load_spec
from app.main import app
from app.ports.transport import Response, TransportError
from app.routers.workflows import get_workflow_service
from tests.executor.support import ScriptedTransport

SPECS_DIR = Path(__file__).resolve().parent.parent.parent / "specs"
ARAZZO_SPEC = SPECS_DIR / "anncsu-workflow.arazzo.yaml"


@contextmanager
def _client_with(service):
    app.dependency_overrides[get_workflow_service] = lambda: service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)


@contextmanager
def _client_scripted(responses: dict[str, Response]):
    spec = load_spec(ARAZZO_SPEC)
    executor = WorkflowExecutor(spec, ScriptedTransport(responses))
    with _client_with(WorkflowApplicationService(executor)) as client:
        yield client


class _RaisingService:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def run(self, workflow_id, inputs):
        raise self._error


def test_crea_indirizzo_route_returns_coalesced_progressivi():
    responses = {
        # odonimo and accesso do not exist -> both "crea" branches run.
        "anncsu-consultazione.esisteOdonimoPost": Response(200, {"data": False}),
        "anncsu-odonimi.gestioneAnncsuOdonimiPdnd": Response(
            200, {"esito": "0", "dati": [{"progr_nazionale": "2000449"}]}
        ),
        "anncsu-consultazione.esisteAccessoPost": Response(200, {"data": False}),
        "anncsu-accessi.gestioneAnncsuPdnd": Response(
            200, {"esito": "0", "dati": [{"progr_civico": "1370588"}]}
        ),
    }
    with _client_scripted(responses) as client:
        response = client.post(
            "/v1/workflows/verifica-e-crea-indirizzo-completo",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA",
                "dug": "VIA",
                "numero_civico": "42",
                "data_validita": "08/10/2024",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["progressivo_nazionale_odonimo"] == "2000449"
    assert body["progressivo_civico"] == "1370588"
    assert body["message"]


def test_ricerca_route_maps_search_results():
    responses = {
        "anncsu-consultazione.elencoodonimiprogPost": Response(
            200, {"data": [{"prognaz": "2000449", "dug": "VIA", "denomuff": "ROMA"}]}
        ),
        "anncsu-consultazione.elencoaccessiprogPost": Response(
            200, {"data": [{"prognazacc": "1370588", "civico": "42"}]}
        ),
    }
    with _client_scripted(responses) as client:
        response = client.post(
            "/v1/workflows/ricerca-indirizzo-completo",
            json={"codcom": "H501", "denom_odonimo": "ROMA", "numero_civico": "42"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["odonimi"][0]["prognaz"] == "2000449"
    assert body["odonimi"][0]["denomuff"] == "ROMA"
    assert body["accessi"][0]["prognazacc"] == "1370588"
    assert body["accessi"][0]["civico"] == "42"


def test_aggiorna_coordinate_route_returns_updated_coordinates():
    responses = {
        "anncsu-consultazione.elencoodonimiprogPost": Response(
            200, {"data": [{"prognaz": "2000449", "dug": "VIA", "denomuff": "ROMA"}]}
        ),
        "anncsu-consultazione.elencoaccessiprogPost": Response(
            200, {"data": [{"prognazacc": "1370588", "civico": "42"}]}
        ),
        "anncsu-coordinate.gestionecoordinate": Response(
            200,
            {
                "esito": "0",
                "dati": [{"coordinata_x": "13.1022000", "coordinata_y": "41.8847600"}],
            },
        ),
    }
    with _client_scripted(responses) as client:
        response = client.post(
            "/v1/workflows/aggiorna-coordinate-accesso",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA",
                "numero_civico": "42",
                "coordinata_x": "13.1022000",
                "coordinata_y": "41.8847600",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["coordinate"] == {"coordinata_x": "13.1022000", "coordinata_y": "41.8847600"}


def test_sopprimi_odonimo_route_reports_suppressed_accessi():
    responses = {
        "anncsu-consultazione.elencoodonimiprogPost": Response(
            200, {"data": [{"prognaz": "2000449", "denomuff": "VIA ROMA"}]}
        ),
        "anncsu-consultazione.elencoaccessiprogPost": Response(
            200, {"data": [{"prognazacc": "a1"}, {"prognazacc": "a2"}]}
        ),
        "anncsu-accessi.gestioneAnncsuPdnd": Response(200, {"esito": "0"}),
        "anncsu-odonimi.gestioneAnncsuOdonimiPdnd": Response(200, {"esito": "0"}),
    }
    with _client_scripted(responses) as client:
        response = client.post(
            "/v1/workflows/sopprimi-odonimo-completo",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA",
                "data_soppressione": "08/10/2024",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["odonimo_soppresso"] == "VIA ROMA"
    assert body["progressivo_nazionale"] == "2000449"
    assert [a["prognazacc"] for a in body["accessi_presenti"]] == ["a1", "a2"]


def test_step_failure_maps_to_a_422_problem():
    responses = {
        # The first step's successCriteria ($statusCode == 200) fails; no onFailure.
        "anncsu-consultazione.esisteOdonimoPost": Response(500, {"esito": "99"}),
    }
    with _client_scripted(responses) as client:
        response = client.post(
            "/v1/workflows/verifica-e-crea-indirizzo-completo",
            json={"codcom": "H501", "denom_odonimo": "ROMA", "dug": "VIA", "numero_civico": "42"},
        )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert problem["status"] == 422
    assert problem["title"]
    assert problem["detail"]


def test_transport_error_maps_to_a_502_problem():
    with _client_with(_RaisingService(TransportError("token endpoint unreachable"))) as client:
        response = client.post(
            "/v1/workflows/ricerca-indirizzo-completo",
            json={"codcom": "H501", "denom_odonimo": "ROMA"},
        )

    assert response.status_code == 502
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert problem["status"] == 502
    assert "token endpoint unreachable" in problem["detail"]


def test_workflow_error_maps_to_a_500_problem():
    with _client_with(_RaisingService(WorkflowError("goto loop detected"))) as client:
        response = client.post(
            "/v1/workflows/ricerca-indirizzo-completo",
            json={"codcom": "H501", "denom_odonimo": "ROMA"},
        )

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["status"] == 500


def test_step_failed_is_a_workflow_error_but_keeps_its_own_status():
    """StepFailedError subclasses WorkflowError; the more specific handler must win."""
    with _client_with(_RaisingService(StepFailedError("step failed"))) as client:
        response = client.post(
            "/v1/workflows/ricerca-indirizzo-completo",
            json={"codcom": "H501", "denom_odonimo": "ROMA"},
        )

    assert response.status_code == 422


def test_invalid_input_returns_fastapi_validation_422():
    with _client_scripted({}) as client:
        response = client.post(
            "/v1/workflows/ricerca-indirizzo-completo",
            json={"denom_odonimo": "ROMA"},  # missing required codcom
        )

    assert response.status_code == 422


def test_the_reusable_sub_workflow_is_not_exposed():
    with _client_scripted({}) as client:
        response = client.post(
            "/v1/workflows/sopprimi-accesso",
            json={"codcom": "H501"},
        )

    assert response.status_code == 404


def test_the_production_service_wiring_builds_and_is_cached():
    """The default provider wires spec + SDK transport once (no network at build)."""
    first = get_workflow_service()
    assert isinstance(first, WorkflowApplicationService)
    assert get_workflow_service() is first


def test_workflow_routes_are_published_in_the_v1_openapi():
    with _client_scripted({}) as client:
        document = client.get("/v1/openapi.json").json()

    for workflow_id in (
        "verifica-e-crea-indirizzo-completo",
        "aggiorna-coordinate-accesso",
        "sopprimi-odonimo-completo",
        "ricerca-indirizzo-completo",
    ):
        assert f"/v1/workflows/{workflow_id}" in document["paths"]
