# Plan 089 (v0.9.29) — `gw2_core.__version__` dynamic lookup via `importlib.metadata`

## Files touched
- `libs/gw2_core/src/gw2_core/__init__.py` (1-line replacement of the literal `__version__`)
- `libs/gw2_core/pyproject.toml` (1-line version bump `0.3.0` → `0.5.0` to match the actual code state)

## Findings (audit)

- `__init__.py` line 41: `__version__ = "0.5.0"` is HARDCODED.
- `pyproject.toml` line 3: `version = "0.3.0"` is STALE.
- **The two values disagree.** Whatever you bump, the other one will drift again on the next release.
- The actual code state is post-`0.3.0`: the package ships Phase 8 (`BuffRemovalEvent` in `models.py`), the PEP 695 `type Event = ...` discriminated union, and the `accounts` enrichment models (`AccountInfo` / `WorldInfo`) — all of which are documented in design docs as "v0.5+" evolution. The hardcoded `"0.5.0"` in `__init__.py` was someone's attempt to keep the runtime introspection honest; the package metadata got left behind.
- The sibling libraries all converge on the `importlib.metadata.version("name")` pattern with a `PackageNotFoundError` fallback:
  - `gw2_evtc_parser` per plan 042 (v0.9.9).
  - `gw2_analytics` per plan 054 (v0.9.17).
  - `gw2_api_client` per plan 042 (same pattern, same PR).
  - `gw2analytics_api` per plan 077 (v0.9.25).
- `gw2_core` is the ONE library in the workspace still doing the literal `__version__ = "0.X.Y"` thing — the canonical convention is dynamic.

## Fix

1. `libs/gw2_core/src/gw2_core/__init__.py` — replace:

   ```python
   __version__ = "0.5.0"
   ```

   with:

   ```python
   try:
       from importlib.metadata import PackageNotFoundError, version as _pkg_version

       __version__ = _pkg_version("gw2_core")
   except PackageNotFoundError:
       # Editable installs inside the source tree before `pip install -e`
       # resolve to a wheel-less context. The other gw2_* libraries carry
       # the same fallback so introspection still returns a string.
       __version__ = "0.0.0+unknown"
   ```

2. `libs/gw2_core/pyproject.toml` — bump:

   ```toml
   version = "0.3.0"
   ```

   to:

   ```toml
   version = "0.5.0"
   ```

   so `__version__` (dynamic, reads `pyproject`) and the unpinned introspection (`pip show gw2_core`) agree. The next release bumps `pyproject.toml` only — the literal in `__init__.py` no longer exists.

## Tests (5 hermetic, NEW file `libs/gw2_core/tests/test_gw2_core_init.py`)

- `test_version_matches_pyproject_toml` — `gw2_core.__version__ == importlib.metadata.version("gw2_core")`. This is the invariant: any future release bump that forgets to update `pyproject.toml` fails here.
- `test_version_is_three_part_semver_string` — regex `^\d+\.\d+\.\d+(\+[a-z0-9]+)?$` matches `gw2_core.__version__`. Catches accidental `"v0.5"` / `"0.5"` / `"latest"` typos.
- `test_version_remains_string_type_after_dynamic_swap` — sanity: `isinstance(gw2_core.__version__, str)` even after the `try/except` (regression test against accidentally returning the int from a leftover `return 0;` branch).
- `test_package_not_found_fallback_returns_unknown_sentinel` — `monkeypatch.setattr(importlib.metadata, 'version', _raise_PNF)` → `gw2_core.__version__ == "0.0.0+unknown"`. The sentinel uses the `+<local>` semver tag form so downstream tooling knows it's "not a released build".
- `test_dunder_all_lists_version` — `"__version__" in gw2_core.__all__`. Defensive against a future refactor that re-exports via `from gw2_core.models import *` and forgets the version string.

## Rejected alternatives

- **Edit the literal to `"0.5.0"` and forget about it** → defeats the entire point of dynamic resolution; re-opens the drift on the next release. The sibling libs all moved to dynamic for this exact reason. REJECTED.
- **Move `__version__` into `models.py` instead of `__init__.py`** → break the canonical convention used across the other 4 libraries; `models.py` is the data-shape module, `__init__.py` is the package-level metadata surface. REJECTED.
- **Drop `__version__` entirely and require callers to use `importlib.metadata.version("gw2_core")`** → breaks the Python community convention (`__version__` is the de-facto attribute `pip show`, IDEs, and `python -c "import x; print(x.__version__)"` introspection read). REJECTED.
- **Use `version("gw2_core")` without the `try/except`** → breaks editable installs when the package is run from the source tree before `pip install -e .`. The four sibling libs all carry the `PackageNotFoundError` branch for the same reason. REJECTED.
- **Bump `pyproject.toml` only, leave `__init__.py` literal at "0.5.0"** → WORKS for the next release but the test suite will still pass with arbitrary mismatches; loses the test_enforced invariant that "release bumps only touch `pyproject.toml`". The dynamic lookup is what gets you the test invariant. REJECTED.

## Dependency graph

- Independent: touches `__init__.py` + `pyproject.toml`; no interaction with plans 090 / 091 (different file regions: `models.py` enum / `models.py::AccountInfo`).
- Pattern-aligned with the four sibling libraries (plans 042 / 054 / 077), so future PRs across the workspace can copy the import block instead of re-deriving it.
