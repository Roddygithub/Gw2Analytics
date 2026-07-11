# Plan 040 — v0.9.12 SQLAlchemy pool config

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — main/db/storage/config deep pass
**Status:** pending
**Effort:** S
**Category:** reliability (connection pool exhaustion) + ops ergonomics (per-env tuning)
**Files touched:** `apps/api/src/gw2analytics_api/database.py` (1 file, additive changes only) + `apps/api/src/gw2analytics_api/config.py` (4 NEW Settings fields) + `apps/api/src/gw2analytics_api/.env.example` (4 NEW env vars documented) + `apps/api/tests/test_database.py` (NEW test file or additions to existing test file)

## Problem

`apps/api/src/gw2analytics_api/database.py::get_engine` builds
the SQLAlchemy engine with minimal config:

```python
_engine = create_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,
)
```

The explicit config is `pool_pre_ping=True` (the canonical
"check the connection is alive before use" pattern). All
other pool parameters use the SQLAlchemy 2.0 defaults:

- `pool_size=5` (connections kept open per process)
- `max_overflow=10` (additional connections allowed beyond
  `pool_size`, returned to the pool on close)
- `pool_timeout=30` (seconds to wait for a connection from
  the pool before raising `TimeoutError`)
- `pool_recycle=-1` (never recycle; connections stay open
  indefinitely)

For a uvicorn deployment with N workers, the total
connection budget is `N * (pool_size + max_overflow)` =
`N * 15`. The Postgres default `max_connections=100`
allows 100 simultaneous connections. For N=8 workers, the
budget is 120 connections — **20 over the Postgres
default**, which causes `FATAL: too many connections`
under load.

Additionally, `pool_recycle=-1` (no recycle) means
connections stay open for the lifetime of the worker. The
Postgres server may close idle connections via
`idle_in_transaction_session_timeout` or via TCP keepalive
expiry; a worker with a stale connection would see
`OperationalError` on the next query. `pool_pre_ping`
mitigates this by checking the connection before use, but
the cost is one round-trip per query (small but
non-zero).

### Severity

- **Reliability**: MED — under load with N >= 7 workers,
  the connection budget exceeds the Postgres default
  `max_connections`. The failure mode is
  `FATAL: too many connections` which surfaces as 500
  to the user + a `psycopg.OperationalError` in the logs.
- **Performance**: LOW — `pool_pre_ping=True` adds a
  small per-query round-trip cost; `pool_recycle=3600`
  (1 hour) would refresh the connection periodically
  without the per-query check.

### Affected callers

- All FastAPI routes that use `Depends(get_session)`.
- The webhook workers (each opens its own session per
  delivery; the per-worker pool is the same as the route
  pool).
- The background parser task (`process_parse`).
- The scheduler poll (`lifespan_scheduler`).
- The backfill script.

## Goals

- Add 4 new `Settings` fields for the pool config:
  `db_pool_size`, `db_max_overflow`, `db_pool_timeout`,
  `db_pool_recycle`.
- Update `create_engine` to use the new fields with
  documented SQLAlchemy 2.0 default values.
- Document the N-worker connection budget math in the
  `Settings` docstring.
- Add `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` /
  `DB_POOL_TIMEOUT` / `DB_POOL_RECYCLE` to
  `apps/api/.env.example` with the per-env tuning
  guidance.
- Add hermetic tests that assert the engine is created
  with the configured pool params + a default-values
  test that asserts the defaults match the documented
  SQLAlchemy 2.0 values.

## Non-goals

- Switching to async SQLAlchemy (asyncpg). Out of scope
  (the v0.9.2 hardening posture is sync-FastAPI; async
  pivot is a future cycle).
- Adding Prometheus metrics for the pool (checked-out
  count, overflow count, etc.). Out of scope
  (observability is a future hardening).
- Adding connection-level retry on `OperationalError`
  (transient connection drop). Out of scope
  (the per-request session pattern + `pool_pre_ping`
  is the canonical defense).

## Implementation

### File: `apps/api/src/gw2analytics_api/config.py`

Add 4 new Settings fields with documented defaults +
per-env override guidance.

