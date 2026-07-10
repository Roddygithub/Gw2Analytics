# advisor-plan 016 — Settings env loading consistency (`os.environ.get()` → `get_settings()`)

## Problem

Multiple modules read `os.environ.get(...)` directly instead of using the cached `get_settings()` accessor. Inconsistent pattern: some env vars are validated by `pydantic-settings` (DATABASE_URL, SECRETS_KEK, S3_*, ARQ_REDIS_HOST), others are read raw. The risk is silent env-var drift — a future pydantic validator added to Settings won't apply to raw reads. New env-driven feature work stalls because each contributor picks their own pattern.

## Context

- `apps/api/src/gw2analytics_api/parser_settings.py:48-49` — `_REDIS_HOST: str = os.environ.get("ARQ_REDIS_HOST", "localhost")` raw read at module import time.
- `apps/api/src/gw2analytics_api/routes/uploads.py:72,90` — `os.environ.get("ALLOW_INREQUEST_PARSE_FALLBACK")` raw read at request time.
- `apps/api/src/gw2analytics_api/routes/webhooks.py:138` — `os.environ.get(...)` raw read.
- `apps/api/src/gw2analytics_api/crypto.py:76` — `os.environ.get("SECRETS_KEK")` raw read WITHIN helper. Already passed via pydantic in normal code path but raw fallback.
- `apps/api/src/gw2analytics_api/schema_guard.py:122` — `os.environ.get("SKIP_SCHEMA_GUARD")` raw read.

## Approach

Centralize env reads via `get_settings()` (cached `lru_cache` accessor). Add 4 Settings fields for currently-raw env vars. Replace the 6 raw reads with `settings.<field>`. Maintain `monkeypatch` reset semantics in tests via `get_settings.cache_clear()` + `monkeypatch.setenv()` (already the established pattern in `tests/test_config.py:21-100`).

## Files

**In scope**:
- MODIFIED `apps/api/src/gw2analytics_api/config.py` (add 5 fields)
- MODIFIED `apps/api/src/gw2analytics_api/parser_settings.py` (use settings)
- MODIFIED `apps/api/src/gw2analytics_api/routes/uploads.py` (use settings)
- MODIFIED `apps/api/src/gw2analytics_api/routes/webhooks.py` (use settings)
- MODIFIED `apps/api/src/gw2analytics_api/schema_guard.py` (use settings)
- MODIFIED `apps/api/src/gw2analytics_api/crypto.py` (use settings)
- NEW `apps/api/tests/test_config_extras.py` (lock in 5 fields)

**Out of scope**:
- The alembic `env.py` (NO pydantic dependency — uses raw env directly).
- The `web/scripts/dump_openapi.py` (separate process; outside pydantic).

## Steps

1. Add to `apps/api/src/gw2analytics_api/config.py`:
   ```python
   arq_redis_host: str = Field(default="localhost", validation_alias="ARQ_REDIS_HOST")
   arq_redis_port: int = Field(default=6379, validation_alias="ARQ_REDIS_PORT")
   allow_inrequest_parse_fallback: bool = Field(default=False, validation_alias="ALLOW_INREQUEST_PARSE_FALLBACK")
   skip_schema_guard: bool = Field(default=False, validation_alias="SKIP_SCHEMA_GUARD")
   secrets_kek_fallback: list[str] = Field(default=[], validation_alias="SECRETS_KEK_FALLBACK")
   ```
2. Replace `os.environ.get("ARQ_REDIS_HOST", "localhost")` → `get_settings().arq_redis_host` in `parser_settings.py:48`.
3. Replace `os.environ.get("ALLOW_INREQUEST_PARSE_FALLBACK")` → `get_settings().allow_inrequest_parse_fallback` in `routes/uploads.py:72,90`.
4. Replace raw reads in `routes/webhooks.py:138` with the appropriate settings field.
5. Replace `os.environ.get("SKIP_SCHEMA_GUARD")` in `schema_guard.py:122` → `get_settings().skip_schema_guard`.
6. Replace `os.environ.get("SECRETS_KEK")` in `crypto.py:76` → `get_settings().secrets_kek.get_secret_value()`.
7. Add `apps/api/tests/test_config_extras.py`:
   - Lock in `arq_redis_host`, `arq_redis_port`, `allow_inrequest_parse_fallback`, `skip_schema_guard`, `secrets_kek_fallback` parsing — mirror the existing `test_config.py:1-100` pattern (`monkeypatch.setenv` + `get_settings.cache_clear`).

## Verification

- `grep -rE 'os\.environ\.get' apps/api/src/` → should drop from ~6 to 0 (or to 1, the documented escape-hatch exception).
- `uv run pytest apps/api/tests/test_config_extras.py -v` → all green.
- `uv run pytest` (full suite) → all green (no regression).

## Test plan

- 5 new Settings parsing tests (1 per new field); some may combine if a field shares patterns.
- Existing tests should pass unchanged (only the SOURCE of truth changed, not the BEHAVIOR).

## Done criteria

- 5 new Settings fields present.
- 6 raw reads replaced.
- 5 new + all existing tests pass.
- Lint + mypy + ruff all green.

## Maintenance note

- Future env vars should be added to Settings, NOT via raw `os.environ.get()`. Document this in CONTRIBUTING.md (small CONTRIBUTING note).
- The `_env_file=None` test pattern in `test_config.py:46-100` MUST be preserved — `pydantic-settings`'s `.env` auto-load interferes with explicit env assertions.
- `get_settings` is a `lru_cache`'d accessor; tests MUST `cache_clear()` before re-asserting env-driven fields (already the pattern).

## Escape hatch

- If a module genuinely CAN'T import from `gw2analytics_api.config` (circular import or import-time-only path), keep one raw `os.environ.get(...)` AND add a comment citing this plan as known-debt. Document the location.
- If a future pydantic-settings upgrade changes `validation_alias` semantics, retest the new fields explicitly.
