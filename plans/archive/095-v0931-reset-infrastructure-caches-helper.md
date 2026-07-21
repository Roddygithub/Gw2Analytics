# Plan 095 (v0.9.31) — `reset_infrastructure_caches()` consolidation for test isolation

## Files touched
- NEW `apps/api/src/gw2analytics_api/_cache_reset.py` (NEW helper module — single public function `reset_infrastructure_caches()`)
- `apps/api/src/gw2analytics_api/config.py` (no functional change; the helper accesses `get_settings.cache_clear()` from outside)
- `apps/api/src/gw2analytics_api/database.py` (no functional change; the helper resets the `_engine` + `_SessionLocal` globals)
- `apps/api/src/gw2analytics_api/storage.py` (no functional change; the helper resets `_client`)
- NEW `apps/api/tests/test_cache_reset.py` (5 hermetic tests)

## Findings (audit)

- `apps/api` has 4 SEPARATE module-global cache / lazy-singleton surfaces:
  1. `config.py::get_settings` decorated with `@lru_cache` — reset path is `get_settings.cache_clear()`.
  2. `database.py::_engine` lazy singleton — reset path is `global _engine; _engine = None`.
  3. `database.py::_SessionLocal` lazy singleton — reset path is `global _SessionLocal; _SessionLocal = None`.
  4. `storage.py::_client` lazy singleton — reset path is `global _client; _client = None`.
