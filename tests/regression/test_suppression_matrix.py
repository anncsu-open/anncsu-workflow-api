"""End-to-end regression for odonimo suppression under both server hypotheses.

How ANNCSU handles suppressing an odonimo that still has accessi is unconfirmed
(ADR 0003): it may reject with esito 23 / error 320, or silently cascade. The
canonical spec suppresses every accesso explicitly (``x-executor.foreach``)
before the odonimo, which is correct under BOTH hypotheses. These tests pin that
property end-to-end — HTTP route -> application service -> engine -> SDK adapter
-> the REAL anncsu-sdk clients — against a stateful fake ANNCSU served through
``httpx.MockTransport``. No PDND credentials involved.

Running through the real SDK also verifies the wire shapes the unit tests assume
(request serialization, response models) against anncsu-sdk itself.
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


class FakeAnncsuServer:
    """A stateful fake ANNCSU behind ``httpx.MockTransport``.

    Holds one odonimo with its accessi and serves the endpoints the workflows
    touch. ``mode`` selects the unconfirmed server behaviour for suppressing an
    odonimo that still has accessi: ``"reject"`` answers esito 23 (error 320),
    ``"cascade"`` silently deletes the residual accessi. Every request is
    recorded in ``log`` as ``(path, body)``.
    """

    def __init__(self, *, accessi: list[str], mode: str) -> None:
        self.mode = mode
        self.odonimo = {"prognaz": "2000449", "dug": "VIA", "denomuff": "ROMA"}
        self.accessi = {
            p: {"prognazacc": p, "civico": str(n)} for n, p in enumerate(accessi, start=1)
        }
        self.odonimo_suppressed = False
        self.log: list[tuple[str, dict]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.read() or b"{}")
        self.log.append((path, body))
        return httpx.Response(200, json=getattr(self, f"_{path}")(body))

    def _elencoodonimiprog(self, body: dict) -> dict:
        return {"res": "OK", "data": [self.odonimo]}

    def _elencoaccessiprog(self, body: dict) -> dict:
        return {"res": "OK", "data": list(self.accessi.values())}

    def _accessi(self, body: dict) -> dict:
        accesso = body["richiesta"]["accesso"]
        if accesso.get("operazione_civico") == "S":
            self.accessi.pop(accesso["progr_civico"], None)
        return {"esito": "0", "messaggio": "Operazione eseguita"}

    def _odonimi(self, body: dict) -> dict:
        if body["richiesta"].get("tipo_operazione") == "S":
            if self.accessi and self.mode == "reject":
                return {"esito": "23", "messaggio": "Errore 320: accessi presenti"}
            self.accessi.clear()  # cascade (or nothing left to cascade)
            self.odonimo_suppressed = True
        return {"esito": "0", "messaggio": "Operazione eseguita"}


@contextmanager
def _client(server: FakeAnncsuServer):
    """Wire the REAL sub-SDK clients onto the fake server and override the DI."""

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
    service = WorkflowApplicationService(executor)
    app.dependency_overrides[get_workflow_service] = lambda: service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)


def _suppress(client: TestClient):
    return client.post(
        "/v1/workflows/sopprimi-odonimo-completo",
        json={"codcom": "H501", "denom_odonimo": "ROMA", "data_soppressione": "08/10/2024"},
    )


def test_suppression_succeeds_when_the_server_rejects_residual_accessi():
    """Reject hypothesis: explicit per-accesso suppression makes the workflow pass."""
    server = FakeAnncsuServer(accessi=["a1", "a2"], mode="reject")

    with _client(server) as client:
        response = _suppress(client)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["progressivo_nazionale"] == "2000449"
    assert [a["prognazacc"] for a in body["accessi_presenti"]] == ["a1", "a2"]
    assert server.accessi == {}
    assert server.odonimo_suppressed is True


def test_suppression_stays_explicit_when_the_server_would_cascade():
    """Cascade hypothesis: every accesso is still suppressed by an explicit,
    traceable call — the workflow never relies on silent server-side deletions."""
    server = FakeAnncsuServer(accessi=["a1", "a2"], mode="cascade")

    with _client(server) as client:
        response = _suppress(client)

    assert response.status_code == 200
    explicit = [
        body["richiesta"]["accesso"]["progr_civico"]
        for path, body in server.log
        if path == "accessi"
    ]
    assert explicit == ["a1", "a2"]  # tracked deletions, one per accesso
    assert server.odonimo_suppressed is True


def test_accessi_are_suppressed_before_the_odonimo():
    """The x-executor.foreach ordering invariant, observed from the server side."""
    server = FakeAnncsuServer(accessi=["a1", "a2"], mode="reject")

    with _client(server) as client:
        _suppress(client)

    operations = [path for path, _ in server.log if path in ("accessi", "odonimi")]
    assert operations == ["accessi", "accessi", "odonimi"]


def test_suppression_of_an_odonimo_without_accessi_skips_the_loop():
    server = FakeAnncsuServer(accessi=[], mode="reject")

    with _client(server) as client:
        response = _suppress(client)

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert [path for path, _ in server.log if path == "accessi"] == []
    assert server.odonimo_suppressed is True


def test_generic_accesso_update_through_the_real_sdk():
    """The R replace payload reaches the wire complete and without nulls (ADR 0010)."""

    class UpdateServer(FakeAnncsuServer):
        def _accessi(self, body: dict) -> dict:
            richiesta = body["richiesta"]
            assert richiesta["progr_nazionale"] == "2000449"
            accesso = richiesta["accesso"]
            assert accesso["operazione_civico"] == "R"
            # Unset optionals (metrico, specificita, isolato, ...) must be absent,
            # not null: under replace semantics the difference matters.
            assert None not in accesso.values()
            assert "metrico" not in accesso
            assert accesso["numero"] == "42"
            assert accesso["esponente"] == "B"
            assert accesso["sezione_censimento"] == "580911010001"
            return {"esito": "0", "dati": [{"progr_civico": "1370588", "numero": "42"}]}

    server = UpdateServer(accessi=[], mode="reject")

    with _client(server) as client:
        response = client.post(
            "/v1/workflows/aggiorna-accesso-da-progressivo",
            json={
                "codcom": "H501",
                "prognaz": "2000449",
                "prognazacc": "1370588",
                "numero": "42",
                "esponente": "B",
                "sezione_censimento": "580911010001",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["prognazacc"] == "1370588"
    assert body["accesso"]["progr_civico"] == "1370588"


def test_create_branch_path_through_the_real_sdk():
    """Happy/branch path of the upsert saga through the real SDK serialization."""

    class CreateServer(FakeAnncsuServer):
        def _esisteodonimo(self, body: dict) -> dict:
            return {"res": "OK", "data": False}

        def _esisteaccesso(self, body: dict) -> dict:
            return {"res": "OK", "data": False}

        def _odonimi(self, body: dict) -> dict:
            assert body["richiesta"]["tipo_operazione"] == "I"
            return {"esito": "0", "dati": [{"progr_nazionale": "2000449"}]}

        def _accessi(self, body: dict) -> dict:
            accesso = body["richiesta"]["accesso"]
            assert accesso["operazione_civico"] == "I"
            # Required by the OAS for I/R; the server rejects the insert without it.
            assert accesso["sezione_censimento"] == "580911010001"
            return {"esito": "0", "dati": [{"progr_civico": "1370588"}]}

    server = CreateServer(accessi=[], mode="reject")

    with _client(server) as client:
        response = client.post(
            "/v1/workflows/verifica-e-crea-indirizzo-completo",
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
