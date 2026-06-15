"""End-to-end regression for address creation/update through the REAL anncsu-sdk.

Drives HTTP route -> application service -> engine -> SDK adapter -> the real
anncsu-sdk clients against a fake ANNCSU (``httpx.MockTransport``), so the wire
shapes are checked against the SDK's own serialization — which the unit tests,
using a scripted transport, bypass. In particular this pins that the accesso
coordinate block and the new full fields actually reach the wire (a payload key
the SDK model does not know is silently dropped). No PDND credentials involved.
"""

import json
from contextlib import contextmanager
from pathlib import Path

import httpx
from anncsu.accessi import AnncsuAccessi
from anncsu.coordinate import AnncsuCoordinate
from anncsu.odonimi import AnncsuOdonimi
from anncsu.pa import AnncsuConsultazione
from fastapi.testclient import TestClient

from app.adapters.anncsu import AnncsuClientManager, AnncsuSdkTransport
from app.application.service import WorkflowApplicationService
from app.executor.engine import WorkflowExecutor
from app.executor.spec import load_spec
from app.main import app
from app.routers.workflows import get_workflow_service

SPECS_DIR = Path(__file__).resolve().parent.parent.parent / "specs"
ARAZZO_SPEC = SPECS_DIR / "anncsu-workflow.arazzo.yaml"


class FakeAnncsu:
    """Records every request body and serves the create/update endpoints."""

    def __init__(
        self,
        *,
        odonimo_exists: bool = False,
        accesso_exists: bool = False,
        accessi_found: bool = True,
    ) -> None:
        self.odonimo_exists = odonimo_exists
        self.accesso_exists = accesso_exists
        self.accessi_found = accessi_found
        self.log: list[tuple[str, dict]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.read() or b"{}")
        self.log.append((path, body))
        result = getattr(self, f"_{path}")(body)
        # A handler may return a ready Response to simulate a non-200 (e.g. ANNCSU's
        # 404 "no results"); otherwise the dict is the 200 JSON body.
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=result)

    def received(self, path: str) -> dict:
        return next(body for seen, body in self.log if seen == path)

    def _esisteodonimo(self, body: dict) -> dict:
        return {"res": "OK", "data": self.odonimo_exists}

    def _elencoodonimiprog(self, body: dict) -> dict:
        # The REAL wire shape (anncsu-sdk#12): the API returns `duf` (not the OAS
        # `denomuff`) plus the extra `cododocomunale`.
        return {
            "res": "OK",
            "data": [
                {
                    "prognaz": "2000449",
                    "cododocomunale": "5786",
                    "dug": "VIA",
                    "duf": "ROMA",
                    "denomloc": "",
                    "denomlingua1": "",
                    "denomlingua2": "",
                }
            ],
        }

    def _elencoaccessiprog(self, body: dict) -> dict | httpx.Response:
        if not self.accessi_found:
            # ANNCSU answers 404 (problem+json) when a search matches nothing; the
            # real SDK raises this as a typed error the transport maps back.
            return httpx.Response(
                404,
                json={
                    "title": "non trovati accessi per valori forniti alla funzione elencoaccessiprog",
                    "detail": "non trovati accessi per progressivo nazionale odonimo '919572'",
                },
            )
        # Real wire shape for accessi (anncsu-sdk#12): coordX/coordY + codacccomunale.
        return {
            "res": "OK",
            "data": [
                {
                    "prognazacc": "1370588",
                    "codacccomunale": "",
                    "civico": "42",
                    "esp": "",
                    "specif": "",
                    "metrico": "",
                    "coordX": "12.49",
                    "coordY": "41.90",
                    "quota": "0",
                    "metodo": "3",
                }
            ],
        }

    def _esisteaccesso(self, body: dict) -> dict:
        return {"res": "OK", "data": self.accesso_exists}

    def _prognazacc(self, body: dict) -> dict:
        # leggi-accesso (accesso update): the read the x-coalesce falls back on.
        return {"res": "OK", "data": [{"civico": "42"}]}

    def _odonimi(self, body: dict) -> dict:
        return {"esito": "0", "dati": [{"progr_nazionale": "2000449"}]}

    def _accessi(self, body: dict) -> dict:
        return {"esito": "0", "dati": [{"progr_civico": "1370588"}]}


