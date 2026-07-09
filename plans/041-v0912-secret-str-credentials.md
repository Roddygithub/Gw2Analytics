# Plan 041 — v0.9.12 config: `SecretStr` for credentials

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — main/db/storage/config deep pass
**Status:** pending
**Effort:** S
**Category:** security (defence in depth: log redaction) + DX
**Files touched:** `apps/api/src/gw2analytics_api/config.py` (1 file, additive changes only) + `apps/api/src/gw2analytics_api/database.py` (1-line change to unwrap the SecretStr) + `apps/api/src/gw2analytics_api/storage.py` (1-line change to unwrap the SecretStr) + `apps/api/tests/test_config.py` (NEW test cases)

## Problem

`apps/api/src/gw2analytics_api/config.py::Settings` stores
the credentials as plain `str`:

```python
database_url: str = Field(validation_alias="DATABASE_URL")
minio_endpoint: str = Field(validation_alias="S3_ENDPOINT")
minio_access_key: str = Field(validation_alias="S3_ACCESS_KEY")
minio_secret_key: str = Field(validation_alias="S3_SECRET_KEY")
```

The `database_url` typically embeds the Postgres password
in the connection string
(`postgresql+psycopg://user:password@host/db`). The
`minio_secret_key` is the MinIO root password. Both are
secrets that should be redacted in any logged output.

A naive `logger.info("settings: %s", settings.model_dump())`
prints the secrets in plain text. The canonical Pydantic v2
defence is `SecretStr` — a wrapper type whose
`__repr__` returns `"**********"` and whose `get_secret_value()`
returns the underlying `str`. Any code that reads the
secret must call `.get_secret_value()` explicitly, so a
naive `logger.info` of the `Settings` object redacts the
secrets automatically.

### Severity

- **Security**: MED — defence in depth. The current
  code has no logger.info of secrets, but a future
  contributor who adds `logger.info(settings)` for
  debugging would leak the credentials to the log
  stream (which is shipped to the operator's log
  aggregator + the CI artefacts on failure).
- **DX**: MED — explicit `.get_secret_value()` at the
  read site makes the secret-handling code path
  self-documenting. A future contributor reading
  `get_engine()` sees `settings.database_url.get_secret_value()`
  and knows "this is a secret, treat it carefully".

### Affected callers

- `apps/api/src/gw2analytics_api/database.py::get_engine` —
  reads `settings.database_url`.
- `apps/api/src/gw2analytics_api/storage.py::get_minio` —
  reads `settings.minio_secret_key` + `settings.minio_access_key`.
- The CI workflow's `OpenAPI: dump FastAPI spec` step
  passes `DATABASE_URL: "postgresql+psycopg://ci@localhost/ci"`
  (no password; the test DB has no password). The
  change to `SecretStr` would require the test
  workflow to use `.get_secret_value()` OR the test
  fixture to set the value as a plain string (which
  `SecretStr` accepts at the Pydantic boundary).

## Goals

- Switch `database_url`, `minio_secret_key`, and
  `minio_access_key` to `SecretStr` in `Settings`.
- Update `database.py::get_engine` + `storage.py::get_minio`
  to call `.get_secret_value()` on the secret fields.
- Add a `__repr__` test that asserts the secrets are
  redacted in `repr(settings)` + `settings.model_dump()`.
- Add a `get_secret_value()` test that asserts the
  unwrapped string matches the env var value.

## Non-goals

- Encrypting the secrets at rest (e.g. SOPS, HashiCorp
  Vault, pgcrypto envelope encryption). Out of scope
  (the v0.9.1 deferred list tracks
  "webhook secret-at-rest"; the same architecture
  applies here).
- Switching the `minio_endpoint` to `SecretStr`. The
  endpoint is not a secret (it's the host:port of the
  MinIO server, which is visible in the URL bar of
  the MinIO console).
- Redacting the `parser_version` field (it's a
  version string, not a secret).
- Adding a custom log filter that redacts known
  secret patterns from log output. The Pydantic
  v2 `SecretStr` is the canonical defence; a custom
  log filter is over-engineered for the current
  surface.

## Implementation

### File: `apps/api/src/gw2analytics_api/config.py`

Switch the 3 secret fields to `SecretStr`. The diff is
a 3-line type change + a 3-line `min_length` removal
(SecretStr is itself the type; the `min_length` is
the wrong constraint for a SecretStr).

```python
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """..."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # Credentials use ``SecretStr`` (Pydantic v2) so a
    # naive ``logger.info(settings)`` redacts the
    # secrets automatically. Callers that need the
    # underlying string call ``.get_secret_value()``
    # explicitly (e.g. ``settings.database_url.get_secret_value()``).
    #
    # The ``min_length`` constraints were removed
    # because ``SecretStr`` enforces non-emptiness at
    # the type level; an empty ``DATABASE_URL``
    # raises a clear ``ValidationError`` at startup.
    database_url: SecretStr = Field(validation_alias="DATABASE_URL")
    minio_endpoint: str = Field(validation_alias="S3_ENDPOINT")
    minio_access_key: SecretStr = Field(validation_alias="S3_ACCESS_KEY")
    minio_secret_key: SecretStr = Field(validation_alias="S3_SECRET_KEY")
    minio_bucket: str = Field(validation_alias="S3_BUCKET")

    # ... (rest of Settings unchanged) ...
```

### File: `apps/api/src/gw2analytics_api/database.py`

Update `get_engine` to call `.get_secret_value()`.

