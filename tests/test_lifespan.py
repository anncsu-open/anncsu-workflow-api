"""Tests for the application lifespan and DI of the authenticated service (ADR 0015).

The lifespan builds the authenticated workflow service once and stores it on
``app.state``; the route dependency resolves it from there. Everything is exercised
behind fakes (fake auth managers / SDK classes / builder), so no PDND credentials
or network are needed.
"""

from types import SimpleNamespace
from typing import cast

from anncsu.common.config import ClientAssertionSettings
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import main
from app.adapters.anncsu.auth import SOURCES
from app.application.service import WorkflowApplicationService
from app.config import settings
from app.routers.workflows import build_workflow_service, get_workflow_service


class _FakeManager:
    def __init__(self) -> None:
        self.calls = 0

    def get_access_token(self) -> str:
        self.calls += 1
        return "voucher"


def _assertion_settings() -> ClientAssertionSettings:
    return ClientAssertionSettings(
        kid="kid",
        issuer="client-id",
        subject="client-id",
        audience="https://auth.uat.interop.pagopa.it/token.oauth2",
        purpose_id_pa="",
        purpose_id_coordinate="",
        purpose_id_coordinate_bulk="",
        purpose_id_accessi="",
        purpose_id_interni="",
        purpose_id_odonimi="",
        private_key="dummy-key",
    )


def test_get_workflow_service_resolves_from_app_state():
    sentinel = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(workflow_service=sentinel)))
    assert get_workflow_service(cast(Request, request)) is sentinel


def test_build_workflow_service_wires_an_authenticated_service_without_network():
    def manager_factory(**kwargs):
        return _FakeManager()

    service, auth_managers, client_manager = build_workflow_service(
        settings,
        _assertion_settings(),
        manager_factory=manager_factory,
    )

    assert isinstance(service, WorkflowApplicationService)
    assert set(auth_managers) == set(SOURCES)
    # The client manager exposes a per-source lock (used by /ready).
    assert all(client_manager.lock(source) is not None for source in SOURCES)
    # Building the service must not fetch any token (lazy: clients/URLs built on first use).
    assert all(manager.calls == 0 for manager in auth_managers.values())


def test_lifespan_populates_app_state(monkeypatch):
    fake_service = object()
    fake_managers = {"anncsu-accessi": object()}
    fake_client_manager = object()
    monkeypatch.setattr(main, "ClientAssertionSettings", lambda: "ASSERTION")
    monkeypatch.setattr(
        main,
        "build_workflow_service",
        lambda _settings, _assertion: (fake_service, fake_managers, fake_client_manager),
    )

    with TestClient(main.app):
        pass

    assert main.app.state.workflow_service is fake_service
    assert main.app.state.auth_managers is fake_managers
    assert main.app.state.client_manager is fake_client_manager
