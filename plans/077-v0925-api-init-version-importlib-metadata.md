# Plan 077 — v0.9.25 — apps/api `__init__.py::__version__` derived from `importlib.metadata`

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Addressed finding (LOW-MED DX + correctness):** `apps/api/src/gw2analytics_api/__init__.py` hardcodes `__version__ = "0.8.6"`. Drift vs the actual installed package (currently `0.9.2` per `pyproject.toml` + the 14 release tags). Plan 042 (v0.9.12) introduced `_resolve_app_version()` via `importlib.metadata.version("gw2analytics_api")` for `main.py`'s OpenAPI `version=` field but DIDN'T update `__init__.py`. Plan 054 (v0.9.17) introduced `importlib.metadata` for the 3 library `__init__.py` files (`gw2_core` + `gw2_analytics` + `gw2_evtc_parser`) but DIDN'T apply to `apps/api`. Fix derives `__version__` from the installed package via the same `_resolve_app_version()` helper (or its inline equivalent), with a `PackageNotFoundError` fallback `"0.0.0+unknown"`.

## File changes

### 1 file edited + 1 NEW test file

**A. `apps/api/src/gw2analytics_api/__init__.py`** — current 11-line file:

```python
"""FastAPI gateway for GW2Analytics.

This package is a **thin** HTTP layer: it serializes :mod:`gw2_core`
models in and out. No business logic lives here.
"""

from __future__ import annotations

from gw2analytics_api.main import app

__version__ = "0.8.6"

__all__ = ["__version__", "app"]
```

becomes:

```python
"""FastAPI gateway for GW2Analytics.

This package is a **thin** HTTP layer: it serializes :mod:`gw2_core`
models in and out. No business logic lives here.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from gw2analytics_api.main import app

# v0.9.25 plan 077: derive `__version__` from the installed package
# (not a hard-coded string). Matches the canonical pattern from
# plan 042 v0.9.12 (`main.py` OpenAPI version) + plan 054 v0.9.17
# (`_resolve_parser_version()` for the 3 library __init__.py files).
# The fallback `"0.0.0+unknown"` covers the rare case where the
# package is imported without being installed (e.g., a CI workflow
# that adds the source tree to ``sys.path`` without ``pip install -e .``).
try:
    __version__ = _pkg_version("gw2analytics_api")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["__version__", "app"]
```

The eager `from gw2analytics_api.main import app` re-export is preserved (consumers like `python -m gw2analytics_api.__main__` depend on it).

**B. NEW `apps/api/tests/test_init_version.py`** — 5 hermetic tests for the 5 surfaces:

| # | Test | Asserts |
|---|---|---|
| 1 | `__version__` is a non-empty `str` | The field always exists; the literal `"0.8.6"` is gone |
| 2 | `__version__` does NOT equal `"0.8.6"` | Drift is fixed; the current `0.9.2` is reflected (after a normal `pip install -e .` in the dev env) |
| 3 | `__version__` parses to a valid PEP 440 version when installed | Uses `packaging.version.Version(__version__)` to assert the canonical format (`MAJOR.MINOR.PATCH` or the `0.0.0+local.<hash>` dev format) |
| 4 | The `__all__` tuple is `["__version__", "app"]` (unchanged) | The re-export contract is stable |
| 5 | When `gw2analytics_api` is `PackageNotFoundError`, the fallback `"0.0.0+unknown"` is used (covered by monkeypatching `_pkg_version` to raise `PackageNotFoundError`) | The defensive fallback path works |

## Considered and rejected

- **Alternative: bump the hard-coded `"0.8.6"` to the current version `"0.9.2"`** — drift returns on every release, requires a maintainer to update 2 files (`__init__.py` + `pyproject.toml`) in lockstep.
- **Alternative: delete the `__version__` re-export** — breaks the public API; `python -c "import gw2analytics_api; print(gw2analytics_api.__version__)"` is a documented op-tool pattern in `CONTRIBUTING.md`.
- **Alternative: define `__version__` in `pyproject.toml` and read it via `tomllib`** — `importlib.metadata` is the canonical PEP 621 path; `tomllib` is for pyproject introspection only.
- **Alternative: move `__version__` to a NEW `_version.py` file** to keep `__init__.py` minimal — adds a module without benefit; `__init__.py`'s `__version__` is a Python-package convention (`SQLAlchemy`, `pydantic`, `requests` all do the same).
- **Alternative: import `_resolve_app_version()` from `main.py` directly** — `main.py` defines it without exporting; refactoring `main.py` to expose it is a wider change. The plan re-uses the inline pattern from plan 054 instead.

## Effort

`S` — 1 file edit + 1 NEW test file (5 tests). All additive (no deletions). Backwards-compatible re-export contract. Independent of plans 078 + 079.
