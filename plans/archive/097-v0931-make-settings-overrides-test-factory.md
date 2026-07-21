# Plan 097 (v0.9.31) — `make_settings(**overrides)` test factory activating `populate_by_name=True`

## Files touched
- NEW `apps/api/tests/_settings_factory.py` (NEW public function `make_settings(**overrides)`)
- `apps/api/tests/_fixtures.py` (1-line addition: `from ._settings_factory import make_settings`)
- `apps/api/tests/test_config.py` (3 new tests demonstrating override patterns; existing tests UNCHANGED)

## Findings (audit)

- `config.py::Settings::model_config` includes `populate_by_name=True` (set in v0.9.0 per the inline comment). The comment explains: "lets callers pass `Settings(cors_allowed_origins=[...])` by the Python field name while keeping `validation_alias="CORS_ALLOWED_ORIGINS"` for env input".
- But the configured flag is **UNUSED** in the test suite:
  - All test overrides today go through env-var mutation + `get_settings.cache_clear()` (3 steps: monkeypatch env, clear cache, re-call).
  - The `Settings(kw=...)` Python-name construction path the flag enables is LEFT AS-IS — no test uses it, no helper exposes it.
- Result: every test that wants to flip a CORS setting, swap a parser_version, or override minio_bucket does the 3-step dance. The "supported" Python-name construction is dead code until something bridges it.
- Real-world impact: 4 of the 11 `test_*.py` files in `apps/api/tests/*` (per the v0.9.26 audit) currently call `monkeypatch.setenv("DATABASE_URL", ...)` followed by `get_settings.cache_clear()` followed by `get_settings()`. Each pair is repeatable boilerplate.

## Fix

1. NEW `apps/api/tests/_settings_factory.py`:

   ```python
   """Test factory for ``gw2analytics_api.config.Settings``.

   Activates the ``populate_by_name=True`` configuration flag on
   :class:`Settings` (which has been reachable since v0.9.0 but is
   currently unused by any test in the suite). Lets a test construct
   a Settings instance with Python-name overrides:

   >>> from apps.api.tests._settings_factory import make_settings
   >>> settings = make_settings(
   ...     database_url="postgresql://test/test",
   ...     parser_version="0.6.0",
   ...     cors_allowed_origins=["https://test"],
   ... )

   The factory clears the :func:`get_settings` ``lru_cache`` before
   AND after the construction so the next test that DOES use the
   production cache picks up the env-var baseline (no state leak).
   Internally the factory uses the configured
   ``model_config.populate_by_name=True`` flag to accept the
   Python-name override keys; the flag's setting-aliases are
   consulted FIRST so an env-derived field can be overridden by a
   Python-keyword argument.
   """
   from __future__ import annotations

   from typing import Any

   import pytest

   from gw2analytics_api.config import Settings, get_settings


   def make_settings(**overrides: Any) -> Settings:
       """Build a Settings instance with Python-name overrides.

       Clears :func:`get_settings` ``lru_cache`` BEFORE reading the
       env-derived baseline so the overrides sees a clean cache
       (defensive — a stale cache from a previous test would
       otherwise be missed by the new instance). The cache is
       cleared AGAIN after construction to leave the env-var
       baseline ready for the next test.

       Usage:

       >>> s = make_settings(cors_allowed_origins=["https://x"])
       >>> s.cors_allowed_origins == ["https://x"]

       The factory's required-field exceptions are matched to the
       production env-derived values when ``pytest-env`` is in
       effect (the test runner auto-loads ``.env``).
       """
       get_settings.cache_clear()
       try:
           if overrides:
               return Settings(**overrides)
           # Even with no overrides, return a FRESH Settings
           # (not the cached one) so the caller can mutate it
           # freely without contaminating the cache.
           return Settings()
       finally:
           get_settings.cache_clear()


   @pytest.fixture
   def make_settings_fixture(make_settings):  # type: ignore[no-redef]
       """Pytest fixture wrapper around :func:`make_settings`.

       Aliases the function so tests can return a configured
       ``Settings`` from a fixture without spelling out the
       factory each time. Most tests will call ``make_settings``
       directly without this fixture — the fixture exists for the
       cases where the test also depends on env-derived defaults
       in the same test body.
       """
       return make_settings
   ```

2. `apps/api/tests/_fixtures.py` — add the import for downstream tests:

   ```python
   from gw2analytics_api._cache_reset import reset_infrastructure_caches  # plan 095
   from ._settings_factory import make_settings  # plan 097
   ```

3. NO change to `apps/api/src/gw2analytics_api/config.py` (the `populate_by_name=True` flag is already configured).

## Tests (4 hermetic + 3 demonstration tests)

