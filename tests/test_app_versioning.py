"""Tests for the app's /v1 versioning and localized OpenAPI wiring (ADR 0005)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_probes_are_under_the_base_path_but_unversioned():
    # Probes sit under the service base path (so a single ingress prefix routes them)
    # but stay unversioned: /anncsu is the mount, /v1 is the contract version (ADR 0025).
    assert client.get("/anncsu/health").status_code == 200
    assert client.get("/anncsu/ready").status_code in (200, 503)
    assert client.get("/anncsu/v1/health").status_code == 404
    # The old root-level paths no longer exist (they collided across services).
    assert client.get("/health").status_code == 404
    assert client.get("/ready").status_code == 404


def test_v1_openapi_is_served():
    resp = client.get("/anncsu/v1/openapi.json")
    assert resp.status_code == 200
    body = resp.json()
    assert "openapi" in body
    assert "info" in body


def test_v1_openapi_accepts_language_selection():
    # The endpoint must accept ?lang= and Accept-Language without erroring,
    # even when no workflow schemas are documented yet.
    assert client.get("/anncsu/v1/openapi.json?lang=it").status_code == 200
    assert (
        client.get("/anncsu/v1/openapi.json", headers={"Accept-Language": "it"}).status_code == 200
    )


def test_default_openapi_is_disabled():
    # The contract lives under /v1; the unversioned default doc is off.
    assert client.get("/openapi.json").status_code == 404


def test_v1_docs_and_redoc_served():
    assert client.get("/anncsu/v1/docs").status_code == 200
    assert client.get("/anncsu/v1/redoc").status_code == 200


def test_openapi_has_no_unresolved_defs_refs():
    # Embedded schemas (e.g. the Problem error responses) must reference
    # `#/components/schemas/...`, not pydantic's local `#/$defs/...` which does not
    # resolve in the OpenAPI document (broke Swagger/ReDoc — ADR 0022 regression).
    spec = client.get("/anncsu/v1/openapi.json").json()
    refs: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str):
                    refs.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(spec)
    bad = sorted({r for r in refs if r.startswith("#/$defs/")})
    assert not bad, f"unresolved $defs refs in OpenAPI: {bad}"


def test_root_index_advertises_docs_and_openapi():
    # The service base is /anncsu; the index there makes the entry points discoverable.
    resp = client.get("/anncsu")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"]
    assert body["version"]
    assert body["openapi"] == "/anncsu/v1/openapi.json"
    assert body["docs"] == "/anncsu/v1/docs"
    assert body["redoc"] == "/anncsu/v1/redoc"
    assert body["health"] == "/anncsu/health"
    assert body["ready"] == "/anncsu/ready"


def test_bare_root_returns_404():
    # The bare / is not routed through the /anncsu ingress prefix (ADR 0025).
    assert client.get("/").status_code == 404
