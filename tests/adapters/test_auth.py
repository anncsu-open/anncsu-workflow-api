"""Tests for the PDND auth wiring (ADR 0015).

Everything crosses real seams except PDND itself: a fake ``PDNDAuthManager``
(records ``get_access_token`` calls) and fake SDK classes / ModI registrar let us
pin the wiring — one manager per source, a lazy per-request security provider, and
the ModI hook only on the write clients — without real credentials or network.
"""

from anncsu.common.config import ClientAssertionSettings

from app.adapters.anncsu.auth import (
    SOURCES,
    build_auth_managers,
    build_clients,
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


def _urls() -> dict[str, str]:
    return {source: f"https://{source}.example.test" for source in SOURCES}


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
        server_urls=_urls(),
        manager_factory=factory,
    )

    assert set(managers) == set(SOURCES)
    for kwargs in built:
        assert kwargs["settings"] is settings
        assert kwargs["token_endpoint"] == "https://token.example.test"
        assert kwargs["session_persistence"] is False
    assert len({kwargs["api_type"] for kwargs in built}) == len(SOURCES)


def test_build_clients_wires_security_everywhere_and_modi_only_for_writers():
    urls = _urls()
    managers = {source: _FakeManager() for source in SOURCES}
    recorded: dict[str, dict] = {}

    def sdk_factory(source: str):
        def make(**kwargs):
            recorded[source] = kwargs
            return object()

        return make

    sdk_classes = {source: sdk_factory(source) for source in SOURCES}
    modi_calls: list[tuple] = []

    def fake_modi(hooks, settings, modi_audience):
        modi_calls.append((settings, modi_audience))

    clients = build_clients(
        managers,
        urls,
        assertion_settings=_assertion_settings(),
        sdk_classes=sdk_classes,
        modi_registrar=fake_modi,
    )

    assert set(clients) == set(SOURCES)
    # Every client gets a callable security provider; only writers get hooks.
    assert callable(recorded[READER]["security"])
    assert "hooks" not in recorded[READER]
    for writer in WRITERS:
        assert callable(recorded[writer]["security"])
        assert "hooks" in recorded[writer]
    # ModI registered exactly for the writers, with their server_url as audience.
    assert len(modi_calls) == len(WRITERS)
    assert {audience for _settings, audience in modi_calls} == {urls[w] for w in WRITERS}


def test_build_clients_is_lazy_and_does_not_fetch_tokens():
    managers = {source: _FakeManager() for source in SOURCES}

    def noop_factory(**kwargs):
        return object()

    build_clients(
        managers,
        _urls(),
        assertion_settings=_assertion_settings(),
        sdk_classes=dict.fromkeys(SOURCES, noop_factory),
        modi_registrar=lambda *args, **kwargs: None,
    )

    assert all(manager.calls == 0 for manager in managers.values())
