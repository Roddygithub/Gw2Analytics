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

import base64
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
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
    minio_secure: bool = False
    # ``cors_allowed_origins`` defaults to the local Next.js frontend
    # (``http://localhost:3000``) so a production deployment that
    # forgets to set ``CORS_ALLOWED_ORIGINS`` does not silently
    # wide-open the API to every origin. Operators can still set
    # ``CORS_ALLOWED_ORIGINS=*`` for unrestricted local curl/dev, or
    # a comma-separated list for multiple origins.
    # ``NoDecode`` short-circuits pydantic-settings' default JSON
    # parsing of list-valued env vars (a bare ``*`` is not valid JSON
    # and would otherwise raise ``SettingsError`` on startup); the
    # ``_split_cors_origins`` validator below splits the raw env string
    # on commas (``CORS_ALLOWED_ORIGINS=https://a,https://b`` -> 2
    # entries) and recognises ``*`` as the wide-open shortcut.
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:3000"],
        validation_alias="CORS_ALLOWED_ORIGINS",
    )
    # v0.10.0 plan 031: webhook secret at rest envelope encryption.
    # ``SecretStr`` masks the value in tracebacks / repr / debug
    # (so the KEK never leaks via the standard Python logging
    # channels or exception formatting). REQUIRED at startup;
    # the 44-char validator below fails-fast so a misconfigured
    # deployment refuses to boot BEFORE the first webhook is
    # processed (no silent plaintext fallback).
    secrets_kek: SecretStr = Field(validation_alias="SECRETS_KEK")
    # v0.10.9 plan 016: centralized env-var reads as Settings
    # fields. All env-driven config (boolean feature flags + the
    # comma-separated KEK fallback list) MUST live as Settings
    # fields so tests can mock them via ``monkeypatch.setenv`` +
    # a single ``get_settings.cache_clear()``. The grep check at
    # the end of plan 016's done criteria
    # (``grep -rE 'os\.environ\.get' apps/api/src/``) is the
    # audit guard against the next contributor adding a raw
    # read.
    arq_redis_host: str = Field(default="localhost", validation_alias="ARQ_REDIS_HOST")
    arq_redis_port: int = Field(default=6379, validation_alias="ARQ_REDIS_PORT")
    # ``ALLOW_INREQUEST_PARSE_FALLBACK`` is "1" in tests (per
    # conftest.py + pytest_env) so the upload route exercises
    # the in-request fallback. Production defaults to False
    # (pool-only path; pool unavailability surfaces a loud 503).
    allow_inrequest_parse_fallback: bool = Field(
        default=False,
        validation_alias="ALLOW_INREQUEST_PARSE_FALLBACK",
    )
    skip_schema_guard: bool = Field(default=False, validation_alias="SKIP_SCHEMA_GUARD")
    # SSRF-block-bypass for trusted dev environments. The env
    # name keeps the ``GW2ANALYTICS_`` prefix per the
    # operational runbook; the Python name strips it for
    # readability.
    gw2analytics_allow_private_webhook_urls: bool = Field(
        default=False,
        validation_alias="GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS",
    )
    # Comma-separated Fernet key list consulted by
    # ``crypto._resolve_kek`` after the primary KEK fails to
    # decrypt (keystore rotation). Defaults to empty list (no
    # fallback) so v0.10.8 deployments behave unchanged. The
    # custom ``_split_secrets_kek_fallback`` validator below
    # mirrors the ``_split_cors_origins`` pattern
    # (``Annotated[list[str], NoDecode]`` + comma split); JSON-
    # style ``["a","b"]`` would otherwise crash on the bare
    # ``a,b`` form operators paste into ``.env``. Owned by
    # plan 016; plan 015 (KEK rotation) will READ this field
    # via ``get_settings().secrets_kek_fallback``.
    secrets_kek_fallback: Annotated[list[str], NoDecode] = Field(
        default=[],
        validation_alias="SECRETS_KEK_FALLBACK",
    )
    # v0.10.12 plan 014: stuck-upload sweeper config.
    # Interval between sweep iterations (seconds) and the
    # staleness threshold for pending uploads (seconds).
    stuck_sweeper_interval_s: int = Field(
        default=300,
        validation_alias="STUCK_SWEEPER_INTERVAL_S",
    )
    stuck_sweeper_threshold_s: int = Field(
        default=300,
        validation_alias="STUCK_SWEEPER_THRESHOLD_S",
    )
    # v0.10.26-pre plan 170: failed-upload retention window (days)
    # for the cleanup DELETE sweep. Scoped to ``error_message LIKE
    # 'Duplicate fight:%'`` rows (the plan/160 idempotency collision
    # path) that ALSO have zero dependent :class:`OrmFight` rows
    # (the FK cascade would otherwise orphan fight data -- the
    # cascade is 4 levels deep: Upload -> OrmFight -> {OrmFightAgent,
    # OrmFightSkill, OrmFightPlayerSummary}). Default 90 days;
    # ``ge=1`` so an operator typo of 0 cannot silently become
    # "delete immediately".
    stuck_sweeper_failed_retention_days: int = Field(
        default=90,
        validation_alias="STUCK_SWEEPER_FAILED_RETENTION_DAYS",
        ge=1,
    )
    # v0.10.25: hard cap on the compressed ``.zevtc`` upload body.
    # Real WvW logs are ~5-40 MB compressed; the cap gives headroom
    # for the largest known files while preventing OOM from malicious
    # or broken clients. The parser's decompressed cap (500 MB) is
    # separate and larger.
    max_upload_size_bytes: int = Field(
        default=100 * 1024 * 1024,
        validation_alias="MAX_UPLOAD_SIZE_BYTES",
        # Floor at 1 MiB so an operator typo (MAX_UPLOAD_SIZE_BYTES=0 or
        # negative) cannot silently disable the cap -- Pydantic raises
        # ValidationError on app startup. Upper bound is intentionally
        # unbounded (the parser-side MAX_EVTC_BYTES is the second gate).
        ge=1024 * 1024,
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

    @field_validator("secrets_kek", mode="before")
    @classmethod
    def _validate_secrets_kek(cls, v: object) -> str:
        """Enforce the Fernet-key format BEFORE pydantic's SecretStr wrap.

        pydantic runs ``mode="before"`` validators BEFORE the
        ``SecretStr`` wrap, so ``v`` is the raw env input (a
        ``str``). Validating the length here surfaces a clear
        error message that names the field-length expectation +
        the canonical Python one-liner for generating a fresh
        KEK. The wrap to ``SecretStr`` happens AFTER this
        validator returns, so the masked-but-validated form
        lands in the model.
        """
        s = v
        if s is None or not isinstance(s, str):
            raise ValueError(f"SECRETS_KEK must be a string; got {type(s).__name__}")
        if len(s) != 44:
            raise ValueError(
                f"SECRETS_KEK must be exactly 44 URL-safe base64 chars "
                f"(Fernet 32-byte key); got {len(s)} chars. "
                f'Generate via `python -c "from cryptography.fernet '
                f'import Fernet; print(Fernet.generate_key().decode())"`.'
            )
        # Length is necessary but not sufficient: ``"a" * 44`` is
        # 44 chars but URL-safe-b64-decodes to 33 bytes (44*6/8),
        # not 32. Fernet's ``Fernet(key)`` constructor rejects
        # any non-32-byte key with ``ValueError``. The validator
        # round-trips the base64 decode so a misconfigured
        # deployment fails loud at app startup instead of crashing
        # on the first ``encrypt_webhook_secret`` call deep in a
        # BG task (which would surface as a 500 to the integrator
        # with no actionable context).
        try:
            decoded = base64.urlsafe_b64decode(s)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"SECRETS_KEK must be valid URL-safe base64; got decode error: {exc}"
            ) from exc
        if len(decoded) != 32:
            raise ValueError(
                f"SECRETS_KEK URL-safe-b64-decodes to {len(decoded)} bytes; "
                f"Fernet requires exactly 32. Generate via "
                f'`python -c "from cryptography.fernet import Fernet; '
                f'print(Fernet.generate_key().decode())"`.'
            )
        return s

    # v0.10.9 plan 016: comma-split validator for the
    # ``SECRETS_KEK_FALLBACK`` env var. The
    # ``Annotated[list[str], NoDecode]`` shape mirrors
    # ``_split_cors_origins`` above so pydantic-settings does
    # NOT attempt to JSON-decode the raw string; the bare-csv
    # form (``kek_a,kek_b``) is what operators paste into
    # ``.env``, NOT the JSON-list form (``["kek_a","kek_b"]``).
    @field_validator("secrets_kek_fallback", mode="before")
    @classmethod
    def _split_secrets_kek_fallback(cls, v: object) -> list[str]:
        # ``Annotated[list[str], NoDecode]`` short-circuits
        # pydantic-settings' default JSON-list parser for THIS
        # field (matching the ``cors_allowed_origins``
        # precedent). Empty-string handling differs slightly:
        # ``SECRETS_KEK_FALLBACK=`` is treated as "no fallback"
        # (explicit empty) which is SAFER than the wildcard
        # fallback used for ``CORS_ALLOWED_ORIGINS`` -- an
        # empty fallback list is the documented pre-v0.10.9
        # default, so a misconfigured "empty" deployment should
        # be the safe default (no fallback rotation) rather
        # than the inverted-state default.
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return []
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            return v
        msg = f"secrets_kek_fallback env value must be a string or list, got {type(v).__name__}"
        raise ValueError(msg)


@lru_cache
def get_settings() -> Settings:
    """Cached accessor to avoid re-parsing env on every dependency injection."""
    return Settings()
