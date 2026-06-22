"""Tests for ``AnncsuSdkTransport``: the production adapter behind ``WorkflowTransport``.

The SDK boundary is faked (recorded callables on objects shaped like the sub-SDK
clients), but everything that crosses it is real: real SDK response models on
success and real SDK error classes on failure, so the response-adapter mapping
(decision D3) and the error boundary (ADR 0008) are pinned against anncsu-sdk types:

- HTTP outcome reached the service (200 body, or a documented 4xx/5xx raised by the
  SDK as ``AnncsuBaseError``) -> normalized ``Response``; the Arazzo spec evaluates it.
- The call itself failed (network, no response, token refresh) -> ``TransportError``.
"""

import asyncio
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from anncsu.accessi import models as accessi_models
from anncsu.common.errors import NoResponseError
from anncsu.common.hooks.token_validation import TokenRefreshError
from anncsu.common.pdnd_token import TokenResponseError
from anncsu.pa import errors as pa_errors
from anncsu.pa import models as pa_models
from structlog.testing import capture_logs

from app.adapters.anncsu.auth import AudienceDiscoveryError
from app.adapters.anncsu.client_manager import AnncsuClientManager
from app.adapters.anncsu.registry import UnknownOperationError
from app.adapters.anncsu.transport import AnncsuSdkTransport
from app.config import Settings
from app.logging import configure_logging
from app.ports.transport import TransportError, WorkflowTransport

ESISTE_ODONIMO = "anncsu-consultazione.esisteOdonimoPost"
GESTIONE_ACCESSI = "anncsu-accessi.gestioneAnncsuPdnd"


def _transport(fake_clients: dict) -> AnncsuSdkTransport:
    return AnncsuSdkTransport(AnncsuClientManager(clients=fake_clients))


def _recorded(result):
    """A fake sync SDK method that records kwargs and returns/raises ``result``."""
    calls: list[dict] = []

    def method(**kwargs):
        calls.append(kwargs)
        if isinstance(result, Exception):
            raise result
        return result

    return method, calls


def _consultazione(method) -> dict:
    return {
        "anncsu-consultazione": SimpleNamespace(
            json_post=SimpleNamespace(esiste_odonimo_post=method)
        )
    }


def _accessi(method) -> dict:
    return {"anncsu-accessi": SimpleNamespace(anncsu=SimpleNamespace(gestione_anncsu_pdnd=method))}


def _building_transport(source: str, builder) -> AnncsuSdkTransport:
    """A transport whose client for ``source`` is built lazily by ``builder``.

    Drives the build-time failure path (the voucher/token fetch on first use,
    ADR 0017), which the pre-built ``clients=`` helpers above cannot reach.
    """
    return AnncsuSdkTransport(AnncsuClientManager(builders={source: builder}))


def test_transport_satisfies_the_port_protocol():
    transport = _transport({})
    assert isinstance(transport, WorkflowTransport)


async def test_dispatch_returns_a_response_built_from_the_sdk_model():
    method, calls = _recorded(pa_models.EsisteOdonimoPostResponse(res="OK", data=True))
    transport = _transport(_consultazione(method))

    payload = {"req": "esisteodonimo", "codcom": "H501", "denom": "VIA ROMA"}
    response = await transport.dispatch(
        operation_id=ESISTE_ODONIMO,
        payload=payload,
        content_type="application/json",
    )

    assert calls == [payload]
    assert response.status_code == 200
    assert response.body["data"] is True
    assert response.body["res"] == "OK"


async def test_dispatch_routes_a_write_payload_to_the_sdk_kwargs():
    risposta = accessi_models.RispostaOperazione(
        esito="0",
        dati=[accessi_models.Dati(progr_civico="123", progr_nazionale="456")],
    )
    method, calls = _recorded(risposta)
    transport = _transport(_accessi(method))

    richiesta = {
        "codcom": "H501",
        "progr_nazionale": "456",
        "accesso": {"numero": "1"},
    }
    response = await transport.dispatch(
        operation_id=GESTIONE_ACCESSI,
        payload={"richiesta": richiesta},
        content_type="application/json",
    )

    assert calls == [{"richiesta": richiesta}]
    # The wire shape the Arazzo successCriteria/outputs read ([BLOCK_REST] in-band esito).
    assert response.status_code == 200
    assert response.body["esito"] == "0"
    assert response.body["dati"][0]["progr_civico"] == "123"


