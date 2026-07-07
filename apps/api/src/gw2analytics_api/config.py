"""Application configuration via environment.

Single source of truth for every connection string and bucket name.
Reads from ``.env`` and process env vars; required keys (``DATABASE_URL``
and ``S3_*``) have no defaults so a misconfigured deployment fails loudly
at startup with a pydantic ``ValidationError`` listing the missing keys
instead of silently pointing at dev sentinels.

Dev/CI credentials live in ``.env.example`` (copy to ``.env``); the test
suite auto-loads them via ``pytest-env`` so contributors never have to
hand-roll a ``.env`` file just to run ``uv run pytest``.

Note: field names like ``minio_endpoint`` only map to the explicitly
aliased env vars (``S3_ENDPOINT`` here); the Python name itself is not
an env key. Setting ``MINIO_ENDPOINT=...`` in ``.env`` will be silently
ignored.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, loaded once and cached."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ``database_url`` and the ``minio_*`` fields are *required*: no
    # defaults so a misconfigured deployment fails fast at startup.
    # The ``minio_*`` snake_case Python names map to ``S3_*`` env-var
    # aliases because the underlying MinIO client speaks the S3 protocol
    # and the project-wide convention (per ``.env.example``) is the
    # S3 nomenclature regardless of the actual provider.
    database_url: str = Field(validation_alias="DATABASE_URL")
    minio_endpoint: str = Field(validation_alias="S3_ENDPOINT")
    minio_access_key: str = Field(validation_alias="S3_ACCESS_KEY")
    minio_secret_key: str = Field(validation_alias="S3_SECRET_KEY")
    minio_bucket: str = Field(validation_alias="S3_BUCKET")
    # ``minio_secure`` and ``parser_version`` keep their previous
    # defaults: unrelated to credentials and unlikely to need per-env
    # overrides in the current scope.
    minio_secure: bool = False
    parser_version: str = "0.5.0"
    # ``cors_allowed_origins`` defaults to wide-open for local dev
    # (the Next.js frontend at :3000 + curl from any origin). Set
    # ``CORS_ALLOWED_ORIGINS=https://app.example.com,https://admin.example.com``
    # in deployment env to tighten. Comma-separated env input is
    # parsed by pydantic-settings into a list.
    cors_allowed_origins: list[str] = Field(
        default=["*"],
        validation_alias="CORS_ALLOWED_ORIGINS",
    )


@lru_cache
def get_settings() -> Settings:
    """Cached accessor to avoid re-parsing env on every dependency injection."""
    return Settings()
