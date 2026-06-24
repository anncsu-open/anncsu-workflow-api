"""Configuration settings for ANNCSU Workflow Service."""

from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# PDND token endpoints (the SDK uses the same UAT/production split).
PROD_TOKEN_ENDPOINT = "https://auth.interop.pagopa.it/token.oauth2"
UAT_TOKEN_ENDPOINT = "https://auth.uat.interop.pagopa.it/token.oauth2"


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # The SDK's ClientAssertionSettings reads the same .env (PDND_* keys); ignore
        # them here instead of rejecting the whole file as extra inputs (ADR 0015).
        extra="ignore",
    )

    # Application
    app_name: str = "ANNCSU Workflow Service"
    app_version: str = "1.0.0"
    debug: bool = False

    # Logging (ADR 0014): structured logs, JSON in production, console in dev.
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # ANNCSU API server URLs are NOT configured here: each SDK client discovers its
    # e-service URL from the voucher audience on first use (ADR 0017).

    # PDND credentials are NOT here: they live in the SDK's ClientAssertionSettings
    # (PDND_* env), loaded from the same .env (ADR 0015). Keeping them in one place
    # avoids the divergent, dead config this service used to carry.

    # HTTP Client
    # TLS verification for the ANNCSU calls; collaudo serves a self-signed cert,
    # so VERIFY_SSL=false disables it there (ADR 0017). Keep True in production.
    verify_ssl: bool = True

    # Explicit per-HTTP-operation timeout (seconds) for the ANNCSU/PDND e-service
    # calls, instead of httpx's implicit 5s default; the inner bound below the
    # transport's per-dispatch wait_for backstop (ADR 0017). Tune if PDND is slow.
    # Not PDND_-prefixed: that env namespace belongs to the SDK's assertion settings.
    http_timeout: float = 20.0

    # Environment
    use_validation_env: bool = False  # selects the PDND token endpoint (UAT vs prod)

    # Inbound security (ADR 0023): M2M API-KEY + source-IP/hostname ACL on the
    # workflow routes. API_KEY is required (fail-closed if unset); the allowlists are
    # enforced only when non-empty. Comma-separated in .env.
    api_key: str | None = None  # secret; never logged (ADR 0014)
    # NoDecode: take the raw .env string (comma-separated) instead of letting
    # pydantic-settings JSON-decode it; the validator below splits it.
    allowed_ips: Annotated[list[str], NoDecode] = []  # CIDR ranges (a single IP is a /32)
    allowed_fqdn: Annotated[list[str], NoDecode] = []  # allowed called hostnames (host[:port])

    @field_validator("allowed_ips", "allowed_fqdn", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept a comma-separated string in .env (e.g. ``10.0.0.0/8,127.0.0.1/32``)."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


def resolve_token_endpoint(use_validation_env: bool) -> str:
    """Return the PDND token endpoint for the selected environment (ADR 0015)."""
    return UAT_TOKEN_ENDPOINT if use_validation_env else PROD_TOKEN_ENDPOINT


settings = Settings()
