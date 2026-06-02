"""Tests for the FastAPI app and the Arazzo visualization route."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_workflows_ui_serves_arazzo_ui_page():
    resp = client.get("/workflows/ui")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    # The page mounts arazzo-ui from esm.sh, pointing at the spec we serve.
    assert "ArazzoUIStandalone" in body
    assert "@jentic/arazzo-ui" in body
    assert "/workflows/spec/anncsu-workflow.arazzo.yaml" in body


def test_arazzo_spec_is_served_statically():
    resp = client.get("/workflows/spec/anncsu-workflow.arazzo.yaml")
    assert resp.status_code == 200
    assert "arazzo: 1.0.0" in resp.text


def test_openapi_source_with_special_chars_is_served():
    # The consultation file name contains spaces and an en-dash (–):
    # arazzo-ui's relative resolution depends on this.
    resp = client.get("/workflows/spec/Specifica API - ANNCSU – Consultazione per le PA.yaml")
    assert resp.status_code == 200
