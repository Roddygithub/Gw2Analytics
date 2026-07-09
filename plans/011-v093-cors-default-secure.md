# Plan 011 — v0.9.3: CORS default `["*"]` locked down

**Author:** senior-advisor audit (improve skill, standard effort) — selected by maintainer (top-3 by leverage).
**Drift base:** `44ea862` (origin/main HEAD at plan authoring).
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** an executor model with NO prior context.

---

## Why this matters

`apps/api/src/gw2analytics_api/config.py:54-86` defines `cors_allowed_origins` with a default of `["*"]`, AND `_split_cors_origins` maps BOTH the empty string AND `"*"` to `["*"]`. Combined with `apps/api/src/gw2analytics_api/main.py:75-87` `allow_methods=["*"]` + `allow_headers=["*"]`, an operator who:

1. Runs `cp .env.example .env` (per the README + CONTRIBUTING quickstart).
2. Builds + deploys without setting `CORS_ALLOWED_ORIGINS` to a real allowlist.
3. Has `["*"]` as the operating value forever.

…ships a backend where any browser-side JS (Phishing page, compromised extension, OAuth callback origin snooping) can issue cross-origin requests to **every** API endpoint with no Origin enforcement, no method restriction, no header restriction. Authorization is Bearer-only on `/api/v1/account`, but the wide-open CORS still allows probing other endpoints (uploads, fights, players) for information leakage.

The fix is a Pydantic v2 `@model_validator(mode="after")` that rejects `cors_allowed_origins == ["*"]` when a deployment mode other than `dev` is configured. Fail-fast at startup; pydantic `ValidationError` is the canonical error shape.

---

## Files IN scope

- `apps/api/src/gw2analytics_api/config.py` — Settings class (`env` field + `@model_validator(mode="after")`).
- `apps/api/.env.example` — add `ENV=production` as the prod baseline + a comment about CORS_ALLOWED_ORIGINS in prod.
- `pyproject.toml` (root, `[tool.pytest_env]`) — add `ENV=dev` so existing tests stay green.
- `apps/api/tests/test_config.py` — 4 new regression tests.

## Files NOT in scope

- `apps/api/src/gw2analytics_api/main.py` (the FastAPI CORS middleware itself stays; only the Settings-driven input is tightened).
- `web/` (no frontend changes).
- `libs/*` (no worker-side env reads).
- Any Alembic migration (no schema change).

---

## Current code (read from `44ea862`)

### `config.py:38-86` — the unsafe default + validator

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(validation_alias="DATABASE_URL")
    minio_endpoint: str = Field(validation_alias="S3_ENDPOINT")
    minio_access_key: str = Field(validation_alias="S3_ACCESS_KEY")
    minio_secret_key: str = Field(validation_alias="S3_SECRET_KEY")
    minio_bucket: str = Field(validation_alias="S3_BUCKET")
    minio_secure: bool = False
    parser_version: str = "0.5.0"
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=["*"],
        validation_alias="CORS_ALLOWED_ORIGINS",
    )

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if v in ("", "*"):
                return ["*"]
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            return v
        raise ValueError(...)
```

### `main.py:75-87` — the accepting middleware

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### `.env.example` (root file)

```
DATABASE_URL=postgresql+psycopg://gw2analytics:gw2analytics@localhost:5432/gw2analytics
S3_ENDPOINT=localhost:9000
S3_ACCESS_KEY=gw2analytics
S3_SECRET_KEY=...
S3_BUCKET=gw2analytics
```

(`CORS_ALLOWED_ORIGINS` is NOT in `.env.example` — the prod operator must explicitly set it. But the default is still `["*"]`, so a missing env var silently lands on the wildcard.)

---

## Step-by-step

### Step 1 — Add `env` field to Settings

In `apps/api/src/gw2analytics_api/config.py`:

```python
from typing import Annotated, Literal

