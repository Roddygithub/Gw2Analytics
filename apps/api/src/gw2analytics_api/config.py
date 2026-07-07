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
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, loaded once and cached."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # ``populate_by_name=True`` lets callers pass Settings(
        #     cors_allowed_origins=[...]) by the Python field name while
        # keeping ``validation_alias="CORS_ALLOWED_ORIGINS"`` for env
        # input. Without this, the Python name is rejected (the field
        # only accepts the alias), and Settings(kw=...) silently
        # falls back to the field default. The env-var path keeps
        # working because ``validation_alias`` is consulted first.
        populate_by_name=True,
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
    # ``cors_allowed_origins`` defaults to wide-open (``["*"]``) for
    # local dev (the Next.js frontend at :3000 + curl from any origin).
    # ``NoDecode`` short-circuits pydantic-settings' default JSON
    # parsing of list-valued env vars (a bare ``*`` is not valid JSON
    # and would otherwise raise ``SettingsError`` on startup); the
    # ``_split_cors_origins`` validator below splits the raw env string
    # on commas (``CORS_ALLOWED_ORIGINS=https://a,https://b`` -> 2
    # entries) and recognises ``*`` as the wide-open shortcut.
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=["*"],
        validation_alias="CORS_ALLOWED_ORIGINS",
    )

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> list[str]:
        # ``Annotated[list[str], NoDecode]`` short-circuits pydantic-settings'
        # ``env_ignore_empty=True`` default for this field -- once the
        # env source is bypassed (NoDecode), the raw env string flows
        # straight to this validator regardless of emptiness. So the
        # empty-string branch below is **reachable** (and required):
        # ``CORS_ALLOWED_ORIGINS=`` arrives here as ``""`` and must be
        # treated as "no constraint" rather than ``[""]``.
        if isinstance(v, str):
            v = v.strip()
            if v in ("", "*"):
                return ["*"]
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            return v
        msg = f"cors_allowed_origins env value must be a string or list, got {type(v).__name__}"
        raise ValueError(msg)


@lru_cache
def get_settings() -> Settings:
    """Cached accessor to avoid re-parsing env on every dependency injection."""
    return Settings()