NEW hermetic tests in `test_config.py`:

- `test_make_settings_accepts_python_name_override_for_optional_field` — `make_settings(parser_version="0.6.0").parser_version == "0.6.0"`. Verifies the populated-by-name path for an optional field; the easiest verdict because `parser_version` has no env-var alias.
- `test_make_settings_accepts_python_name_override_for_aliased_field` — `make_settings(database_url="postgresql://x/y").database_url == "postgresql://x/y"`. Verifies the populated-by-name path for an aliased required field (`validation_alias="DATABASE_URL"`).
- `test_make_settings_clears_lru_cache_before_and_after_construction` — use a sequence: `get_settings.cache_clear(); s1 = Settings(); get_settings(); assert get_settings.cache_info().currsize == 1`, then call `make_settings(database_url="...")`, then call `get_settings()` again, assert `cache_info().currsize == 1` (the cache is post-construction-empty, the next access returns the env-var baseline cached fresh). Defensive: catches a regression where the factory forgets the after-construction clear.
- `test_make_settings_isolated_from_previous_test_state` — sequence: monkeypatch `os.environ` to a sentinel, `make_settings(database_url="postgresql://override/x")` (env override ignored because of explicit kwarg), assert the result sees the kwarg, NOT the env. Reverses the experiment: confirms the factory prioritises kwarg over env.

NEW demonstration tests in same file (3 small tests, ~10 lines each):

- `test_demo_override_single_field_for_cors_test` — pattern shown: `csrf_settings = make_settings(cors_allowed_origins=["https://csrf-test"])`. Demonstrates the typical use-case: a route test wants to assert CORS headers in isolation.
- `test_demo_override_parser_version_for_regression_check` — shows how an analyst can flip `parser_version` for a regression test (the parser-version-dependent code path in `services.py`).
- `test_demo_override_minio_bucket_for_storage_test` — shows how an isolated MinIO test can target a different bucket (e.g. `events-test-2024-12-09`) without polluting the env.

## Rejected alternatives

- **Drop `populate_by_name=True` from the Settings config** — the flag is configured dead code today; removing it makes the cleanup. But the flag was added with the explicit comment "Settings(kw=...)" intentionally, and removing it would close the door on a future test factory (the OPPOSITE of what this plan wants). The factory is the activation, not the removal. REJECTED.
- **Inline `get_settings.cache_clear() + Settings(**overrides)` boilerplate in every test** — exactly what the factory replaces; the factory is the DRY hoist. REJECTED.
- **Add the factory to `apps/api/src/gw2analytics_api/config.py`** rather than `tests/_settings_factory.py` — mixes the test convenience with the production module; conceptually backwards. The factory lives in `tests/` only. REJECTED.
- **Replace the monkeypatch.setenv pattern entirely with `make_settings`** — tool-creep: the monkeypatch pattern is fine for tests that want the env-var mutation to leak across the lru_cache layer; `make_settings` is the right tool for tests that want a self-contained instance. They complement, not replace. REJECTED.
- **Use `pydantic_settings.Settings(**overrides)` directly without a wrapper** — the wrapper adds the cache-clear behaviour + the convention ("every test factory call goes through this helper"). The bare pydantic-settings call would be one-shot per test and easily forgotten in the next test. REJECTED.
- **Make `make_settings` a context manager (`with make_settings(...) as s:`)** — the context manager would auto-clean-up on exit; but the factory's job is to construct an instance for the test's consumption (often passed to a fixture), and the lru_cache cleanup happens at the `finally` block already, no context manager needed. Overengineering. REJECTED.
- **Add `make_settings` to the `apps/api/src/gw2analytics_api/__init__.py` exports** — would leak the test factory into the production package; consumers shouldn't import a test factory. REJECTED.

## Dependency graph

- Independent: NEW `apps/api/tests/_settings_factory.py` + 1-line `_fixtures.py` import + 4 hermetic tests + 3 demonstration tests in `test_config.py`.
- No production-source change — `populate_by_name=True` is already configured on `Settings`. The factory ACTIVATES the existing flag, not adds new public surface.
- Complements plan 095 (reset_infrastructure_caches) — different tools for different jobs:
  - `make_settings` returns a self-contained Settings instance for a test that wants isolation but not env-mutation propagation.
  - `reset_infrastructure_caches` is the cleanup hook for a test that DOES mutate env vars and wants the next access to see the mutation.
  - Tests that want BOTH (mutate env + override kwarg) call `reset_infrastructure_caches`, set the env var, and pass the override kwarg to `make_settings` — clean composition.
- No interaction with plan 096 (`events_blob_uri` semantics).
