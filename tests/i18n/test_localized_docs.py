"""Integration tests for the localized, versioned OpenAPI docs wiring.

Uses a minimal app with one model-bearing endpoint so the workflow schemas appear
in the OpenAPI components, then checks language selection via query and header.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.i18n.fastapi import setup_localized_docs
from app.models.workflows import CreaIndirizzoCompletoInput


@pytest.fixture
def client() -> TestClient:
    app = FastAPI(title="Test")

    @app.post("/v1/echo")
    def echo(body: CreaIndirizzoCompletoInput) -> dict:
        return {}

    setup_localized_docs(app, prefix="/v1")
    return TestClient(app)


def _codcom_description(client: TestClient, url: str, **kwargs) -> str:
    schema = client.get(url, **kwargs).json()
    props = schema["components"]["schemas"]["CreaIndirizzoCompletoInput"]["properties"]
    return props["codcom"]["description"]


def test_default_openapi_is_english(client):
    assert _codcom_description(client, "/v1/openapi.json") == "Belfiore municipality code (codcom)"


def test_query_param_localizes_to_italian(client):
    assert _codcom_description(client, "/v1/openapi.json?lang=it") == "Codice Belfiore del comune"


def test_accept_language_header_localizes(client):
    desc = _codcom_description(client, "/v1/openapi.json", headers={"Accept-Language": "it"})
    assert desc == "Codice Belfiore del comune"


def test_query_param_overrides_header(client):
    desc = _codcom_description(
        client, "/v1/openapi.json?lang=en", headers={"Accept-Language": "it"}
    )
    assert desc == "Belfiore municipality code (codcom)"


def test_swagger_and_redoc_served_under_v1(client):
    assert client.get("/v1/docs").status_code == 200
    assert client.get("/v1/redoc").status_code == 200