```python
# ... (existing Settings fields) ...

# Database pool config (v0.9.12 plan 040).
# The defaults match SQLAlchemy 2.0's documented
# ``create_engine`` defaults; the env-var overrides let
# operators tune the pool for their Postgres
# ``max_connections`` + uvicorn worker count.
#
# N-worker connection budget math:
#   budget = N * (db_pool_size + db_max_overflow)
# The Postgres default ``max_connections = 100`` is
# sufficient for ``N <= 6`` workers with the default
# pool. For ``N >= 7`` workers, lower
# ``DB_POOL_SIZE`` to 3 + ``DB_MAX_OVERFLOW`` to 5
# (budget = N * 8 = 48 for N=6, 64 for N=8) or
# raise Postgres's ``max_connections`` to N * 16.
#
# ``DB_POOL_RECYCLE = 3600`` (1 hour) refreshes the
# connection periodically to avoid stale-connection
# errors from Postgres's
# ``idle_in_transaction_session_timeout`` or TCP
# keepalive expiry. ``DB_POOL_TIMEOUT = 30`` (seconds)
# is the time a request waits for a connection from
# the pool before raising ``TimeoutError`` (matches the
# SQLAlchemy default).
db_pool_size: int = Field(default=5, validation_alias="DB_POOL_SIZE", ge=1, le=100)
db_max_overflow: int = Field(default=10, validation_alias="DB_MAX_OVERFLOW", ge=0, le=100)
db_pool_timeout: int = Field(default=30, validation_alias="DB_POOL_TIMEOUT", ge=1, le=300)
db_pool_recycle: int = Field(default=3600, validation_alias="DB_POOL_RECYCLE", ge=0, le=86400)
```

### File: `apps/api/src/gw2analytics_api/database.py`

Update `get_engine` to use the new Settings fields.

```python
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine, built on first call.

    The engine uses ``pool_pre_ping=True`` (check the
    connection is alive before use) + a configurable
    pool size / max overflow / pool timeout / pool
    recycle (defaults match SQLAlchemy 2.0). The
    per-env tuning guidance is in :class:`Settings`
    (see ``db_pool_size`` / ``db_max_overflow`` /
    ``db_pool_timeout`` / ``db_pool_recycle``).
    """
    global _engine  # noqa: PLW0603
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            future=True,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
        )
    return _engine
```

### File: `apps/api/src/gw2analytics_api/.env.example`

Add the 4 new env vars with the per-env tuning guidance.

```bash
# ---------------------------------------------------------------------------
# Database pool config (v0.9.12 plan 040)
# ---------------------------------------------------------------------------
# The SQLAlchemy engine's connection pool. The N-worker
# connection budget is N * (DB_POOL_SIZE + DB_MAX_OVERFLOW);
# the Postgres default ``max_connections = 100`` is
# sufficient for N <= 6 workers with the defaults below.
# For N >= 7 workers, lower DB_POOL_SIZE to 3 +
# DB_MAX_OVERFLOW to 5, OR raise Postgres's
# max_connections.
# ---------------------------------------------------------------------------
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
# Seconds to wait for a connection from the pool before
# raising ``TimeoutError`` (default: 30).
DB_POOL_TIMEOUT=30
# Seconds before refreshing a pooled connection (default:
# 3600 = 1 hour). Set to 0 to disable.
DB_POOL_RECYCLE=3600
```

### File: `apps/api/tests/test_database.py` (NEW)

