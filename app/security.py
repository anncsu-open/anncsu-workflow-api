"""Inbound security for the workflow routes (ADR 0023).

A single dependency enforces, in order: an API-KEY (`X-API-KEY` header, authn), then a
source-IP CIDR allowlist and a called-hostname allowlist (authz). The API-KEY is
required (fail-closed if unset); the allowlists are enforced only when configured.
Rejections become RFC 7807 Problems via :class:`AccessDeniedError`.
"""

from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader

from app.config import Settings, settings
from app.errors import AccessDeniedError
from app.logging import get_logger

_log = get_logger("app.security")

API_KEY_HEADER = "X-API-KEY"

# auto_error=False: a missing header resolves to None and we raise our own Problem
# (a 401 with the RFC 7807 body), not FastAPI's default 403.
_api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


def get_settings() -> Settings:
    """Return the application settings (overridable in tests)."""
    return settings


def _client_ip(request: Request) -> str:
    """Resolve the caller IP: the ingress-set ``X-Real-IP``, else the socket peer."""
    for key, value in request.headers.items():
        if key.lower() == "x-real-ip" and value:
            return value
    return request.client.host if request.client else ""


def _ip_allowed(ip: str, cidrs: list[str]) -> bool:
    try:
        addr = ip_address(ip)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if addr in ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


async def require_m2m_access(
    request: Request,
    api_key: Annotated[str | None, Security(_api_key_header)],
    cfg: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Guard the workflow routes: API-KEY (authn) then source-IP/hostname ACL (authz)."""
    # 1) API-KEY — required (fail-closed if unset). Never log the key value.
    if not cfg.api_key or api_key != cfg.api_key:
        raise AccessDeniedError(401, "Unauthorized", "Missing or invalid API key")

    # 2) Source-IP allowlist (CIDR) — enforced only when configured.
    if cfg.allowed_ips:
        ip = _client_ip(request)
        _log.debug("access.client_ip", ip=ip)
        if not _ip_allowed(ip, cfg.allowed_ips):
            _log.warning("access.ip_not_allowed", ip=ip, allowed=cfg.allowed_ips)
            raise AccessDeniedError(403, "Forbidden", "Source IP not allowed")

    # 3) Called-hostname allowlist — enforced only when configured.
    if cfg.allowed_fqdn:
        host = request.base_url.netloc
        if host not in cfg.allowed_fqdn:
            _log.warning("access.host_not_allowed", host=host, allowed=cfg.allowed_fqdn)
            raise AccessDeniedError(403, "Forbidden", "Host not allowed")
