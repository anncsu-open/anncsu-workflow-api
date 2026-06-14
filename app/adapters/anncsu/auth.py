"""PDND authentication wiring for the SDK clients (ADR 0015).

Builds one :class:`PDNDAuthManager` per Arazzo source (each API needs its own
``purpose_id``) and an authenticated SDK client per source. Authentication is a
**security-provider callable** that the SDK invokes before every request, so the
access token is fetched lazily and refreshed automatically by the manager. The
three write APIs additionally get the ModI pre-request hook
(``Agid-JWT-Signature``/audit) when ``PDND_MODI_*`` is configured; the PA reader
does not. No tokens are fetched at build time.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from anncsu.accessi import AnncsuAccessi
from anncsu.accessi.models import Security as AccessiSecurity
from anncsu.common.auth import PDNDAuthManager
from anncsu.common.config import APIType, ClientAssertionSettings
from anncsu.common.hooks import SDKHooks, register_modi_hook
from anncsu.common.modi import AuditContext, ModIConfig
from anncsu.common.security import Security as PASecurity
from anncsu.coordinate import AnncsuCoordinate
from anncsu.coordinate.models import Security as CoordinateSecurity
from anncsu.odonimi import AnncsuOdonimi
from anncsu.odonimi.models import Security as OdonimiSecurity
from anncsu.pa import AnncsuConsultazione

from app.logging import get_logger

_log = get_logger("app.auth")


@dataclass(frozen=True)
class SourceAuth:
    """How one Arazzo source authenticates."""

    api_type: APIType
    security_cls: type
    bearer_kwarg: str  # PA uses ``bearer``; the write SDKs use ``bearer_auth``
    is_writer: bool  # writers also need the ModI signature/audit hook


# Single source of truth for the per-source auth shape (ADR 0015).
SOURCES: dict[str, SourceAuth] = {
    "anncsu-consultazione": SourceAuth(APIType.PA, PASecurity, "bearer", is_writer=False),
    "anncsu-accessi": SourceAuth(APIType.ACCESSI, AccessiSecurity, "bearer_auth", is_writer=True),
    "anncsu-odonimi": SourceAuth(APIType.ODONIMI, OdonimiSecurity, "bearer_auth", is_writer=True),
    "anncsu-coordinate": SourceAuth(
        APIType.COORDINATE, CoordinateSecurity, "bearer_auth", is_writer=True
    ),
}

# Default SDK client class per source (injectable for tests).
SDK_CLASSES: dict[str, type] = {
    "anncsu-consultazione": AnncsuConsultazione,
    "anncsu-accessi": AnncsuAccessi,
    "anncsu-odonimi": AnncsuOdonimi,
    "anncsu-coordinate": AnncsuCoordinate,
}


def make_security_provider(
    manager: Any, security_cls: type, bearer_kwarg: str
) -> Callable[[], Any]:
    """Return a callable the SDK invokes per request for a fresh-bearer Security."""

    def provider() -> Any:
        return security_cls(**{bearer_kwarg: manager.get_access_token()})

    return provider


def build_auth_managers(
    assertion_settings: ClientAssertionSettings,
    *,
    token_endpoint: str,
    server_urls: Mapping[str, str],
    manager_factory: Callable[..., Any] = PDNDAuthManager,
) -> dict[str, Any]:
    """Build one auth manager per source (eager build, but no token fetched here)."""
    managers: dict[str, Any] = {}
    for source, spec in SOURCES.items():
        managers[source] = manager_factory(
            api_type=spec.api_type,
            settings=assertion_settings,
            token_endpoint=token_endpoint,
            session_persistence=False,
        )
    return managers


def register_modi_hook_if_configured(
    hooks: SDKHooks, settings: ClientAssertionSettings, modi_audience: str
) -> None:
    """Register the ModI pre-request hook on ``hooks`` (best-effort).

    Mirrors the SDK CLI: a dedicated ``PDND_MODI_*`` signing key is preferred
    (GovWay requires it to differ from the voucher key in production); absent one,
    fall back to the voucher key with a warning. Failures are logged and swallowed
    so the service keeps running (the API call may then fail with a clearer error).
    """
    try:
        if settings.has_e_service_key:
            modi_kid = settings.modi_kid
            modi_private_key: bytes | None = None
            if settings.modi_private_key:
                modi_private_key = settings.modi_private_key.encode("utf-8")
            elif settings.modi_key_path:
                with open(settings.modi_key_path, "rb") as key_file:
                    modi_private_key = key_file.read()
        else:
            if not getattr(settings, "modi_kid", None):
                _log.warning(
                    "auth.modi_key_fallback",
                    detail="PDND_MODI_KID not set; using the voucher key for ModI "
                    "signing (GovWay requires a dedicated key in production)",
                )
            modi_kid = settings.kid
            modi_private_key = None
            if settings.private_key:
                modi_private_key = settings.private_key.encode("utf-8")
            elif settings.key_path:
                with open(settings.key_path, "rb") as key_file:
                    modi_private_key = key_file.read()

        if modi_private_key and modi_kid:
            modi_config = ModIConfig(
                private_key=modi_private_key,
                kid=modi_kid,
                issuer=settings.issuer,
                audience=modi_audience,
            )
            audit_context: AuditContext | None = None
            if settings.has_modi_audit_context:
                audit_context = settings.get_modi_audit_context()
            register_modi_hook(hooks, config=modi_config, audit_context=audit_context)
    except Exception as error:  # noqa: BLE001 - best-effort, mirror the CLI
        _log.warning("auth.modi_hook_failed", detail=str(error))


def build_clients(
    auth_managers: Mapping[str, Any],
    server_urls: Mapping[str, str],
    assertion_settings: ClientAssertionSettings,
    *,
    sdk_classes: Mapping[str, Any] = SDK_CLASSES,
    modi_registrar: Callable[..., None] = register_modi_hook_if_configured,
) -> dict[str, Any]:
    """Build an authenticated SDK client per source (writers also get the ModI hook)."""
    clients: dict[str, Any] = {}
    for source, spec in SOURCES.items():
        url = server_urls[source]
        provider = make_security_provider(
            auth_managers[source], spec.security_cls, spec.bearer_kwarg
        )
        sdk_cls = sdk_classes[source]
        if spec.is_writer:
            hooks = SDKHooks()
            modi_registrar(hooks, assertion_settings, url)
            clients[source] = sdk_cls(server_url=url, security=provider, hooks=hooks)
        else:
            clients[source] = sdk_cls(server_url=url, security=provider)
    return clients