class Settings(BaseSettings):
    # ... existing fields ...

    # v0.9.3 plan 011: deployment mode flag. Drives the CORS
    # fail-fast below; future plans can use it to gate other
    # unsafe-by-default settings (S3 secure, secret-at-rest
    # encryption, etc.). Operators MUST set ``ENV=production``
    # before any non-loopback deployment. pytest-env injects
    # ``ENV=dev`` so tests stay green (see root pyproject.toml).
    env: Literal["dev", "staging", "production"] = Field(
        default="dev",
        validation_alias="ENV",
    )
```

### Step 2 — Add `@model_validator(mode="after")` for CORS gate

CRITICAL (per thinker):

> The `@field_validator(mode="before")` does **not** have access to the *parsed* `env` field; the cross-field check requires `@model_validator(mode="after")` on the `Settings` class itself.

```python
from pydantic import model_validator

class Settings(BaseSettings):
    # ... existing fields ...

    @model_validator(mode="after")
    def _enforce_safe_cors_in_non_dev(self) -> "Settings":
        if self.env == "dev":
            return self
        if self.cors_allowed_origins == ["*"]:
            raise ValueError(
                "cors_allowed_origins=[\\\"*\\\"] is unsafe in "
                f"ENV={self.env!r}. Set CORS_ALLOWED_ORIGINS to a "
                "comma-separated allowlist of explicit origins "
                '(e.g. CORS_ALLOWED_ORIGINS=https://app.example.com).'
            )
        return self
```

### Step 3 — Update `apps/api/.env.example` (root)

Add the line at the top of the file (operators MUST read it before copying):

```
# v0.9.3 plan 011: deployment mode gate.
# - dev (default): permissive CORS + SQLite-style defaults — fine for local dev only.
# - staging: permissive CORS allowed with a WARNING at startup; no prod workloads.
# - production: forbids CORS_ALLOWED_ORIGINS="*" — must enumerate explicit origins
#   (e.g. https://app.example.com). Failure to set raises pydantic ValidationError on startup.
ENV=production