```python
def get_engine() -> Engine:
    """..."""
    global _engine  # noqa: PLW0603
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            # ``SecretStr.get_secret_value()`` unwraps the
            # wrapper. SQLAlchemy's ``create_engine`` takes
            # a plain ``str``; the wrapper is purely a
            # defence-in-depth measure against accidental
            # ``logger.info(settings)`` calls.
            settings.database_url.get_secret_value(),
            future=True,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
        )
    return _engine
```

### File: `apps/api/src/gw2analytics_api/storage.py`

Update `get_minio` to call `.get_secret_value()` on the
secret fields.

```python
def get_minio() -> Minio:
    """..."""
    global _client  # noqa: PLW0603
    if _client is None:
        s = get_settings()
        _client = Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key.get_secret_value(),
            secret_key=s.minio_secret_key.get_secret_value(),
            secure=s.minio_secure,
        )
    return _client
```

### File: `apps/api/tests/test_config.py` (NEW test cases)

```python
import pytest

from gw2analytics_api.config import Settings, get_settings


class TestSecretStr:
    """The credential fields are ``SecretStr`` (v0.9.12
    plan 041) so accidental log leaks are redacted."""

    def test_database_url_is_secret_str(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``settings.database_url`` is a ``SecretStr``."""
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/d")
        get_settings.cache_clear()
        settings = Settings()
        from pydantic import SecretStr
        assert isinstance(settings.database_url, SecretStr)

    def test_secret_str_get_secret_value_returns_raw_string(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``settings.database_url.get_secret_value()``
        returns the raw env var value."""
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/d")
        get_settings.cache_clear()
        settings = Settings()
        assert (
            settings.database_url.get_secret_value()
            == "postgresql+psycopg://u:p@h/d"
        )

    def test_repr_redacts_secrets(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``repr(settings)`` does NOT include the raw
        secret values."""
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:SECRET@h/d")
        monkeypatch.setenv("S3_ACCESS_KEY", "SECRET_KEY")
        monkeypatch.setenv("S3_SECRET_KEY", "SECRET_PASSWORD")
        get_settings.cache_clear()
        settings = Settings()
        rep = repr(settings)
        assert "SECRET" not in rep
        assert "SECRET_KEY" not in rep
        assert "SECRET_PASSWORD" not in rep

    def test_model_dump_redacts_secrets(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``settings.model_dump()`` returns
        ``SecretStr`` instances (not raw strings) for
        the secret fields."""
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/d")
        monkeypatch.setenv("S3_SECRET_KEY", "minio-secret-password")
        get_settings.cache_clear()
        settings = Settings()
        dumped = settings.model_dump()
        from pydantic import SecretStr
        assert isinstance(dumped["database_url"], SecretStr)
        assert isinstance(dumped["minio_secret_key"], SecretStr)
```

## Test plan

1. **4 new hermetic tests** in
   `apps/api/tests/test_config.py` cover the 4 secret-
   handling paths (SecretStr type, get_secret_value
   returns raw, repr redacts, model_dump returns
   SecretStr).
2. **All existing tests pass** — the change is
   backwards-compatible for any code that reads the
   secret via `.get_secret_value()` (the canonical
   pattern).
3. **`uv run pytest apps/api/tests/`** exits 0.
4. **`uv run mypy --no-incremental libs apps`** is
   clean.

## Acceptance criteria

- [ ] 3 Settings fields are switched to `SecretStr`:
      `database_url`, `minio_access_key`,
      `minio_secret_key`.
- [ ] `database.py::get_engine` calls
      `.get_secret_value()` on `database_url`.
- [ ] `storage.py::get_minio` calls `.get_secret_value()`
      on `minio_access_key` + `minio_secret_key`.
- [ ] 4 new hermetic tests pass.
- [ ] All existing tests pass.
- [ ] `mypy --no-incremental` is clean.
- [ ] `ruff check` is clean.
- [ ] No production code paths change (the secret
      read sites call `.get_secret_value()` which
      unwraps to the same string the previous code
      used).

## Out-of-scope / deferred

- **Encrypting the secrets at rest** (SOPS, Vault,
  pgcrypto envelope encryption): out of scope (the
  v0.9.1 deferred list tracks "webhook
  secret-at-rest"; the same architecture applies
  here).
- **Switching `minio_endpoint` to `SecretStr`**:
  out of scope (the endpoint is not a secret).
- **Redacting `parser_version`**: out of scope
  (it's a version string, not a secret).
- **Adding a custom log filter** that redacts known
  secret patterns: out of scope (Pydantic v2
  `SecretStr` is the canonical defence).

## Maintenance notes

- **`SecretStr` is Pydantic v2 only**. The project
  is on Pydantic v2 (per the prior audit cycles),
  so the change is a no-op for the Pydantic
  version.
- **The `.get_secret_value()` call is explicit at
  each read site**. A future contributor reading
  `get_engine()` sees
  `settings.database_url.get_secret_value()` and
  knows the value is a secret. The pattern is
  self-documenting.
- **`SecretStr` does NOT encrypt the value in
  memory**. The value is stored as a plain string
  in the `SecretStr` wrapper; a memory dump
  attacker could extract the secret. The defence
  is purely against accidental log leaks. The
  at-rest encryption (SOPS, Vault, pgcrypto
  envelope) is a future hardening tracked in the
  v0.9.1 deferred list.
- **The test asserts that `repr(settings)` does
  NOT include the raw secret values**. The
  canonical Pydantic v2 `SecretStr.__repr__` is
  `SecretStr('**********')`; the test verifies
  this contract.
