"""Tests for application configuration (ADR 0015).

The app ``Settings`` carries only application concerns; PDND credentials live in
the SDK's ``ClientAssertionSettings`` (``PDND_*`` env), loaded from the same
``.env``. The PDND token endpoint is derived from ``use_validation_env``.
"""

from app.config import (
    PROD_TOKEN_ENDPOINT,
    UAT_TOKEN_ENDPOINT,
    Settings,
    resolve_token_endpoint,
)


def test_resolve_token_endpoint_prefers_uat_in_validation_env():
    assert resolve_token_endpoint(use_validation_env=True) == UAT_TOKEN_ENDPOINT


def test_resolve_token_endpoint_uses_production_otherwise():
    assert resolve_token_endpoint(use_validation_env=False) == PROD_TOKEN_ENDPOINT


def test_uat_and_production_endpoints_differ():
    assert UAT_TOKEN_ENDPOINT != PROD_TOKEN_ENDPOINT
    assert UAT_TOKEN_ENDPOINT.startswith("https://")
    assert PROD_TOKEN_ENDPOINT.startswith("https://")


def test_settings_keeps_application_fields():
    s = Settings()
    assert s.app_name
    assert s.log_format in ("json", "console")
    assert isinstance(s.use_validation_env, bool)


def test_settings_verify_ssl_defaults_to_true(tmp_path, monkeypatch):
    # Hermetic (no local .env): collaudo serves a self-signed cert and sets
    # VERIFY_SSL=false, but the default is True (ADR 0017).
    monkeypatch.chdir(tmp_path)
    assert Settings().verify_ssl is True


def test_settings_drops_dead_pdnd_and_jwt_fields():
    # These moved to the SDK's ClientAssertionSettings (PDND_* env) and must no
    # longer exist on the app Settings, where they were never wired to anything.
    s = Settings()
    for dead in (
        "pdnd_client_id",
        "pdnd_client_secret",
        "pdnd_token_url",
        "pdnd_audience",
        "jwt_private_key_path",
        "jwt_algorithm",
        "user_id",
        "user_location",
        "loa",
    ):
        assert not hasattr(s, dead), f"{dead} should be removed from app Settings"


def test_settings_ignores_pdnd_keys_sharing_the_dotenv(tmp_path, monkeypatch):
    # The SDK's ClientAssertionSettings reads the same .env (PDND_* keys); the app
    # Settings must ignore them, not reject the whole file as extra inputs (ADR 0015).
    (tmp_path / ".env").write_text(
        "APP_NAME=Probe\nPDND_KID=x\nPDND_AUDIENCE=y\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    settings = Settings()
    assert settings.app_name == "Probe"
