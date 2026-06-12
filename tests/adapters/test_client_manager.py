"""Tests for the client manager: the four authenticated sub-SDK clients + per-API locks.

One client per Arazzo source, built once from settings and reused across dispatches.
The per-source ``asyncio.Lock`` serializes calls into each API so the SDK's sync-only
PDND token refresh (anncsu-sdk#35) never runs concurrently for the same auth manager.
"""

from anncsu.accessi import AnncsuAccessi
from anncsu.coordinate import AnncsuCoordinate
from anncsu.odonimi import AnncsuOdonimi
from anncsu.pa import AnncsuConsultazione

from app.adapters.anncsu.client_manager import AnncsuClientManager
from app.config import Settings


def test_from_settings_builds_the_four_sub_sdks_with_configured_urls():
    settings = Settings()
    manager = AnncsuClientManager.from_settings(settings)

    expectations = {
        "anncsu-consultazione": (AnncsuConsultazione, settings.anncsu_consultazione_url),
        "anncsu-odonimi": (AnncsuOdonimi, settings.anncsu_odonimi_url),
        "anncsu-accessi": (AnncsuAccessi, settings.anncsu_accessi_url),
        "anncsu-coordinate": (AnncsuCoordinate, settings.anncsu_coordinate_url),
    }
    for source, (client_type, url) in expectations.items():
        client = manager.client(source)
        assert isinstance(client, client_type)
        assert client.sdk_configuration.server_url == url


def test_from_settings_uses_validation_urls_when_enabled():
    settings = Settings(use_validation_env=True)
    manager = AnncsuClientManager.from_settings(settings)

    consultazione = manager.client("anncsu-consultazione")
    odonimi = manager.client("anncsu-odonimi")
    assert consultazione.sdk_configuration.server_url == settings.anncsu_consultazione_val_url
    assert odonimi.sdk_configuration.server_url == settings.anncsu_odonimi_val_url


def test_lock_is_one_per_source_and_stable():
    manager = AnncsuClientManager(clients={"a": object(), "b": object()})
    assert manager.lock("a") is manager.lock("a")
    assert manager.lock("a") is not manager.lock("b")
