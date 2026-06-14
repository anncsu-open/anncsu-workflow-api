"""Tests for the structured-logging setup (ADR 0014).

configure_logging is called inside each test (after capsys has patched stdout) so
the StreamHandler binds to the captured stream — letting us assert the rendered
JSON, including secret redaction and the bound request id.
"""

import json
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.config import Settings
from app.executor.engine import StepFailedError
from app.logging import bind_request_id, configure_logging, get_logger, redact_sensitive
from app.main import app
from app.ports.transport import TransportError
from app.routers.workflows import get_workflow_service


def _last_json_line(capsys) -> dict:
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    return json.loads(lines[-1])


def test_redact_masks_sensitive_keys_only():
    out = redact_sensitive(
        None,
        "info",
        {
            "authorization": "Bearer x",
            "token": "t",
            "jwt_assertion": "a",
            "pdnd_client_secret": "s",
            "codcom": "H501",
        },
    )
    assert out["authorization"] == "***"
    assert out["token"] == "***"
    assert out["jwt_assertion"] == "***"
    assert out["pdnd_client_secret"] == "***"
    assert out["codcom"] == "H501"  # a domain identifier, not a secret


def test_configure_logging_is_idempotent():
    configure_logging(Settings(log_level="INFO", log_format="json"))
    configure_logging(Settings(log_level="DEBUG", log_format="console"))
    assert get_logger("x") is not None


def test_json_format_emits_a_structured_line(capsys):
    configure_logging(Settings(log_level="INFO", log_format="json"))
    get_logger("test").info("hello.event", foo="bar")

    payload = _last_json_line(capsys)
    assert payload["event"] == "hello.event"
    assert payload["foo"] == "bar"
    assert payload["level"] == "info"
    assert "timestamp" in payload


def test_secrets_are_redacted_end_to_end(capsys):
    configure_logging(Settings(log_level="INFO", log_format="json"))
    get_logger("test").info("auth", authorization="Bearer super-secret-token")

    payload = _last_json_line(capsys)
    assert payload["authorization"] == "***"


def test_bound_request_id_appears_in_logs(capsys):
    configure_logging(Settings(log_level="INFO", log_format="json"))
    with bind_request_id("req-123"):
        get_logger("test").info("inside.request")
    payload = _last_json_line(capsys)
    assert payload["request_id"] == "req-123"


def test_level_filters_below_threshold(capsys):
    configure_logging(Settings(log_level="WARNING", log_format="json"))
    get_logger("test").info("should.be.filtered")
    assert capsys.readouterr().out.strip() == ""


# --- request-context middleware + correlation id (integration) ---------------


@pytest.fixture
def client(capsys):
    configure_logging(Settings(log_level="INFO", log_format="json"))  # bind to capsys stdout
    return TestClient(app)


def test_response_carries_a_request_id_header(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_inbound_request_id_is_echoed(client):
    response = client.get("/health", headers={"X-Request-ID": "req-abc"})
    assert response.headers["X-Request-ID"] == "req-abc"


def test_request_start_and_end_are_logged(client):
    with capture_logs() as logs:
        client.get("/health")
    by_event = {e["event"]: e for e in logs if "event" in e}
    assert "request.start" in by_event
    assert by_event["request.end"]["status_code"] == 200
    assert "duration_ms" in by_event["request.end"]


@contextmanager
def _override_service(error: Exception):
    class _Raising:
        async def run(self, *_args, **_kwargs):
            raise error

    app.dependency_overrides[get_workflow_service] = _Raising
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


def test_transport_error_is_logged_and_carries_request_id():
    with _override_service(TransportError("pdnd unreachable")) as app:
        with capture_logs() as logs:
            response = TestClient(app).post(
                "/v1/workflows/ricerca-indirizzo-completo",
                json={"codcom": "H501", "denom_odonimo": "ROMA"},
                headers={"X-Request-ID": "req-502"},
            )

    assert response.status_code == 502
    assert response.json()["request_id"] == "req-502"  # propagated onto the Problem body
    errors = [e for e in logs if e.get("log_level") == "error"]
    assert any("pdnd unreachable" in str(e) for e in errors)


def test_step_failure_is_logged_as_warning():
    with _override_service(StepFailedError("step x failed")) as app:
        with capture_logs() as logs:
            response = TestClient(app).post(
                "/v1/workflows/ricerca-indirizzo-completo",
                json={"codcom": "H501", "denom_odonimo": "ROMA"},
            )

    assert response.status_code == 422
    assert any(e.get("log_level") == "warning" for e in logs)