async def test_a_documented_http_error_becomes_a_response_for_the_spec():
    problem = {"title": "Unprocessable Entity", "detail": "error in json"}
    raw = httpx.Response(
        422,
        headers={"content-type": "application/problem+json"},
        json=problem,
        request=httpx.Request("POST", "https://example.test/anncsu/v1/esisteodonimo"),
    )
    error = pa_errors.EsisteOdonimoPostUnprocessableEntityError(
        pa_errors.EsisteOdonimoPostUnprocessableEntityErrorData(**problem), raw
    )
    method, _ = _recorded(error)
    transport = _transport(_consultazione(method))

    response = await transport.dispatch(
        operation_id=ESISTE_ODONIMO, payload={}, content_type="application/json"
    )

    assert response.status_code == 422
    assert response.body == problem
    assert response.headers["content-type"] == "application/problem+json"


async def test_a_non_json_http_error_body_falls_back_to_text():
    raw = httpx.Response(
        500,
        headers={"content-type": "text/html"},
        text="<html>gateway error</html>",
        request=httpx.Request("POST", "https://example.test/anncsu/v1/esisteodonimo"),
    )
    method, _ = _recorded(pa_errors.APIError("API error occurred", raw, raw.text))
    transport = _transport(_consultazione(method))

    response = await transport.dispatch(operation_id=ESISTE_ODONIMO, payload={}, content_type=None)

    assert response.status_code == 500
    assert response.body == "<html>gateway error</html>"


async def test_a_network_failure_raises_transport_error():
    method, _ = _recorded(httpx.ConnectError("connection refused"))
    transport = _transport(_consultazione(method))

    with pytest.raises(TransportError) as excinfo:
        await transport.dispatch(operation_id=ESISTE_ODONIMO, payload={}, content_type=None)
    assert isinstance(excinfo.value.__cause__, httpx.ConnectError)


async def test_a_missing_response_raises_transport_error():
    method, _ = _recorded(NoResponseError("No response received"))
    transport = _transport(_consultazione(method))

    with pytest.raises(TransportError):
        await transport.dispatch(operation_id=ESISTE_ODONIMO, payload={}, content_type=None)


async def test_a_failed_token_refresh_raises_transport_error():
    method, _ = _recorded(TokenRefreshError("PDND token refresh failed"))
    transport = _transport(_consultazione(method))

    with pytest.raises(TransportError) as excinfo:
        await transport.dispatch(operation_id=ESISTE_ODONIMO, payload={}, content_type=None)
    assert isinstance(excinfo.value.__cause__, TokenRefreshError)


async def test_a_token_generation_failure_at_build_raises_transport_error():
    # The lazy build fetches a voucher; PDND rejecting the token (e.g. 015-0008) must
    # not escape as a raw 500 -> it is a failure below the Arazzo contract (ADR 0024).
    def builder():
        raise TokenResponseError("Token request failed: 015-0008 - Unable to generate a token")

    transport = _building_transport("anncsu-accessi", builder)

    with pytest.raises(TransportError) as excinfo:
        await transport.dispatch(
            operation_id=GESTIONE_ACCESSI,
            payload={"richiesta": {}},
            content_type="application/json",
        )
    assert isinstance(excinfo.value.__cause__, TokenResponseError)


async def test_a_missing_voucher_audience_at_build_raises_transport_error():
    # The build cannot derive the e-service URL from the voucher (ADR 0017): this is a
    # TransportError, not a raw 500 (ADR 0024).
    def builder():
        raise AudienceDiscoveryError("no audience in the voucher for 'anncsu-accessi'")

    transport = _building_transport("anncsu-accessi", builder)

    with pytest.raises(TransportError) as excinfo:
        await transport.dispatch(
            operation_id=GESTIONE_ACCESSI,
            payload={"richiesta": {}},
            content_type="application/json",
        )
    assert isinstance(excinfo.value.__cause__, AudienceDiscoveryError)


