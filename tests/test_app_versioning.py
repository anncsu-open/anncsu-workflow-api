"""Tests for the app's /v1 versioning and localized OpenAPI wiring (ADR 0005)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_stays_unversioned():
    assert client.get("/health").status_code == 200


def test_v1_openapi_is_served():
    resp = client.get("/v1/openapi.json")
    assert resp.status_code == 200
    body = resp.json()
    assert "openapi" in body
    assert "info" in body


def test_v1_openapi_accepts_language_selection():
    # The endpoint must accept ?lang= and Accept-Language without erroring,
    # even when no workflow schemas are documented yet.
    assert client.get("/v1/openapi.json?lang=it").status_code == 200
    assert client.get("/v1/openapi.json", headers={"Accept-Language": "it"}).status_code == 200


def test_default_openapi_is_disabled():
    # The contract lives under /v1; the unversioned default doc is off.
    assert client.get("/openapi.json").status_code == 404


def test_v1_docs_and_redoc_served():
    assert client.get("/v1/docs").status_code == 200
    assert client.get("/v1/redoc").status_code == 200
