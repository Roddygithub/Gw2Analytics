"""Application configuration via environment.

Single source of truth for every connection string and bucket name.
Reads from ``DATABASE_URL`` and ``MINIO_*`` env vars; sensible
defaults match the in-repo ``docker-compose.yml`` development stack.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, loaded once and cached."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Defaults mirror docker-compose.yml dev credentials (override via .env).
    database_url: str = "postgresql+psycopg://gw2analytics:gw2analytics@localhost:5432/gw2analytics"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "gw2analytics"
    minio_secret_key: str = "gw2analytics-secret"  # noqa: S105
    minio_bucket: str = "gw2analytics"
    minio_secure: bool = False

    parser_version: str = "0.5.0"


@lru_cache
def get_settings() -> Settings:
    """Cached accessor to avoid re-parsing env on every dependency injection."""
    return Settings()
