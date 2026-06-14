"""Configuration settings for ANNCSU Workflow Service."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
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
        "https://modipa-val.agenziaentrate.gov.it/govway/rest/in/"
        "AgenziaEntrate-PDND/anncsu-consultazione/v1"
    )
    anncsu_odonimi_val_url: str = (
        "https://modipa-val.agenziaentrate.it/govway/rest/in/"
        "AgenziaEntrate-PDND/anncsu-aggiornamento-odonimi/v1"
    )

    # Security - PDND Authentication
    pdnd_client_id: str = ""
    pdnd_client_secret: str = ""
    pdnd_token_url: str = "https://auth.interop.pagopa.it/token.oauth2"
    pdnd_audience: str = ""

    # JWT Settings for Agid-JWT-Signature and Agid-JWT-TrackingEvidence
    jwt_private_key_path: str = "./keys/private_key.pem"
    jwt_algorithm: str = "RS256"

    # Tracking Evidence (Audit)
    user_id: str = ""  # Internal user ID
    user_location: str = ""  # User workstation
    loa: str = "3"  # Authentication level (1-4)

    # HTTP Client
    http_timeout: int = 30
    http_max_retries: int = 3

    # Environment
    use_validation_env: bool = False  # If True, use the validation URLs


settings = Settings()
