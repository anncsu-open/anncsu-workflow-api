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

import httpx
from anncsu.accessi import AnncsuAccessi
from anncsu.accessi.models import Security as AccessiSecurity
from anncsu.common.auth import PDNDAuthManager, extract_voucher_audience
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
    manager_factory: Callable[..., Any] = PDNDAuthManager,
) -> dict[str, Any]:
    """Build one auth manager per source (eager build, but no token fetched here).

    The server URL is no longer needed here: it is discovered from the voucher when
    the SDK client is lazily built (ADR 0017).
    """
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


class AudienceDiscoveryError(RuntimeError):
    """The voucher carried no audience, so the e-service URL can't be discovered."""


def make_client_builder(  # noqa: PLR0913 - a wiring factory with injectable seams
    source: str,
    spec: SourceAuth,
    auth_manager: Any,
    assertion_settings: ClientAssertionSettings,
    *,
    verify_ssl: bool,
    http_timeout: float,
    sdk_class: Any,
    audience_resolver: Callable[[str], str | None] = extract_voucher_audience,
    modi_registrar: Callable[..., None] = register_modi_hook_if_configured,
) -> Callable[[], Any]:
    """Return a callable that lazily builds the authenticated SDK client (ADR 0017).

    The build fetches the voucher, derives the e-service ``server_url`` from its
    audience, and constructs the client with a ``verify_ssl``-configured HTTP client
    and the per-request security provider (writers also get the ModI hook). It is a
    synchronous, blocking call (voucher fetch) and must run off the event loop —
    the transport invokes it inside ``asyncio.to_thread`` under the per-source lock.

    ``http_timeout`` is set explicitly on the HTTP client (instead of httpx's
    implicit 5s default) so PDND e-service calls are bounded predictably; it is the
    inner bound, below the transport's per-dispatch ``wait_for`` backstop.
    """

    def build() -> Any:
        url = audience_resolver(auth_manager.get_access_token())
        if not url:
            _log.error("client.no_audience", source=source)
            raise AudienceDiscoveryError(f"no audience in the voucher for {source!r}")
        provider = make_security_provider(auth_manager, spec.security_cls, spec.bearer_kwarg)
        kwargs: dict[str, Any] = {
            "server_url": url,
            "security": provider,
            "client": httpx.Client(verify=verify_ssl, timeout=http_timeout),
        }
        if spec.is_writer:
            hooks = SDKHooks()
            modi_registrar(hooks, assertion_settings, url)
            kwargs["hooks"] = hooks
        client = sdk_class(**kwargs)
        _log.info("client.built", source=source, server_url=url)
        return client

    return build


def build_client_builders(  # noqa: PLR0913 - a wiring factory with injectable seams
    auth_managers: Mapping[str, Any],
    assertion_settings: ClientAssertionSettings,
    *,
    verify_ssl: bool,
    http_timeout: float,
    sdk_classes: Mapping[str, Any] = SDK_CLASSES,
    modi_registrar: Callable[..., None] = register_modi_hook_if_configured,
    audience_resolver: Callable[[str], str | None] = extract_voucher_audience,
) -> dict[str, Callable[[], Any]]:
    """A lazy SDK-client builder per source (URL discovered from the voucher)."""
    return {
        source: make_client_builder(
            source,
            spec,
            auth_managers[source],
            assertion_settings,
            verify_ssl=verify_ssl,
            http_timeout=http_timeout,
            sdk_class=sdk_classes[source],
            audience_resolver=audience_resolver,
            modi_registrar=modi_registrar,
        )
        for source, spec in SOURCES.items()
    }
