# Plan 098 (v0.9.32) — `gw2_evtc_parser.__version__` dynamic lookup via `importlib.metadata` + pyproject.toml bump

## Files touched
- `libs/gw2_evtc_parser/src/gw2_evtc_parser/__init__.py` (1-line replacement of the literal `__version__`)
- `libs/gw2_evtc_parser/pyproject.toml` (1-line version bump `0.1.0` → `0.5.0` to match the runtime introspection)

## Findings (audit)

- `__init__.py` line 23: `__version__ = "0.5.0"` is HARDCODED.
- `pyproject.toml` line 3: `version = "0.1.0"` is STALE.
- **The two values disagree by FOUR minor versions.** This is the WORST version drift in the entire 5-library workspace:
  - `gw2_core` (plan 089 v0.9.29): 0.3.0 vs 0.5.0 (2 minor versions apart).
  - `gw2_api_client` (plan 092 v0.9.30): matching at 0.1.0 (no drift).
  - `gw2_analytics` / `gw2analytics_api`: already migrated to dynamic per plan 042 / 054 / 077.
- `gw2_evtc_parser` is the only workspace library whose `__version__` literal is BOTH (a) hardcoded and (b) FOUR minor versions behind the pyproject metadata's intent (assuming the runtime literal "0.5.0" reflects the actual code state — which matches the Phase 8 features shipped in `parser.py` + `interface.py` + `__main__.py`).
- Documentation drift: plan 042 (referenced in historical commit logs as "feat(api): v0.9.x plan 042") was supposed to migrate `gw2_evtc_parser` to `importlib.metadata`. Reviewing the current `__init__.py` shows the migration NEVER SHIPPED — the literal `"0.5.0"` is still there.
- The drift cascades: any consumer pinning `gw2_evtc_parser >= 0.4.0` resolves to the wheel whose `pyproject.toml::version = "0.1.0"` (the LATEST released version on PyPI is the SOURCE OF TRUTH), but `python -c "import gw2_evtc_parser; print(gw2_evtc_parser.__version__)"` returns `"0.5.0"`. The two introspection surfaces diverge.

## Fix

1. `libs/gw2_evtc_parser/src/gw2_evtc_parser/__init__.py` — replace:

   ```python
   __version__ = "0.5.0"
   ```

   with:

   ```python
   try:
       from importlib.metadata import PackageNotFoundError, version as _pkg_version

       __version__ = _pkg_version("gw2_evtc_parser")
   except PackageNotFoundError:
       # Editable installs inside the source tree before `pip install -e`
       # resolve to a wheel-less context. The other gw2_* libraries carry
       # the same fallback so introspection still returns a string.
       __version__ = "0.0.0+unknown"
   ```

2. `libs/gw2_evtc_parser/pyproject.toml` — bump:

   ```toml
   version = "0.1.0"
   ```

   to:

   ```toml
   version = "0.5.0"
   ```

   so `__version__` (dynamic, reads `pyproject`) matches the runtime literal that was hand-coded. After this fix, the runtime introspection surfaces AGREE with the actual code state (Phase 8 events, audience-aware parser call-sites, etc.).

3. RECONCILE the README + CHANGELOG references to "Plan 042 shipped" — historically claim the migration shipped; per this audit it didn't. Recommended follow-up: a 1-line CHANGELOG entry noting "v0.9.32 plan 098 closes the v0.9.x plan-042 promised-but-never-shipped migration".

## Tests (5 hermetic, NEW file `libs/gw2_evtc_parser/tests/test_gw2_evtc_parser_init.py`)

- `test_version_matches_pyproject_toml` — `gw2_evtc_parser.__version__ == importlib.metadata.version("gw2_evtc_parser")`. Test-enforced invariant: the WORST drift in the workspace is now caught at the test layer.
- `test_version_is_three_part_semver_string` — regex `^\d+\.\d+\.\d+(\+[a-z0-9]+)?$` matches `gw2_evtc_parser.__version__`.
- `test_version_remains_string_type_after_dynamic_swap` — sanity: `isinstance(gw2_evtc_parser.__version__, str)` even after the `try/except`.
- `test_package_not_found_fallback_returns_unknown_sentinel` — `monkeypatch.setattr(importlib.metadata, 'version', _raise_PNF)` → `gw2_evtc_parser.__version__ == "0.0.0+unknown"`.
- `test_dunder_all_lists_version` — `"__version__" in gw2_evtc_parser.__all__`. Defensive guard.

## Rejected alternatives

- **Leave the drift; bump only the `__init__.py` literal to "0.1.0" to match pyproject** — the runtime literal `"0.5.0"` was someone's attempt to reflect the actual code state (Phase 8 events, etc.); reverting it to `0.1.0` reverses the documentation effort. The pyproject bump to `0.5.0` honours the documentation AND the code. REJECTED.
- **Leave the drift; bump only `pyproject.toml` to "0.5.0" without touching `__init__.py`** — works for the next release but loses the test-layer invariant. The dynamic lookup is what enforces the invariant. REJECTED.
- **Skip the dynamic lookup entirely, just edit both literals to `"0.5.0"`** — fine today; on the next release, the literals would drift again. The 4 sibling libs all converged on dynamic for this reason. REJECTED.
- **Use `version("gw2_evtc_parser")` without the `try/except`** — breaks editable installs when the package is run from the source tree before `pip install -e .`. The four sibling libs all carry the `PackageNotFoundError` branch. REJECTED.

## Dependency graph

- Independent: touches `__init__.py` + `pyproject.toml` only.
- Parallel-safe with plans 099 / 100 (different file regions: 099 touches `interface.py` docstring; 100 touches `__main__.py::cmd_inspect_zip`).
- Pattern-aligned with the four sibling libraries (plans 042 / 054 / 077 / 089 / 092), so the 5-library workspace now uses an IDENTICAL `try / except PackageNotFoundError` import block.
- Documentation reconciliation: `CHANGELOG.md` should record the v0.9.32 plan-098 entry that closes the v0.9.x plan-042 promised-but-never-shipped migration (recommended, not required by this plan).
