# Plan 092 (v0.9.30) — `gw2_api_client.__version__` dynamic lookup via `importlib.metadata`

## Files touched
- `libs/gw2_api_client/src/gw2_api_client/__init__.py` (1-line replacement of the literal `__version__`)

## Findings (audit)

- `__init__.py` line 29: `__version__ = "0.1.0"` is HARDCODED.
- `pyproject.toml` line 3: `version = "0.1.0"` MATCHES the literal — there's NO drift today.
- But the static-vs-dynamic convention across the 5-library workspace is inconsistent: 4 of 5 libs (`gw2_evtc_parser` plan 042, `gw2_analytics` plan 054, `gw2analytics_api` plan 077, `gw2_core` plan 089) all converged on `importlib.metadata.version("name")` with a `PackageNotFoundError` fallback. `gw2_api_client` is the LAST library still doing the literal pattern.
- Future-bump ergonomic: plan 089 documented the invariant — "any future release bump that forgets to update `pyproject.toml` fails here at the test layer". Without that invariant on `gw2_api_client`, a release bump can drift between the literal in `__init__.py` and the metadata in `pyproject.toml` forever (no test failure to catch it). The 5-library workspace should converge on the same enforcement surface for symmetry.

## Fix

1. `libs/gw2_api_client/src/gw2_api_client/__init__.py` — replace:

   ```python
   __version__ = "0.1.0"
   ```

   with:

   ```python
   try:
       from importlib.metadata import PackageNotFoundError, version as _pkg_version

       __version__ = _pkg_version("gw2_api_client")
   except PackageNotFoundError:
       # Editable installs inside the source tree before `pip install -e`
       # resolve to a wheel-less context. The other gw2_* libraries carry
       # the same fallback so introspection still returns a string.
       __version__ = "0.0.0+unknown"
   ```

2. NO `pyproject.toml::version` change needed (already `"0.1.0"`, matches introspection).

## Tests (5 hermetic, NEW file `libs/gw2_api_client/tests/test_gw2_api_client_init.py`)

- `test_version_matches_pyproject_toml` — `gw2_api_client.__version__ == importlib.metadata.version("gw2_api_client")`. Cross-library invariant: any future release bump that forgets to update `pyproject.toml` fails here AT THE TEST LAYER for this library the same way plan 089 enforces it for `gw2_core`.
- `test_version_is_three_part_semver_string` — regex `^\d+\.\d+\.\d+(\+[a-z0-9]+)?$` matches `gw2_api_client.__version__`.
- `test_version_remains_string_type_after_dynamic_swap` — sanity: `isinstance(gw2_api_client.__version__, str)` even after the `try/except` (regression test against accidentally returning an int from a leftover `return 0;` branch).
- `test_package_not_found_fallback_returns_unknown_sentinel` — `monkeypatch.setattr(importlib.metadata, 'version', _raise_PNF)` → `gw2_api_client.__version__ == "0.0.0+unknown"`. The sentinel uses the `+<local>` semver tag form so downstream tooling knows it's "not a released build".
- `test_dunder_all_lists_version` — `"__version__" in gw2_api_client.__all__`. Defensive guard against a future refactor that re-exports via `from gw2_api_client.client import *` and forgets the version string.

## Rejected alternatives

- **Leave the literal at `"0.1.0"` since there's no drift today** — fine today, but releases drift without a test-layer invariant. The 4 sibling libs all moved to dynamic for the same reason; leaving gw2_api_client static would be the ONE library in the workspace that breaks the pattern. REJECTED.
- **Bump the literal to "1.0.0" without touching pyproject** — introduces drift that the future test can't catch (no test fixture, no dynamic resolution). The dynamic lookup is what gets you the test invariant. REJECTED.
- **Drop `__version__` entirely and require callers to use `importlib.metadata.version("gw2_api_client")` directly** — breaks the Python community convention (`__version__` is the de-facto attribute `pip show`, IDEs, and `python -c "import x; print(x.__version__)"` introspection read). REJECTED.
- **Use `version("gw2_api_client")` without the `try/except`** — breaks editable installs when the package is run from the source tree before `pip install -e .`. The four sibling libs all carry the `PackageNotFoundError` branch for the same reason. REJECTED.
- **Move `__version__` into `client.py` instead of `__init__.py`** — break the canonical convention used across the other 4 libraries; `client.py` is the implementation module, `__init__.py` is the package-level metadata surface. REJECTED.

## Dependency graph

- Independent: touches `__init__.py` only (no `pyproject.toml` change because there's no drift).
- Parallel-safe with plans 093 / 094 (different file regions: 093 touches `client.py::_get_with_retries`; 094 touches `client.py` constants + `__init__` url wiring).
- Pattern-aligned with the four sibling libraries (plans 042 / 054 / 077 / 089), so future PRs across the workspace can copy the import block instead of re-deriving it. The 5-library ecosystem now uses an IDENTICAL `try / except PackageNotFoundError` import block — small but real DX win for the contributor who has to bump all five `pyproject.version` values next release.
