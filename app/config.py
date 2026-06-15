"""Configuration settings for ANNCSU Workflow Service."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

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

    # ANNCSU API URLs
    anncsu_consultazione_url: str = (
        "https://modipa.agenziaentrate.gov.it/govway/rest/in/"
        "AgenziaEntrate-PDND/anncsu-consultazione/v1"
    )
    anncsu_odonimi_url: str = (
        "https://modipa.agenziaentrate.it/govway/rest/in/"
        "AgenziaEntrate-PDND/anncsu-aggiornamento-odonimi/v1"
    )
    anncsu_accessi_url: str = (
        "https://modipa.agenziaentrate.it/govway/rest/in/AgenziaEntrate/anncsuaccessi/v1"
    )
    anncsu_coordinate_url: str = (
        "https://modipa.agenziaentrate.it/govway/rest/in/AgenziaEntrate/anncsuaccessi/v1"
    )

    # Validation environment URLs
    anncsu_consultazione_val_url: str = (
        "https://modipa-val.agenziaentrate.it/govway/rest/in/"
        "AgenziaEntrate-PDND/anncsu-consultazione/v1"
    )
    anncsu_odonimi_val_url: str = (
        "https://modipa-val.agenziaentrate.it/govway/rest/in/"
        "AgenziaEntrate-PDND/anncsu-aggiornamento-odonimi/v1"
    )

    # PDND credentials are NOT here: they live in the SDK's ClientAssertionSettings
    # (PDND_* env), loaded from the same .env (ADR 0015). Keeping them in one place
    # avoids the divergent, dead config this service used to carry.

    # HTTP Client
    http_timeout: int = 30
    http_max_retries: int = 3

    # Environment
    use_validation_env: bool = False  # If True, use the validation URLs


def resolve_token_endpoint(use_validation_env: bool) -> str:
    """Return the PDND token endpoint for the selected environment (ADR 0015)."""
    return UAT_TOKEN_ENDPOINT if use_validation_env else PROD_TOKEN_ENDPOINT


settings = Settings()