@contextmanager
def _client(server: FakeAnncsu):
    def sdk(client_type, api: str):
        return client_type(
            server_url=f"https://anncsu.test/{api}/v1",
            client=httpx.Client(transport=server.transport()),
        )

    manager = AnncsuClientManager(
        clients={
            "anncsu-consultazione": sdk(AnncsuConsultazione, "consultazione"),
            "anncsu-odonimi": sdk(AnncsuOdonimi, "odonimi"),
            "anncsu-accessi": sdk(AnncsuAccessi, "accessi"),
            "anncsu-coordinate": sdk(AnncsuCoordinate, "coordinate"),
        }
    )
    executor = WorkflowExecutor(load_spec(ARAZZO_SPEC), AnncsuSdkTransport(manager))
    app.dependency_overrides[get_workflow_service] = lambda: WorkflowApplicationService(executor)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)


def test_create_civic_sends_full_accesso_fields_to_the_wire():
    server = FakeAnncsu(odonimo_exists=False, accesso_exists=False)
    with _client(server) as client:
        response = client.post(
            "/v1/workflows/verifica-e-crea-indirizzo-completo",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA",
                "dug": "VIA",
                "numero_civico": "42",
                "sezione_censimento": "580911010001",
                "esponente": "A",
                "coordinata_x": "13.1022000",
                "coordinata_y": "41.8847600",
                "coordinata_z": "150",
                "metodo": "3",
            },
        )

    assert response.status_code == 200
    accesso = server.received("accessi")["richiesta"]["accesso"]
    assert accesso["operazione_civico"] == "I"
    assert accesso["esponente"] == "A"
    # The coordinate block must reach the wire with the SDK's own field names.
    assert accesso["coordinate"] == {
        "x": "13.1022000",
        "y": "41.8847600",
        "z": "150",
        "metodo": "3",
    }


def test_create_metric_skips_the_civic_existence_check_on_the_wire():
    server = FakeAnncsu(odonimo_exists=False)
    with _client(server) as client:
        response = client.post(
            "/v1/workflows/verifica-e-crea-indirizzo-completo",
            json={
                "codcom": "H501",
                "denom_odonimo": "ROMA",
                "dug": "VIA",
                "metrico": "300",
                "sezione_censimento": "580911010001",
            },
        )

    assert response.status_code == 200
    assert "esisteaccesso" not in [path for path, _ in server.log]
    assert server.received("accessi")["richiesta"]["accesso"]["metrico"] == "300"


def test_accesso_update_sends_coordinates_to_the_wire():
    server = FakeAnncsu()
    with _client(server) as client:
        response = client.post(
            "/v1/workflows/aggiorna-accesso-da-progressivo",
            json={
                "codcom": "H501",
                "prognaz": "2000449",
                "prognazacc": "1370588",
                "numero": "42",
                "sezione_censimento": "580911010001",
                "coordinata_x": "13.1022000",
                "coordinata_y": "41.8847600",
            },
        )

    assert response.status_code == 200
    accesso = server.received("accessi")["richiesta"]["accesso"]
    assert accesso["coordinate"]["x"] == "13.1022000"
    assert accesso["coordinate"]["y"] == "41.8847600"


def test_ricerca_maps_real_wire_field_names_through_the_sdk():
    # The full real chain: the API returns the wire names (`duf`, `coordX`, the
    # extra `cododocomunale`/`codacccomunale`); the SDK deserializes via its aliases
    # and the transport re-emits them, so the output models must match those names
    # (anncsu-sdk#12). A scripted transport would bypass this — hence the real SDK.
    server = FakeAnncsu()
    with _client(server) as client:
        response = client.post(
            "/v1/workflows/ricerca-indirizzo-completo",
            json={"codcom": "H501", "denom_odonimo": "ROMA", "numero_civico": "42"},
        )

    assert response.status_code == 200
    body = response.json()
    odonimo = body["odonimi"][0]
    assert odonimo["duf"] == "ROMA"  # real wire field (NOT the OAS `denomuff`)
    assert odonimo["cododocomunale"] == "5786"  # extra real field
    accesso = body["accessi"][0]
    assert accesso["coordX"] == "12.49"
    assert "codacccomunale" in accesso  # extra real field


def test_ricerca_returns_empty_accessi_when_the_sdk_raises_a_real_404():
    # The real SDK raises a typed error on ANNCSU's 404 "no results"; the transport
    # maps it back to a Response(404) and the search ends with empty accessi (200),
    # not a 422. A scripted transport never exercises this SDK error path.
    server = FakeAnncsu(accessi_found=False)
    with _client(server) as client:
        response = client.post(
            "/v1/workflows/ricerca-indirizzo-completo",
            json={"codcom": "H501", "denom_odonimo": "ROMA", "numero_civico": "1"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["odonimi"][0]["duf"] == "ROMA"  # odonimi still returned
    assert body["accessi"] == []  # 404 -> empty, the search did not hard-fail
    assert "elencoaccessiprog" in [path for path, _ in server.log]
