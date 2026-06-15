"""Tests for the PDND auth wiring (ADR 0015).

Everything crosses real seams except PDND itself: a fake ``PDNDAuthManager``
(records ``get_access_token`` calls) and fake SDK classes / ModI registrar let us
pin the wiring — one manager per source, a lazy per-request security provider, and
the ModI hook only on the write clients — without real credentials or network.
"""

import base64
import json

from anncsu.common.config import ClientAssertionSettings
from anncsu.pa import AnncsuConsultazione

from app.adapters.anncsu.auth import (
    SOURCES,
    build_auth_managers,
    build_client_builders,
    make_client_builder,
    make_security_provider,
)

READER = "anncsu-consultazione"
WRITERS = ("anncsu-accessi", "anncsu-odonimi", "anncsu-coordinate")


def _assertion_settings() -> ClientAssertionSettings:
    """A valid ClientAssertionSettings built without env/real keys (all six
    purpose ids present, a dummy key source) — enough to satisfy the validators."""
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


class _FakeManager:
    """Stands in for PDNDAuthManager: counts token fetches, returns a fresh one."""

    def __init__(self) -> None:
        self.calls = 0

    def get_access_token(self) -> str:
        self.calls += 1
        return f"voucher-{self.calls}"


def test_security_provider_returns_a_fresh_bearer_on_every_call():
    manager = _FakeManager()
    captured: list[dict] = []

    class _FakeSecurity:
        def __init__(self, **kwargs):
            captured.append(kwargs)
            self.kwargs = kwargs

    provider = make_security_provider(manager, _FakeSecurity, "bearer_auth")
    first = provider()
    second = provider()

    assert first.kwargs == {"bearer_auth": "voucher-1"}
    assert second.kwargs == {"bearer_auth": "voucher-2"}  # refreshed per request
    assert manager.calls == 2


def test_build_auth_managers_builds_one_per_source_with_distinct_api_types():
    built: list[dict] = []

    def factory(**kwargs):
        built.append(kwargs)
        return _FakeManager()

    settings = _assertion_settings()
    managers = build_auth_managers(
        settings,
        token_endpoint="https://token.example.test",
        manager_factory=factory,
    )

    assert set(managers) == set(SOURCES)
    for kwargs in built:
        assert kwargs["settings"] is settings
        assert kwargs["token_endpoint"] == "https://token.example.test"
        assert kwargs["session_persistence"] is False
    assert len({kwargs["api_type"] for kwargs in built}) == len(SOURCES)


def test_build_client_builders_discover_url_wire_security_and_writer_modi():
    managers = {source: _FakeManager() for source in SOURCES}
    recorded: dict[str, dict] = {}

    def sdk_factory(source: str):
        def make(**kwargs):
            recorded[source] = kwargs
            return object()

        return make

    sdk_classes = {source: sdk_factory(source) for source in SOURCES}
    modi_audiences: list[str] = []

    def fake_modi(hooks, settings, modi_audience):
        modi_audiences.append(modi_audience)

    builders = build_client_builders(
        managers,
        _assertion_settings(),
        verify_ssl=True,
        sdk_classes=sdk_classes,
        modi_registrar=fake_modi,
        audience_resolver=lambda voucher: f"https://disc.test/{voucher}",
    )

    for source in SOURCES:
        builders[source]()  # lazily build each client

    assert set(recorded) == set(SOURCES)
    # The server_url is the discovered voucher audience; an http client is passed.
    assert recorded[READER]["server_url"] == "https://disc.test/voucher-1"
    assert callable(recorded[READER]["security"])
    assert "client" in recorded[READER]
    assert "hooks" not in recorded[READER]
    for writer in WRITERS:
        assert "hooks" in recorded[writer]
    # ModI registered exactly for the writers, with the discovered url as audience.
    assert len(modi_audiences) == len(WRITERS)
    assert all(a == "https://disc.test/voucher-1" for a in modi_audiences)


def test_build_client_builders_are_lazy():
    managers = {source: _FakeManager() for source in SOURCES}
    builders = build_client_builders(
        managers,
        _assertion_settings(),
        verify_ssl=True,
        sdk_classes=dict.fromkeys(SOURCES, lambda **kwargs: object()),
        modi_registrar=lambda *args, **kwargs: None,
        audience_resolver=lambda voucher: "https://disc.test/x",
    )

    # Building the builders fetches no voucher yet.
    assert all(manager.calls == 0 for manager in managers.values())
    # Invoking a builder fetches the voucher once (for URL discovery).
    builders[READER]()
    assert managers[READER].calls == 1


def _voucher(aud: str) -> str:
    """A minimal unsigned JWT carrying an ``aud`` claim (what the SDK reads)."""
    payload = base64.urlsafe_b64encode(json.dumps({"aud": aud}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class _VoucherManager:
    def __init__(self, aud: str) -> None:
        self._aud = aud

    def get_access_token(self) -> str:
        return _voucher(self._aud)


def test_builder_sets_the_discovered_url_on_the_real_sdk_client():
    # Real AnncsuConsultazione + the real extract_voucher_audience: the discovered
    # server URL (from the voucher's aud) must land on the SDK client (ADR 0017).
    builder = make_client_builder(
        "anncsu-consultazione",
        SOURCES["anncsu-consultazione"],
        _VoucherManager("https://anncsu.test/consultazione/v1"),
        _assertion_settings(),
        verify_ssl=False,
        sdk_class=AnncsuConsultazione,
    )

    client = builder()
    assert client.sdk_configuration.server_url == "https://anncsu.test/consultazione/v1"
