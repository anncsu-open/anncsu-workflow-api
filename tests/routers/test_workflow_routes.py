"""Tests for the workflow execution routes: ``POST /anncsu/v1/workflows/<workflowId>``.

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
    transport = ScriptedTransport(
        {
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
    )
    executor = WorkflowExecutor(load_spec(ARAZZO_SPEC), transport)
    with _client_with(WorkflowApplicationService(executor)) as client:
        response = client.post(
            "/anncsu/v1/workflows/verifica-e-crea-indirizzo-completo",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA",
                "dug": "VIA",
                "numero_civico": "42",
                "data_validita": "08/10/2024",
                "sezione_censimento": "580911010001",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["progressivo_nazionale_odonimo"] == "2000449"
    assert body["progressivo_civico"] == "1370588"
    assert body["message"]
    # The accesso insert must carry sezione_censimento: the OAS requires it
    # for operazione_civico I/R and the server rejects the insert without it.
    crea_accesso = next(p for op, p in transport.calls if op == "anncsu-accessi.gestioneAnncsuPdnd")
    assert crea_accesso["richiesta"]["accesso"]["sezione_censimento"] == "580911010001"


def test_crea_indirizzo_requires_the_sezione_censimento():
    """Without the sezione the accesso insert fails opaquely server-side (error 100):
    the contract requires it up front instead."""
    with _client_scripted({}) as client:
        response = client.post(
            "/anncsu/v1/workflows/verifica-e-crea-indirizzo-completo",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA",
                "dug": "VIA",
                "numero_civico": "42",
            },
        )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert any(
        "sezione_censimento" in str(error.get("loc", ())) for error in response.json()["errors"]
    )


def _crea_transport() -> ScriptedTransport:
    """Both create branches run: neither the odonimo nor the accesso exists yet."""
    return ScriptedTransport(
        {
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


def test_crea_indirizzo_civic_sends_full_accesso_and_odonimo_fields():
    transport = _crea_transport()
    executor = WorkflowExecutor(load_spec(ARAZZO_SPEC), transport)
    with _client_with(WorkflowApplicationService(executor)) as client:
        response = client.post(
            "/anncsu/v1/workflows/verifica-e-crea-indirizzo-completo",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA",
                "dug": "VIA",
                "numero_civico": "42",
                "sezione_censimento": "580911010001",
                "esponente": "A",
                "specificita": "ROSSO",
                "isolato": "12",
                "codice_civico_comunale": "7569A",
                "coordinata_x": "13.1022000",
                "coordinata_y": "41.8847600",
                "coordinata_z": "150",
                "metodo": "3",
                "denom_localita": "CENTRO",
                "codice_comunale": "C1",
            },
        )

    assert response.status_code == 200
    accesso = next(p for op, p in transport.calls if op == "anncsu-accessi.gestioneAnncsuPdnd")[
        "richiesta"
    ]["accesso"]
    assert accesso["esponente"] == "A"
    assert accesso["specificita"] == "ROSSO"
    assert accesso["isolato"] == "12"
    assert accesso["codice_civico_comunale"] == "7569A"
    assert accesso["coordinate"]["x"] == "13.1022000"
    assert accesso["coordinate"]["metodo"] == "3"
    odonimo = next(
        p for op, p in transport.calls if op == "anncsu-odonimi.gestioneAnncsuOdonimiPdnd"
    )["richiesta"]
    assert odonimo["denom_localita"] == "CENTRO"
    assert odonimo["codice_comunale"] == "C1"


def test_crea_indirizzo_metric_skips_the_civic_existence_check():
    transport = _crea_transport()
    executor = WorkflowExecutor(load_spec(ARAZZO_SPEC), transport)
    with _client_with(WorkflowApplicationService(executor)) as client:
        response = client.post(
            "/anncsu/v1/workflows/verifica-e-crea-indirizzo-completo",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA",
                "dug": "VIA",
                "metrico": "300",
                "sezione_censimento": "580911010001",
            },
        )

    assert response.status_code == 200
    ops = [op for op, _ in transport.calls]
    # esisteAccessoPost is civic-only, so the metric branch must skip it (ADR 0016).
    assert "anncsu-consultazione.esisteAccessoPost" not in ops
    accesso = next(p for op, p in transport.calls if op == "anncsu-accessi.gestioneAnncsuPdnd")[
        "richiesta"
    ]["accesso"]
    assert accesso["metrico"] == "300"
    assert "numero" not in accesso  # the unset civic number is pruned


def test_crea_indirizzo_metric_with_existing_odonimo_forks_from_cerca():
    # Odonimo already exists -> cerca-odonimo runs; the metric fork must skip the
    # civic check from that branch too, and progr_nazionale comes from the read.
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.esisteOdonimoPost": Response(200, {"data": True}),
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "2000449"}]}
            ),
            "anncsu-accessi.gestioneAnncsuPdnd": Response(
                200, {"esito": "0", "dati": [{"progr_civico": "1370588"}]}
            ),
        }
    )
    executor = WorkflowExecutor(load_spec(ARAZZO_SPEC), transport)
    with _client_with(WorkflowApplicationService(executor)) as client:
        response = client.post(
            "/anncsu/v1/workflows/verifica-e-crea-indirizzo-completo",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA",
                "dug": "VIA",
                "metrico": "300",
                "sezione_censimento": "580911010001",
            },
        )

    assert response.status_code == 200
    ops = [op for op, _ in transport.calls]
    assert "anncsu-consultazione.esisteAccessoPost" not in ops
    richiesta = next(p for op, p in transport.calls if op == "anncsu-accessi.gestioneAnncsuPdnd")[
        "richiesta"
    ]
    assert richiesta["accesso"]["metrico"] == "300"
    assert richiesta["progr_nazionale"] == "2000449"  # coalesced from cerca-odonimo


def test_ricerca_route_maps_search_results():
    responses = {
        "anncsu-consultazione.elencoodonimiprogPost": Response(
            200, {"data": [{"prognaz": "2000449", "dug": "VIA", "duf": "ROMA"}]}
        ),
        "anncsu-consultazione.elencoaccessiprogPost": Response(
            200, {"data": [{"prognazacc": "1370588", "civico": "42"}]}
        ),
    }
    with _client_scripted(responses) as client:
        response = client.post(
            "/anncsu/v1/workflows/ricerca-indirizzo-completo",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA",
                "numero_civico": "42",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["odonimi"][0]["prognaz"] == "2000449"
    assert body["odonimi"][0]["duf"] == "ROMA"
    assert body["accessi"][0]["prognazacc"] == "1370588"
    assert body["accessi"][0]["civico"] == "42"


def test_ricerca_route_folds_esponente_into_accparz():
    # The route accepts an optional esponente; it reaches the wire combined with the
    # civic in a single accparz value with the AdE separators (civic 42 + esponente
    # A -> "42/A"; specificità would append "-…").
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.elencoodonimiprogPost": Response(
                200, {"data": [{"prognaz": "2000449", "duf": "ROMA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200,
                {"data": [{"prognazacc": "1370588", "civico": "42", "esp": "A"}]},
            ),
        }
    )
    executor = WorkflowExecutor(load_spec(ARAZZO_SPEC), transport)
    with _client_with(WorkflowApplicationService(executor)) as client:
        response = client.post(
            "/anncsu/v1/workflows/ricerca-indirizzo-completo",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA",
                "numero_civico": "42",
                "esponente": "A",
            },
        )

    assert response.status_code == 200
    accparz = next(p for op, p in transport.calls if op.endswith("elencoaccessiprogPost"))[
        "accparz"
    ]
    assert accparz == "42/A"


def test_verifica_e_crea_odonimo_route_creates_when_absent():
    # Odonimo-only create (ADR 0019/0020): esisteOdonimo (full name) says no -> create.
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.esisteOdonimoPost": Response(200, {"data": False}),
            "anncsu-odonimi.gestioneAnncsuOdonimiPdnd": Response(
                200, {"esito": "0", "dati": [{"progr_nazionale": "2000449"}]}
            ),
        }
    )
    executor = WorkflowExecutor(load_spec(ARAZZO_SPEC), transport)
    with _client_with(WorkflowApplicationService(executor)) as client:
        response = client.post(
            "/anncsu/v1/workflows/verifica-e-crea-odonimo-completo",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA NUOVA",
                "dug": "VIA",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["progressivo_nazionale_odonimo"] == "2000449"
    assert body["progressivo_civico"] is None  # odonimo-only: no accesso
    esiste = next(p for op, p in transport.calls if op.endswith("esisteOdonimoPost"))
    assert esiste["denom"] == "VIA ROMA NUOVA"


def test_crea_accesso_per_odonimo_route_creates_when_absent():
    # Add a civic accesso to an existing odonimo (ADR 0020): prognaz validated,
    # accesso absent (404) -> created; accparz built with the AdE "/" separator.
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
    executor = WorkflowExecutor(load_spec(ARAZZO_SPEC), transport)
    with _client_with(WorkflowApplicationService(executor)) as client:
        response = client.post(
            "/anncsu/v1/workflows/crea-accesso-per-odonimo",
            json={
                "codcom": "H501",
                "prognaz": "907720",
                "numero_civico": "42",
                "esponente": "A",
                "sezione_censimento": "580911010001",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["progressivo_nazionale_odonimo"] == "907720"
    assert body["progressivo_civico"] == "1370588"
    accparz = next(p for op, p in transport.calls if op.endswith("elencoaccessiprogPost"))[
        "accparz"
    ]
    assert accparz == "42/A"


def test_crea_accesso_per_odonimo_route_requires_civico_xor_metrico():
    # Exactly one of numero_civico / metrico (ADR 0016/0020): neither -> 422.
    with _client_scripted({}) as client:
        response = client.post(
            "/anncsu/v1/workflows/crea-accesso-per-odonimo",
            json={
                "codcom": "H501",
                "prognaz": "907720",
                "sezione_censimento": "580911010001",
            },
        )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"


def test_ricerca_accessi_per_odonimo_route_maps_results():
    # By-prognaz search (ADR 0018): resolve the odonimo, then list its accessi.
    responses = {
        "anncsu-consultazione.prognazareaPost": Response(
            200,
            {"data": [{"prognaz": "907720", "dug": "VIA", "duf": "AURELIA"}]},
        ),
        "anncsu-consultazione.elencoaccessiprogPost": Response(
            200,
            {"data": [{"prognazacc": "5400478", "civico": "1", "coordX": "12.4"}]},
        ),
    }
    with _client_scripted(responses) as client:
        response = client.post(
            "/anncsu/v1/workflows/ricerca-accessi-per-odonimo",
            json={"codcom": "H501", "prognaz": "907720", "numero_civico": "1"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["odonimi"][0]["prognaz"] == "907720"
    assert body["odonimi"][0]["duf"] == "AURELIA"
    assert body["accessi"][0]["prognazacc"] == "5400478"


def test_ricerca_accessi_per_odonimo_requires_numero_civico():
    # ANNCSU's elencoaccessiprog requires accparz, so the by-prognaz search makes
    # numero_civico (the civic/metric filter) mandatory rather than defaulting it
    # to a magic value (ADR 0018, option B): no civic/metric -> 422 at validation.
    with _client_scripted({}) as client:
        response = client.post(
            "/anncsu/v1/workflows/ricerca-accessi-per-odonimo",
            json={"codcom": "H501", "prognaz": "907720"},
        )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert any("numero_civico" in str(e.get("loc", ())) for e in response.json()["errors"])


def test_denomination_based_coordinate_workflow_is_removed():
    """ADR 0011: the non-deterministic by-denomination coordinate write is gone."""
    with _client_scripted({}) as client:
        response = client.post(
            "/anncsu/v1/workflows/aggiorna-coordinate-accesso",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA",
                "numero_civico": "42",
                "coordinata_x": "13.1022000",
                "coordinata_y": "41.8847600",
            },
        )

    assert response.status_code == 404


# The accesso as the consultation (prognazaccPost) currently returns it: a single
# hit, attributes + coordinates, but no sezione_censimento (not exposed).
def _read_response(**overrides):
    data = {
        "civico": "42",
        "esp": "A",
        "specif": "ROSSO",
        "metrico": None,
        "codacccomunale": "7569A",
        "coordX": "13.1000000",
        "coordY": "41.8000000",
        "quota": "100",
        "metodo": "1",
    }
    data.update(overrides)
    return Response(200, {"res": "OK", "data": [data]})


def _accesso_update_transport(read=None) -> ScriptedTransport:
    return ScriptedTransport(
        {
            "anncsu-consultazione.prognazaccPost": read or _read_response(),
            "anncsu-accessi.gestioneAnncsuPdnd": Response(
                200, {"esito": "0", "dati": [{"progr_civico": "1370588"}]}
            ),
        }
    )


def _run_accesso_update(transport, payload):
    executor = WorkflowExecutor(load_spec(ARAZZO_SPEC), transport)
    with _client_with(WorkflowApplicationService(executor)) as client:
        return client.post("/anncsu/v1/workflows/aggiorna-accesso-da-progressivo", json=payload)


def test_coordinate_only_by_progressive_workflow_is_removed():
    """ADR 0012: coordinate updates are unified into aggiorna-accesso-da-progressivo."""
    with _client_scripted({}) as client:
        response = client.post(
            "/anncsu/v1/workflows/aggiorna-coordinate-da-progressivo-accesso",
            json={"codcom": "H501", "prognazacc": "1370588"},
        )
    assert response.status_code == 404


def test_aggiorna_accesso_reads_then_writes():
    """Read-modify-write (ADR 0012): consultation lookup precedes the R write."""
    transport = _accesso_update_transport()
    response = _run_accesso_update(
        transport,
        {
            "codcom": "H501",
            "prognaz": "2000449",
            "prognazacc": "1370588",
            "sezione_censimento": "580911010001",
            "esponente": "B",
        },
    )

    assert response.status_code == 200
    assert [op for op, _ in transport.calls] == [
        "anncsu-consultazione.prognazaccPost",
        "anncsu-accessi.gestioneAnncsuPdnd",
    ]
    assert transport.calls[0][1] == {
        "req": "prognazacc",
        "prognazacc": "1370588",
    }


def test_coordinate_only_update_preserves_attributes_from_the_read():
    """Caller sends only coordinates: the read preserves civico/esponente/etc."""
    transport = _accesso_update_transport()
    response = _run_accesso_update(
        transport,
        {
            "codcom": "H501",
            "prognaz": "2000449",
            "prognazacc": "1370588",
            "sezione_censimento": "580911010001",
            "coordinata_x": "13.5",
            "coordinata_y": "42.0",
        },
    )

    assert response.status_code == 200
    accesso = transport.calls[1][1]["richiesta"]["accesso"]
    assert accesso["numero"] == "42"  # preserved from read
    assert accesso["esponente"] == "A"  # preserved
    assert accesso["specificita"] == "ROSSO"  # preserved
    assert accesso["codice_civico_comunale"] == "7569A"  # preserved
    assert accesso["sezione_censimento"] == "580911010001"  # input only
    assert accesso["coordinate"]["x"] == "13.5"  # input overrides read
    assert accesso["coordinate"]["y"] == "42.0"


def test_attribute_only_update_preserves_coordinates_from_the_read():
    """Caller changes one attribute: the read preserves the coordinates."""
    transport = _accesso_update_transport()
    response = _run_accesso_update(
        transport,
        {
            "codcom": "H501",
            "prognaz": "2000449",
            "prognazacc": "1370588",
            "sezione_censimento": "580911010001",
            "esponente": "Z",
        },
    )

    assert response.status_code == 200
    accesso = transport.calls[1][1]["richiesta"]["accesso"]
    assert accesso["esponente"] == "Z"  # input overrides read
    assert accesso["numero"] == "42"  # preserved
    assert accesso["coordinate"] == {  # preserved from read
        "x": "13.1000000",
        "y": "41.8000000",
        "z": "100",
        "metodo": "1",
    }


def test_mixed_update_merges_input_over_read():
    transport = _accesso_update_transport()
    response = _run_accesso_update(
        transport,
        {
            "codcom": "H501",
            "prognaz": "2000449",
            "prognazacc": "1370588",
            "sezione_censimento": "580911010001",
            "esponente": "Z",
            "coordinata_x": "13.9",
            "coordinata_y": "42.5",
        },
    )

    assert response.status_code == 200
    accesso = transport.calls[1][1]["richiesta"]["accesso"]
    assert accesso["esponente"] == "Z"
    assert accesso["specificita"] == "ROSSO"  # untouched -> from read
    assert accesso["coordinate"]["x"] == "13.9"


def test_accesso_with_no_coordinates_sends_no_coordinate_block():
    transport = _accesso_update_transport(
        read=_read_response(coordX=None, coordY=None, quota=None, metodo=None)
    )
    response = _run_accesso_update(
        transport,
        {
            "codcom": "H501",
            "prognaz": "2000449",
            "prognazacc": "1370588",
            "sezione_censimento": "580911010001",
            "esponente": "B",
        },
    )

    assert response.status_code == 200
    assert "coordinate" not in transport.calls[1][1]["richiesta"]["accesso"]


def test_update_of_a_missing_accesso_maps_to_422():
    """The read finds no accesso (empty data) -> step fails -> Problem 422."""
    transport = _accesso_update_transport(read=Response(200, {"res": "KO", "data": []}))
    response = _run_accesso_update(
        transport,
        {
            "codcom": "H501",
            "prognaz": "2000449",
            "prognazacc": "9999999",
            "sezione_censimento": "580911010001",
            "esponente": "B",
        },
    )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    # The write must not run when the accesso does not exist.
    assert "anncsu-accessi.gestioneAnncsuPdnd" not in [op for op, _ in transport.calls]


def test_aggiorna_accesso_requires_the_sezione_censimento():
    """sezione_censimento is required for R exactly as for I (opaque error 100
    server-side otherwise): the contract rejects its absence up front."""
    with _client_scripted({}) as client:
        response = client.post(
            "/anncsu/v1/workflows/aggiorna-accesso-da-progressivo",
            json={
                "codcom": "H501",
                "prognaz": "2000449",
                "prognazacc": "1370588",
                "numero": "42",
            },
        )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert any(
        "sezione_censimento" in str(error.get("loc", ())) for error in response.json()["errors"]
    )


def test_aggiorna_accesso_route_rejects_the_numero_metrico_mutex():
    with _client_scripted({}) as client:
        response = client.post(
            "/anncsu/v1/workflows/aggiorna-accesso-da-progressivo",
            json={
                "codcom": "H501",
                "prognaz": "2000449",
                "prognazacc": "1370588",
                "numero": "42",
                "metrico": "300",
                "sezione_censimento": "580911010001",
            },
        )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"


def test_sopprimi_odonimo_route_reports_suppressed_accessi():
    responses = {
        "anncsu-consultazione.elencoodonimiprogPost": Response(
            200, {"data": [{"prognaz": "2000449", "duf": "VIA ROMA"}]}
        ),
        "anncsu-consultazione.elencoaccessiprogPost": Response(
            200, {"data": [{"prognazacc": "a1"}, {"prognazacc": "a2"}]}
        ),
        "anncsu-accessi.gestioneAnncsuPdnd": Response(200, {"esito": "0"}),
        # Real odonimo S response: 200 with idRichiesta + dati, no `esito` (contract).
        "anncsu-odonimi.gestioneAnncsuOdonimiPdnd": Response(
            200,
            {"idRichiesta": "317922", "dati": [{"progr_nazionale": "2000449"}]},
        ),
    }
    with _client_scripted(responses) as client:
        response = client.post(
            "/anncsu/v1/workflows/sopprimi-odonimo-completo",
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
            "/anncsu/v1/workflows/verifica-e-crea-indirizzo-completo",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA",
                "dug": "VIA",
                "numero_civico": "42",
            },
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
            "/anncsu/v1/workflows/ricerca-indirizzo-completo",
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
            "/anncsu/v1/workflows/ricerca-indirizzo-completo",
            json={"codcom": "H501", "denom_odonimo": "ROMA"},
        )

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["status"] == 500


def test_step_failed_is_a_workflow_error_but_keeps_its_own_status():
    """StepFailedError subclasses WorkflowError; the more specific handler must win."""
    with _client_with(_RaisingService(StepFailedError("step failed"))) as client:
        response = client.post(
            "/anncsu/v1/workflows/ricerca-indirizzo-completo",
            json={"codcom": "H501", "denom_odonimo": "ROMA"},
        )

    assert response.status_code == 422


def test_invalid_input_returns_a_422_problem():
    with _client_scripted({}) as client:
        response = client.post(
            "/anncsu/v1/workflows/ricerca-indirizzo-completo",
            json={"denom_odonimo": "ROMA"},  # missing required codcom
        )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert problem["status"] == 422
    assert problem["errors"]  # validation detail as an RFC 7807 extension member


def test_ricerca_indirizzo_by_progressivo_nazionale_resolves_via_prognazarea():
    # ADR 0021: progressivo mode resolves the odonimo via prognazarea, skips the
    # denomination search, then lists its accessi.
    transport = ScriptedTransport(
        {
            "anncsu-consultazione.prognazareaPost": Response(
                200, {"data": [{"prognaz": "919572", "denomuff": "ROMA"}]}
            ),
            "anncsu-consultazione.elencoaccessiprogPost": Response(
                200, {"data": [{"prognazacc": "1", "civico": "42"}]}
            ),
        }
    )
    executor = WorkflowExecutor(load_spec(ARAZZO_SPEC), transport)
    with _client_with(WorkflowApplicationService(executor)) as client:
        response = client.post(
            "/anncsu/v1/workflows/ricerca-indirizzo-completo",
            json={"codcom": "H501", "progressivo_nazionale": "919572", "numero_civico": "42"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["odonimi"][0]["prognaz"] == "919572"
    assert body["accessi"][0]["prognazacc"] == "1"
    assert "anncsu-consultazione.elencoodonimiprogPost" not in [op for op, _ in transport.calls]


def test_ricerca_indirizzo_rejects_both_denominazione_and_progressivo():
    # Mutually exclusive selectors (ADR 0021): providing both is a 422.
    with _client_scripted({}) as client:
        response = client.post(
            "/anncsu/v1/workflows/ricerca-indirizzo-completo",
            json={"codcom": "H501", "denom_odonimo": "ROMA", "progressivo_nazionale": "919572"},
        )

    assert response.status_code == 422
    assert response.json()["errors"]


def test_sopprimi_accesso_route_suppresses_one_accesso():
    """Standalone single-accesso suppression (still also used by the odonimo foreach)."""
    transport = ScriptedTransport(
        {"anncsu-accessi.gestioneAnncsuPdnd": Response(200, {"esito": "0"})}
    )
    executor = WorkflowExecutor(load_spec(ARAZZO_SPEC), transport)
    with _client_with(WorkflowApplicationService(executor)) as client:
        response = client.post(
            "/anncsu/v1/workflows/sopprimi-accesso",
            json={
                "codcom": "H501",
                "prognaz": "2000449",
                "prognazacc": "1370588",
                "data_soppressione": "08/10/2024",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["esito"] == "0"
    accesso = transport.calls[0][1]["richiesta"]
    assert accesso["progr_nazionale"] == "2000449"
    assert accesso["accesso"]["progr_civico"] == "1370588"
    assert accesso["accesso"]["operazione_civico"] == "S"
    assert accesso["accesso"]["data_valid_amm"] == "08/10/2024"


def test_sopprimi_accesso_requires_the_suppression_date():
    with _client_scripted({}) as client:
        response = client.post(
            "/anncsu/v1/workflows/sopprimi-accesso",
            json={
                "codcom": "H501",
                "prognaz": "2000449",
                "prognazacc": "1370588",
            },
        )
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"


# The odonimo as the consultation (prognazareaPost) returns it: a single hit with
# the denomination fields, but no delibera/provvedimento (administrative, not exposed).
def _odonimo_read_response(**overrides):
    data = {
        "prognaz": "2000449",
        "cododocomunale": "ABC123",
        "dug": "VIA",
        "denomloc": "CENTRO",
        "denomlingua1": "STRASSE ROM",
        "denomlingua2": None,
    }
    data.update(overrides)
    return Response(200, {"res": "OK", "data": [data]})


def _odonimo_update_transport(read=None) -> ScriptedTransport:
    return ScriptedTransport(
        {
            "anncsu-consultazione.prognazareaPost": read or _odonimo_read_response(),
            "anncsu-odonimi.gestioneAnncsuOdonimiPdnd": Response(
                200, {"esito": "0", "dati": [{"progr_nazionale": "2000449"}]}
            ),
        }
    )


def _run_odonimo_update(transport, payload):
    executor = WorkflowExecutor(load_spec(ARAZZO_SPEC), transport)
    with _client_with(WorkflowApplicationService(executor)) as client:
        return client.post("/anncsu/v1/workflows/aggiorna-odonimo-da-progressivo", json=payload)


_ODONIMO_BASE = {
    "codcom": "H501",
    "prognaz": "2000449",
    "denom_delibera": "VIA ROMA",
}


def test_aggiorna_odonimo_reads_then_writes():
    """Read-modify-write (ADR 0013): consultation lookup precedes the R write."""
    transport = _odonimo_update_transport()
    response = _run_odonimo_update(transport, {**_ODONIMO_BASE, "denom_localita": "PERIFERIA"})

    assert response.status_code == 200
    assert [op for op, _ in transport.calls] == [
        "anncsu-consultazione.prognazareaPost",
        "anncsu-odonimi.gestioneAnncsuOdonimiPdnd",
    ]
    assert transport.calls[0][1] == {"req": "prognazarea", "prognaz": "2000449"}


def test_odonimo_update_preserves_fetched_fields_and_overrides_input():
    transport = _odonimo_update_transport()
    response = _run_odonimo_update(transport, {**_ODONIMO_BASE, "denom_localita": "PERIFERIA"})

    assert response.status_code == 200
    richiesta = transport.calls[1][1]["richiesta"]
    assert richiesta["tipo_operazione"] == "R"
    assert richiesta["progr_nazionale"] == "2000449"
    assert richiesta["denom_delibera"] == "VIA ROMA"  # input only
    assert richiesta["dug"] == "VIA"  # preserved from read
    assert richiesta["denom_in_lingua_1"] == "STRASSE ROM"  # preserved from read
    assert richiesta["codice_comunale"] == "ABC123"  # preserved from read
    assert richiesta["denom_localita"] == "PERIFERIA"  # input overrides read


def test_odonimo_update_requires_denom_delibera():
    with _client_scripted({}) as client:
        response = client.post(
            "/anncsu/v1/workflows/aggiorna-odonimo-da-progressivo",
            json={"codcom": "H501", "prognaz": "2000449"},
        )
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert any("denom_delibera" in str(error.get("loc", ())) for error in response.json()["errors"])


def test_update_of_a_missing_odonimo_maps_to_422():
    transport = _odonimo_update_transport(read=Response(200, {"res": "KO", "data": []}))
    response = _run_odonimo_update(transport, {**_ODONIMO_BASE})

    assert response.status_code == 422
    assert "anncsu-odonimi.gestioneAnncsuOdonimiPdnd" not in [op for op, _ in transport.calls]


def test_workflow_routes_are_published_in_the_v1_openapi():
    with _client_scripted({}) as client:
        document = client.get("/anncsu/v1/openapi.json").json()

    for workflow_id in (
        "verifica-e-crea-indirizzo-completo",
        "aggiorna-accesso-da-progressivo",
        "aggiorna-odonimo-da-progressivo",
        "sopprimi-odonimo-completo",
        "sopprimi-accesso",
        "ricerca-indirizzo-completo",
        "ricerca-accessi-per-odonimo",
        "crea-accesso-per-odonimo",
        "verifica-e-crea-odonimo-completo",
    ):
        assert f"/anncsu/v1/workflows/{workflow_id}" in document["paths"]


def test_workflow_routes_declare_their_problem_responses():
    """The published contract documents the RFC 7807 failures (ADR 0008)."""
    with _client_scripted({}) as client:
        document = client.get("/anncsu/v1/openapi.json").json()

    for workflow_id in (
        "verifica-e-crea-indirizzo-completo",
        "aggiorna-accesso-da-progressivo",
        "aggiorna-odonimo-da-progressivo",
        "sopprimi-odonimo-completo",
        "sopprimi-accesso",
        "ricerca-indirizzo-completo",
        "ricerca-accessi-per-odonimo",
        "crea-accesso-per-odonimo",
        "verifica-e-crea-odonimo-completo",
    ):
        responses = document["paths"][f"/anncsu/v1/workflows/{workflow_id}"]["post"]["responses"]
        for status in ("422", "500", "502"):
            assert "application/problem+json" in responses[status]["content"], (
                f"{workflow_id} does not declare a problem+json {status} response"
            )


def test_all_workflows_declare_named_request_examples():
    """Every workflow publishes named request examples; workflows with optional
    fields cover the with/without variations (not just one minimal example)."""
    expected = {
        "verifica-e-crea-indirizzo-completo": {"minimal", "with_validity_date"},
        "aggiorna-accesso-da-progressivo": {
            "coordinates_only",
            "attribute_only",
            "mixed",
        },
        "aggiorna-odonimo-da-progressivo": {"locality_only", "with_delibera"},
        "ricerca-indirizzo-completo": {
            "by_odonimo",
            "by_progressivo_nazionale",
            "by_odonimo_and_civico",
            "by_civico_and_esponente",
            "by_civico_esponente_specificita",
        },
        "ricerca-accessi-per-odonimo": {"by_civico", "by_metrico"},
        "crea-accesso-per-odonimo": {"civic", "civic_with_esponente", "metric"},
        "verifica-e-crea-odonimo-completo": {"minimal", "with_delibera"},
        "sopprimi-odonimo-completo": {"default"},
        "sopprimi-accesso": {"default"},
    }
    with _client_scripted({}) as client:
        document = client.get("/anncsu/v1/openapi.json").json()

    for workflow_id, names in expected.items():
        content = document["paths"][f"/anncsu/v1/workflows/{workflow_id}"]["post"]["requestBody"][
            "content"
        ]["application/json"]
        examples = set(content.get("examples", {}))
        assert names <= examples, f"{workflow_id} missing examples: {names - examples}"


def test_the_visualizer_page_is_not_part_of_the_contract():
    """/workflows/ui is an HTML page for humans, not API surface."""
    with _client_scripted({}) as client:
        document = client.get("/anncsu/v1/openapi.json").json()

    assert "/workflows/ui" not in document["paths"]
    assert "/health" in document["paths"]  # health stays documented
