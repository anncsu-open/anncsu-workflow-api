"""Tests for the client manager: holds the per-source SDK clients + per-API locks,
and resolves the per-source server URL from settings.

The per-source ``asyncio.Lock`` serializes calls into each API so the SDK's sync-only
PDND token refresh (anncsu-sdk#35) never runs concurrently for the same auth manager.
"""

from app.adapters.anncsu.client_manager import AnncsuClientManager, server_urls_from_settings
from app.config import Settings


def test_server_urls_use_production_urls_by_default():
    settings = Settings()
    assert server_urls_from_settings(settings) == {
        "anncsu-consultazione": settings.anncsu_consultazione_url,
        "anncsu-odonimi": settings.anncsu_odonimi_url,
        "anncsu-accessi": settings.anncsu_accessi_url,
        "anncsu-coordinate": settings.anncsu_coordinate_url,
    }


def test_server_urls_use_validation_urls_when_enabled():
    settings = Settings(use_validation_env=True)
    urls = server_urls_from_settings(settings)

    assert urls["anncsu-consultazione"] == settings.anncsu_consultazione_val_url
    assert urls["anncsu-odonimi"] == settings.anncsu_odonimi_val_url
    # accessi/coordinate have no separate validation URL.
    assert urls["anncsu-accessi"] == settings.anncsu_accessi_url
    assert urls["anncsu-coordinate"] == settings.anncsu_coordinate_url


def test_lock_is_one_per_source_and_stable():
    manager = AnncsuClientManager(clients={"a": object(), "b": object()})
    assert manager.lock("a") is manager.lock("a")
    assert manager.lock("a") is not manager.lock("b")