DATABASE_URL=postgresql+psycopg://gw2analytics:gw2analytics@localhost:5432/gw2analytics
S3_ENDPOINT=localhost:9000
...
CORS_ALLOWED_ORIGINS=https://app.example.com
```

### Step 4 — Update `[tool.pytest_env]` in root `pyproject.toml`

```toml
[tool.pytest_env]
# v0.9.3 plan 011: existing dev credentials + post-test hermetic defaults.
# Add ENV=dev so test_config.py and the apps/api/app boot pathway
# are exempt from the production-mode CORS fail-fast.
ENV = "dev"
DATABASE_URL = "postgresql+psycopg://gw2analytics:gw2analytics@localhost:5432/gw2analytics"
S3_ENDPOINT = "localhost:9000"
S3_ACCESS_KEY = "gw2analytics"
S3_SECRET_KEY = "gw2analytics-secret"
S3_BUCKET = "gw2analytics"
```

### Step 5 — Add regression tests in `apps/api/tests/test_config.py`

```python
"""v0.9.3 plan 011: CORS gate in production mode."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from gw2analytics_api.config import Settings


def _base_kwargs(**overrides):
    base = {
        "database_url": "postgresql+psycopg://u@h/d",
        "minio_endpoint": "localhost",
        "minio_access_key": "k",
        "minio_secret_key": "s",
        "minio_bucket": "b",
    }
    base.update(overrides)
    return base


def test_settings_rejects_wildcard_cors_in_production():
    """Production + wildcards = ValidationError (covers the canonical exploit)."""
    with pytest.raises(ValidationError) as exc:
        Settings(**_base_kwargs(env="production", cors_allowed_origins=["*"]))
    assert "CORS_ALLOWED_ORIGINS" in str(exc.value) or "cors_allowed_origins" in str(exc.value)


def test_settings_rejects_wildcard_cors_in_staging_loud():
    """Staging also rejects wildcards — same fail-fast contract (3-tier model
    has dev: permissive, staging/production: explicit only)."""
    with pytest.raises(ValidationError):
        Settings(**_base_kwargs(env="staging", cors_allowed_origins=["*"]))


def test_settings_accepts_wildcard_cors_in_dev():
    """Dev retains the existing permissive default."""
    s = Settings(**_base_kwargs(env="dev", cors_allowed_origins=["*"]))
    assert s.cors_allowed_origins == ["*"]
    assert s.env == "dev"


def test_settings_accepts_explicit_origins_in_production():
    """Production with explicit origins = happy path."""
    s = Settings(
        **_base_kwargs(
            env="production",
            cors_allowed_origins=["https://app.example.com"],
        )
    )
    assert s.cors_allowed_origins == ["https://app.example.com"]
    assert s.env == "production"


def test_settings_default_env_is_dev():
    """Omitting `env` falls back to dev (backward compat with pre-plan-011 callers)."""
    s = Settings(**_base_kwargs())
    assert s.env == "dev"
```

---

## Verification commands

```bash
# Lint + type-check.
uv run ruff check apps/api
uv run ruff format --check apps/api
uv run mypy --no-incremental libs apps

# New tests pass.
uv run pytest apps/api/tests/test_config.py -v
# Expected: 5 new tests pass (plus the existing 4 env tests unchanged).

# existing settings test stays green (default env=dev).
uv run pytest apps/api/tests/test_uploads_e2e.py -v
# Expected: 92 pass + 0 fail + 3 skip (env=dev via pytest_env).

# Manual smoke: try booting with prod + wildcard and confirm the
# fail-fast surfaces a clear pydantic ValidationError.
ENV=production CORS_ALLOWED_ORIGINS="*" uv run fastapi dev \
    apps/api/src/gw2analytics_api/main.py
# Expected: ValidationError mentioning CORS_ALLOWED_ORIGINS (fail-fast, no hang).
```

A worktree `git diff` against `44ea862` must show ONLY:
- `apps/api/src/gw2analytics_api/config.py` (1 new field + 1 new validator method)
- `apps/api/.env.example` (1 block added)
- `pyproject.toml` (1 line under `[tool.pytest_env]`)
- `apps/api/tests/test_config.py` (5 new tests)
- `CONTRIBUTING.md` (1 short subsection "## Deployment mode gate")

---

## Maintenance note

- The `env` field is informational as far as THIS plan; future hardening plans can use it to gate other unsafe-by-default settings (e.g. raising S3 to HTTPS in prod, requiring SECRET_KEY at startup, secret-at-rest encryption).
- The 3-tier model (`dev` / `staging` / `production`) gives operators 2 grace paths: `dev` for pre-deploy experimentation, `staging` for pre-prod with explicit CORS. Today's plan makes `dev` permissive and `staging`/`production` strict; a future plan could split `staging` into its own middle ground (e.g. permissive with a startup WARNING) if operators request it.
- A misconfigured operator who sets `ENV=production` without setting `CORS_ALLOWED_ORIGINS` will see a fail-fast `pydantic.ValidationError` at app startup with a clear remediation message (the WHAT to do is spelled out in the message). The plan trades "silent misconfig in prod" for "fail-fast at startup" — this is the canonical security-first posture.

## Escape hatches

- If an operator MUSTERD a hotfix and needs `["*"]` in prod (e.g. emergency mobile-app rollout before CORS allowlist is known), they should set `ENV=dev` AS A TEMPORARY MEASURE until the allowlist is determined. The plan's intent is fail-fast-by-default, not "make prod hard"; operators always have the `ENV=dev` escape hatch baked in. This is documented as a runbook line in CONTRIBUTING.md (out of scope to write the runbook here, but the contract is `ENV` is the single dial).
- If a future plan introduces `AUTH_DEV_TOKENS_AUTO_APPROVE=1` or similar dev-only flags, they should be gated on `Settings.env == "dev"` for the same reason this plan gates CORS.
- If a downstream service (e.g. Prometheus exporter) needs to scrape `/api/v1/health/summary` cross-origin and the operator DOES want wide-open CORS in prod for monitoring purposes, the canonical path is a separate ingress route for the health endpoint (out of scope here).