- Every test that mutates env vars (and needs the mutation to be visible to a downstream re-instantiation of the engine / settings / minio client) must remember to reset ALL FOUR paths individually. If it forgets one (typically the `_client` in storage because it's the most recently-touched), the next test sees STALE state — silent footgun.
- v0.9.1 fixed the same problem in 4 separate places per the work surfaced by plan 005 + plan 009 conftest testing isolation (the webhook retry test had to clear settings cache to pick up the new `DATABASE_URL` set by the fixture; a sibling test of the DLQ path saw the cached value and surfaced a 500-class bug). That fix landed per-test rather than per-helper; this plan closes the same problem at the helper-layer for the rest of the test suite (new tests are likely to hit the same footgun).
- The pydantic-settings doc block on `Settings.model_config` mentions `populate_by_name=True` and notes "Settings(kw=...)" is meant to work — but the paths to make it WORK in tests (clear cache + reset globals + mutate env) are scattered across 4 files. A single helper consolidates the reset into 1 call.

## Fix

1. NEW `apps/api/src/gw2analytics_api/_cache_reset.py`:

   ```python
   """Test-isolation helper.

   Wipes every module-global cache / lazy-singleton that BUILDS FROM
   environment variables so a test that mutates an env var (e.g.
   ``monkeypatch.setenv("DATABASE_URL", ...)``) sees the
   mutation on the next access. The 4 surfaces covered:

   1. :func:`gw2analytics_api.config.get_settings` (``lru_cache``)
   2. :func:`gw2analytics_api.database.get_engine` (lazy ``_engine``)
   3. :func:`gw2analytics_api.database.get_sessionmaker` (lazy ``_SessionLocal``)
   4. :func:`gw2analytics_api.storage.get_minio` (lazy ``_client``)

   The helper is exactly the canonical "reset everything that
   depends on env vars" call. Tests that mutate env vars and then
   expect a downstream consumer to see the mutation must call this
   helper before the consumer is exercised; tests that DO NOT mutate
   env vars should still call it once at the top of the test for
   hermetic isolation from the previous test's state.
   """
   from __future__ import annotations

   import gw2analytics_api.config as _config
   import gw2analytics_api.database as _database
   import gw2analytics_api.storage as _storage


   def reset_infrastructure_caches() -> None:
       """Clear every module-global cache / lazy-singleton in ``apps/api``.

       Idempotent — safe to call at the top of every test, before any
       env mutation, and after a fixture teardown. The function is
       deterministic: the order is (settings cache → engine →
       sessionmaker → minio client), which mirrors the dependency
       order (settings → engine → sessionmaker → minio client).
       """
       _config.get_settings.cache_clear()
       _database._engine = None  # type: ignore[attr-defined]  # noqa: SLF001
       _database._SessionLocal = None  # type: ignore[attr-defined]  # noqa: SLF001
       _storage._client = None  # type: ignore[attr-defined]  # noqa: SLF001


   __all__ = ["reset_infrastructure_caches"]
   ```

2. NO change to `config.py`. NO change to `database.py`. NO change to `storage.py`. The helper reaches in to reset their globals from outside.

3. `tests/conftest.py` (the existing per-package conftest) — add the helper as the default `autouse=True` fixture so EVERY test in `apps/api/tests/*` runs with a clean cache baseline:

   ```python
   from gw2analytics_api._cache_reset import reset_infrastructure_caches


   @pytest.fixture(autouse=True)
   def _reset_caches() -> None:
       """Every test starts and ends with a clean module-global
       cache baseline. Mirrors the v0.9.1 conftest fixture (plan 009
       Step 5) which the webhook retry tests carry."""
       reset_infrastructure_caches()
       yield
       reset_infrastructure_caches()
   ```

   Effectively normalises the v0.9.1 conftest pattern (which was scoped to the webhook test files) to the whole package, so no future test file has to remember the helper.

## Tests (5 hermetic, NEW file `apps/api/tests/test_cache_reset.py`)

- `test_reset_clears_settings_lru_cache` — call `reset_infrastructure_caches()`, mutate `os.environ["DATABASE_URL"]` (use `monkeypatch`), then call `get_settings()` and assert the new value is read (was stale before the helper).
- `test_reset_clears_engine_lazy_singleton` — same pattern: monkeypatch the URL, call helper, `get_engine()` returns an engine whose URL `str(...)` matches the patched value (was stale before).
- `test_reset_clears_sessionmaker_lazy_singleton` — same; verifies `_SessionLocal` is reset so a sessionmaker call returns a fresh factory bound to the patched engine.
- `test_reset_clears_minio_client_lazy_singleton` — same; verifies `_client` reset so a subsequent `get_minio()` constructs a NEW Minio with the patched `S3_ENDPOINT`.
- `test_conftest_autouse_applies_to_existing_test_files` — pick one existing test file (e.g. `test_uploads_e2e.py`), instantiate the autouse fixture, assert `get_settings.cache_info().currsize == 0` and `_engine is None`. Defensive regression: catches a future regression where the conftest fixture is removed.

## Rejected alternatives

- **Add a `reset_*` helper per module** (`config.reset_settings_cache`, `database.reset_engine`, `storage.reset_minio_client`) and let each test call each in turn — same fragmented problem at a different layer. The single helper consolidates. REJECTED.
- **Use `functools.cache` (which is thread-safe at init time) instead of manual `_engine = None` resets** — would simplify `database.py` but introduce 2 more `functools.cache`-decorated globals; the new caches still need a reset path. Net LOC change is a wash. Manual helper is more discoverable. REJECTED.
- **Skip the autouse conftest fixture and let tests opt in via `@pytest.mark.usefixtures("reset_caches")`** — works for new tests but every LEGACY test (the 10 existing `test_*.py` files including the v0.8 webhook fix that motivated this) must be retro-fitted. The autouse fixture does it once. REJECTED.
- **Move the reset helper into `gw2analytics_api.config`** to keep it co-located with the cache it clears — couples the helper to the settings layer; the helper resets 3 modules, none of which is `config`. The `_cache_reset.py` module is the right home. REJECTED.
- **Replace the 4 lazy singletons with `functools.cache` so each has a built-in `.cache_clear()`** — would touch the production code of 3 files (`config.py`, `database.py`, `storage.py`) for a 1-line cosmetic win. The helper keeps the production code untouched. REJECTED.
- **Make every test path call `reset_infrastructure_caches()` manually in its body** — works for new tests but bloats the legacy tests; the autouse fixture normalises it. REJECTED.

## Dependency graph

- Independent: NEW `apps/api/src/gw2analytics_api/_cache_reset.py` + NEW `apps/api/tests/test_cache_reset.py`.
- Reads 3 production modules (`config`, `database`, `storage`) but does NOT modify them — production code is unchanged.
- Conftest change is OPTIONAL (works without it but tests must opt in). The plan recommends adding the autouse fixture proactively so future tests inherit the isolation.
- Pattern-aligned with the v0.9.1 webhook conftest (`plan 005` + `plan 009` Step 5): this plan generalises the same isolation to the WHOLE package instead of just the webhook tests.
