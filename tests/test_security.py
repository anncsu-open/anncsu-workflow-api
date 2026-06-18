"""Tests for the inbound security layer (ADR 0023): API-KEY + source-IP/hostname ACL.

The guard protects the workflow routes; probes/docs stay exempt. The workflow service
is scripted (a passing guard still needs a service for the 200 path).
"""

from contextlib import contextmanager
from pathlib import Path

import structlog
from fastapi.testclient import TestClient

from app.application.service import WorkflowApplicationService
from app.config import Settings
from app.executor.engine import WorkflowExecutor
from app.executor.spec import load_spec
from app.main import app
from app.ports.transport import Response
from app.routers.workflows import get_workflow_service
from app.security import get_settings
from tests.executor.support import ScriptedTransport

ARAZZO_SPEC = Path(__file__).resolve().parent.parent / "specs" / "anncsu-workflow.arazzo.yaml"
WF = "/anncsu/v1/workflows/ricerca-indirizzo-completo"
GOOD_BODY = {"codcom": "H501", "denom_odonimo": "ROMA"}  # no civico -> only the odonimi step
PROBLEM = "application/problem+json"


def _scripted_service() -> WorkflowApplicationService:
    transport = ScriptedTransport(
        {"anncsu-consultazione.elencoodonimiprogPost": Response(200, {"data": [{"prognaz": "1"}]})}
    )
    return WorkflowApplicationService(WorkflowExecutor(load_spec(ARAZZO_SPEC), transport))


@contextmanager
def _client(*, api_key="secret", allowed_ips=None, allowed_fqdn=None):
    cfg = Settings(api_key=api_key, allowed_ips=allowed_ips or [], allowed_fqdn=allowed_fqdn or [])
    app.dependency_overrides[get_settings] = lambda: cfg
    app.dependency_overrides[get_workflow_service] = _scripted_service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_workflow_service, None)


# Headers that satisfy the ACL (real IP for the CIDR check; testserver is the host).
_OK = {"X-API-KEY": "secret", "X-Real-IP": "10.0.0.5"}


def test_valid_key_and_acl_passes():
    with _client(allowed_ips=["10.0.0.0/8"], allowed_fqdn=["testserver"]) as client:
        response = client.post(WF, json=GOOD_BODY, headers=_OK)
    assert response.status_code == 200


def test_missing_api_key_is_401():
    with _client(allowed_ips=["10.0.0.0/8"], allowed_fqdn=["testserver"]) as client:
        response = client.post(WF, json=GOOD_BODY, headers={"X-Real-IP": "10.0.0.5"})
    assert response.status_code == 401
    assert response.headers["content-type"] == PROBLEM


def test_wrong_api_key_is_401():
    with _client(allowed_ips=["10.0.0.0/8"], allowed_fqdn=["testserver"]) as client:
        response = client.post(WF, json=GOOD_BODY, headers={**_OK, "X-API-KEY": "nope"})
    assert response.status_code == 401


def test_ip_outside_allowlist_is_403():
    with _client(allowed_ips=["10.0.0.0/8"], allowed_fqdn=["testserver"]) as client:
        response = client.post(WF, json=GOOD_BODY, headers={**_OK, "X-Real-IP": "1.2.3.4"})
    assert response.status_code == 403
    assert response.headers["content-type"] == PROBLEM


def test_host_outside_allowlist_is_403():
    with _client(allowed_ips=["10.0.0.0/8"], allowed_fqdn=["other.example"]) as client:
        response = client.post(WF, json=GOOD_BODY, headers=_OK)
    assert response.status_code == 403


def test_empty_acl_lists_are_not_restricted():
    # ADR 0023: ALLOWED_IPS/ALLOWED_FQDN empty -> that dimension is not enforced;
    # only the API-KEY is required.
    with _client(allowed_ips=[], allowed_fqdn=[]) as client:
        response = client.post(WF, json=GOOD_BODY, headers={"X-API-KEY": "secret"})
    assert response.status_code == 200


def test_probe_is_exempt_from_the_guard():
    with _client(allowed_ips=["10.0.0.0/8"], allowed_fqdn=["testserver"]) as client:
        response = client.get("/health")  # no key, no ACL headers
    assert response.status_code == 200


def test_openapi_advertises_the_api_key_scheme():
    with _client() as client:
        schema = client.get("/anncsu/v1/openapi.json").json()
    schemes = schema.get("components", {}).get("securitySchemes", {})
    assert any(
        s.get("type") == "apiKey" and s.get("in") == "header" and s.get("name") == "X-API-KEY"
        for s in schemes.values()
    )


def test_api_key_is_never_logged():
    with _client(allowed_ips=["10.0.0.0/8"], allowed_fqdn=["testserver"]) as client:
        with structlog.testing.capture_logs() as logs:
            client.post(WF, json=GOOD_BODY, headers=_OK)
    assert "secret" not in str(logs)


def test_rejected_host_is_logged():
    # The host that failed the allowlist is logged (with the allowlist) for diagnosis.
    with _client(allowed_ips=["10.0.0.0/8"], allowed_fqdn=["other.example"]) as client:
        with structlog.testing.capture_logs() as logs:
            client.post(WF, json=GOOD_BODY, headers=_OK)
    assert any(
        log.get("event") == "access.host_not_allowed" and log.get("host") == "testserver"
        for log in logs
    )
