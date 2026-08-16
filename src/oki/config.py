from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from Oki-prefixed environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="OKI_",
        extra="ignore",
    )

    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://oki@localhost:5432/oki"
    valkey_url: str = "valkey://127.0.0.1:6379/0"
    s3_endpoint_url: str = "http://127.0.0.1:8333"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "oki-local"
    sentry_dsn: str | None = None
    keycloak_issuer: str = "http://127.0.0.1:8080/realms/oki"
    keycloak_audience: str = "oki-api"
    keycloak_authorized_party: str = "oki-web"
    keycloak_jwks_uri: str | None = None
    keycloak_jwks_cache_seconds: float = 300
    keycloak_jwks_timeout_seconds: float = 5
    ffmpeg_path: str = "ffmpeg"

    # --- AI Provider Settings ---
    # OpenAI-compatible API (works for standard OpenAI, Azure OpenAI, local endpoints)
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_api_version: str = "2024-06-01"  # Azure API version

    # Azure OpenAI specific
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_whisper_deployment: str = "whisper-1"
    azure_gpt_deployment: str = "gpt-4"

    # ElevenLabs
    elevenlabs_api_key: str | None = None
    elevenlabs_base_url: str = "https://api.elevenlabs.io"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings snapshot."""

    return Settings()