async def test_an_unknown_operation_id_raises():
    transport = _transport(_consultazione(_recorded(None)[0]))

    with pytest.raises(UnknownOperationError):
        await transport.dispatch(
            operation_id="anncsu-consultazione.nope",
            payload={},
            content_type=None,
        )


async def test_the_sdk_call_runs_off_the_event_loop():
    """The sync SDK (blocking PDND token refresh, anncsu-sdk#35) must not block the loop."""
    observed: dict[str, bool] = {}

    def method(**kwargs):
        try:
            asyncio.get_running_loop()
            observed["off_loop"] = False
        except RuntimeError:
            observed["off_loop"] = True
        return pa_models.EsisteOdonimoPostResponse(data=False)

    transport = _transport(_consultazione(method))
    await transport.dispatch(operation_id=ESISTE_ODONIMO, payload={}, content_type=None)

    assert observed["off_loop"] is True


async def test_dispatches_to_the_same_api_are_serialized():
    """The per-API lock must prevent concurrent calls into one sub-SDK client."""
    in_flight = threading.Semaphore(1)
    overlapped: list[bool] = []

    def method(**kwargs):
        if not in_flight.acquire(blocking=False):
            overlapped.append(True)
        time.sleep(0.05)
        in_flight.release()
        return pa_models.EsisteOdonimoPostResponse(data=False)

    transport = _transport(_consultazione(method))
    await asyncio.gather(
        transport.dispatch(operation_id=ESISTE_ODONIMO, payload={}, content_type=None),
        transport.dispatch(operation_id=ESISTE_ODONIMO, payload={}, content_type=None),
    )

    assert not overlapped


async def test_a_hanging_dispatch_is_bounded_and_releases_the_lock():
    """Resilience: a hung SDK call must not hold the per-source lock forever.

    The dispatch is time-bounded; a call that does not return in time raises
    TransportError and releases the per-source lock, so the source stays usable for
    the next dispatch (otherwise one stuck PDND call blocks the whole source).
    """
    release = threading.Event()
    seen = {"n": 0}

    def method(**kwargs):
        seen["n"] += 1
        if seen["n"] == 1:
            release.wait(timeout=2)  # first call hangs past the dispatch timeout
        return pa_models.EsisteOdonimoPostResponse(data=False)

    transport = AnncsuSdkTransport(AnncsuClientManager(clients=_consultazione(method)), timeout=0.1)

    with pytest.raises(TransportError):
        await transport.dispatch(operation_id=ESISTE_ODONIMO, payload={}, content_type=None)

    # The lock was released despite the first call still running in its thread:
    # a second dispatch on the same source proceeds instead of blocking.
    response = await transport.dispatch(operation_id=ESISTE_ODONIMO, payload={}, content_type=None)
    assert response.status_code == 200
    release.set()


async def test_dispatches_to_different_apis_can_overlap():
    """The lock is per-API, not global: two sources may be in flight at once."""
    barrier = threading.Barrier(2, timeout=2)

    def consultazione_method(**kwargs):
        barrier.wait()
        return pa_models.EsisteOdonimoPostResponse(data=False)

    def accessi_method(**kwargs):
        barrier.wait()
        return accessi_models.RispostaOperazione(esito="0")

    clients = _consultazione(consultazione_method) | _accessi(accessi_method)
    transport = _transport(clients)

    await asyncio.gather(
        transport.dispatch(operation_id=ESISTE_ODONIMO, payload={}, content_type=None),
        transport.dispatch(operation_id=GESTIONE_ACCESSI, payload={}, content_type=None),
    )


async def test_dispatch_is_logged_with_operation_and_status():
    # Per-dispatch events are DEBUG; raise the threshold so capture_logs sees them.
    configure_logging(Settings(log_level="DEBUG", log_format="json"))
    method, _ = _recorded(pa_models.EsisteOdonimoPostResponse(data=True))
    transport = _transport(_consultazione(method))

    with capture_logs() as logs:
        await transport.dispatch(operation_id=ESISTE_ODONIMO, payload={}, content_type=None)

    dispatched = [e for e in logs if e.get("event") == "transport.dispatch"]
    assert dispatched and dispatched[0]["operation_id"] == ESISTE_ODONIMO
    assert dispatched[0]["status_code"] == 200