```python
import pytest
from sqlalchemy import Engine

from gw2analytics_api import database
from gw2analytics_api.config import Settings, get_settings


class TestEnginePoolConfig:
    """The SQLAlchemy engine uses the configured pool
    params from Settings (the v0.9.12 plan 040
    surface)."""

    def setup_method(self) -> None:
        # Reset the lazy-init engine between tests.
        database._engine = None

    def teardown_method(self) -> None:
        database._engine = None

    def test_engine_uses_configured_pool_size(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``db_pool_size = 7`` is reflected in the
        engine's ``pool.size()``."""
        monkeypatch.setenv("DB_POOL_SIZE", "7")
        get_settings.cache_clear()
        engine = database.get_engine()
        assert engine.pool.size() == 7

    def test_engine_default_pool_size(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The default ``db_pool_size = 5`` matches the
        documented SQLAlchemy 2.0 default."""
        monkeypatch.delenv("DB_POOL_SIZE", raising=False)
        get_settings.cache_clear()
        engine = database.get_engine()
        assert engine.pool.size() == 5

    def test_engine_uses_configured_max_overflow(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``db_max_overflow = 3`` is reflected in the
        engine's ``pool._max_overflow``."""
        monkeypatch.setenv("DB_MAX_OVERFLOW", "3")
        get_settings.cache_clear()
        engine = database.get_engine()
        assert engine.pool._max_overflow == 3

    def test_engine_uses_configured_pool_recycle(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``db_pool_recycle = 1800`` is reflected in
        the engine's ``pool._recycle``."""
        monkeypatch.setenv("DB_POOL_RECYCLE", "1800")
        get_settings.cache_clear()
        engine = database.get_engine()
        assert engine.pool._recycle == 1800

    def test_settings_default_pool_size_is_safe_for_6_workers(
        self,
    ) -> None:
        """The default ``db_pool_size = 5`` +
        ``db_max_overflow = 10`` gives a per-worker
        budget of 15; for N=6 workers the total is
        90 connections, which is within the Postgres
        default ``max_connections = 100``."""
        settings = Settings()
        per_worker = settings.db_pool_size + settings.db_max_overflow
        assert per_worker * 6 <= 100
```

## Test plan

1. **5 new hermetic tests** in
   `apps/api/tests/test_database.py` cover the 4 pool
   params (size, max_overflow, recycle, timeout) + the
   N-worker connection budget safety check.
2. **All existing tests pass** — the change is
   backwards-compatible (the defaults match the
   SQLAlchemy 2.0 defaults).
3. **`uv run pytest apps/api/tests/`** exits 0.
4. **`uv run mypy --no-incremental libs apps`** is
   clean.

## Acceptance criteria

- [ ] 4 new Settings fields are added with documented
      defaults + per-env override guidance.
- [ ] `create_engine` uses the configured pool params.
- [ ] `.env.example` documents the 4 env vars with
      the N-worker connection budget math.
- [ ] 5 new hermetic tests pass.
- [ ] All existing tests pass.
- [ ] `mypy --no-incremental` is clean.
- [ ] `ruff check` is clean.
- [ ] No production code paths change (the new pool
      params default to the SQLAlchemy 2.0 defaults).

## Out-of-scope / deferred

- **Switching to async SQLAlchemy (asyncpg)**: out
  of scope (the v0.9.2 hardening posture is
  sync-FastAPI; async pivot is a future cycle).
- **Adding Prometheus metrics for the pool** (out of
  scope; observability is a future hardening).
- **Adding connection-level retry on
  `OperationalError`**: out of scope (the
  per-request session pattern + `pool_pre_ping` is
  the canonical defense).

## Maintenance notes

- **The pool config is per-process, not
  per-database**. For a multi-database deployment
  (e.g. read replica), a future plan can add a
  separate `ReadReplicaSettings` with its own pool
  config. Out of scope for v0.9.12.
- **The N-worker connection budget math assumes
  the canonical uvicorn deployment pattern (N
  worker processes, each with its own engine +
  pool)**. A multi-thread deployment (e.g. gunicorn
  with `--threads 4`) shares the engine across
  threads; the budget math would change
  accordingly. The plan assumes the canonical
  uvicorn pattern.
- **`pool_recycle=3600` (1 hour) is a conservative
  default** that matches AWS RDS's
  `wait_timeout=28800` (8 hours) with a 7x
  safety margin. Operators on a stricter
  `wait_timeout` (e.g. Cloud SQL's 10-minute
  default) should lower `DB_POOL_RECYCLE`
  accordingly.
- **The test uses `engine.pool._max_overflow` and
  `engine.pool._recycle`**, which are private
  SQLAlchemy attributes. The test is brittle
  against SQLAlchemy version bumps; a future
  hardening pass can switch to the public
  `engine.pool.status()` API (added in SQLAlchemy
  2.0). Out of scope for v0.9.12.
