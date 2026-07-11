# Plan 030 — v0.10.10: `schema_guard.check_schema_drift` must set absolute `script_location` on `AlembicConfig` (closes the CWD-dependent Alembic resolution bug)

**Stamped at:** `f0249ef` (working-tree diff HEAD; all changes in this plan live in the uncommitted working tree)
**Severity:** MED (correctness + DX — Uvicorn boots from CWD-relative resolution, breaks if launched from repo root)
**Category:** dx, correctness
**Addresses finding:** `apps/api/src/gw2analytics_api/schema_guard.py:71` calls `cfg = AlembicConfig(_alembic_cfg_path())` and then `head = ScriptDirectory.from_config(cfg).get_current_head()`. `apps/api/alembic.ini` declares `script_location = alembic` (line 3, **relative**). When `uvicorn apps.api.src.gw2analytics_api.main:app` is launched from the **repo root** (a common operator pattern + the README quickstart's `uv run fastapi dev apps/api/src/gw2analytics_api/main.py`), the operator's CWD is the repo root, NOT `apps/api/`. Alembic's `ScriptDirectory.from_config(...)` resolves `script_location = alembic` against the **OS current working directory**, so it searches `./alembic/` at the repo root. The directory doesn't exist; Alembic raises `alembic.util.exc.CommandError: Path doesn't exist: alembic`. The schema-drift guard then crashes Uvicorn at startup with an opaque stacktrace. The `_alembic_cfg_path()` helper correctly resolves the `.ini` location from `__file__` (lines 60-71) but does NOT propagate the same robustness to `script_location` inside the `.ini`.

---

## Finding

Evidence (current working-tree source):

```python
# apps/api/src/gw2analytics_api/schema_guard.py:71-85
def check_schema_drift() -> None:
    ...
    cfg = AlembicConfig(_alembic_cfg_path())
    head = ScriptDirectory.from_config(cfg).get_current_head()
```

And the relevant environment config:

```ini
# apps/api/alembic.ini:3
script_location = alembic
prepend_sys_path = .
```

### Why this only fails in specific launch modes

- `cd apps/api && uv run uvicorn apps.api.src.gw2analytics_api.main:app` → CWD is `apps/api/` → `script_location = alembic` resolves to `apps/api/alembic/` ✓ (works)
- `uv run uvicorn apps.api.src.gw2analytics_api.main:app` (from repo root) → CWD is repo root → `script_location = alembic` resolves to `<repo>/alembic/` (does NOT exist) → `CommandError: Path doesn't exist: alembic` ✗ (fails)
- `uv run fastapi dev apps/api/src/gw2analytics_api/main.py` (the README quickstart) → CWD is repo root → same failure mode

The README's Quickstart launches from the repo root → the schema-drift guard fails on a clean clone. Even worse: pre-v0.10.1 (before the schema-drift existed), the SAME bug would have manifested on `cd apps/api && uv run alembic upgrade head` (this DID work because the operator was in `apps/api/`). The drift guard ADDED this dependency on operator CWD, making the bug NEW.

---

## Fix

### Step 1 — Override `script_location` to an absolute path

In `apps/api/src/gw2analytics_api/schema_guard.py`, after `_alembic_cfg_path()` but BEFORE `ScriptDirectory.from_config(cfg)`:

```python
def check_schema_drift() -> None:
    ...
    cfg = AlembicConfig(_alembic_cfg_path())
    # v0.10.10 plan 030: override the ``script_location`` from the
    # ``alembic.ini`` (which is RELATIVE = ``alembic``) to an
    # ABSOLUTE path derived from the .ini's location. The operator
    # can now boot Uvicorn from the repo root (the README quickstart
    # + the canonical ``uv run fastapi dev`` path) without the
    # schema-drift guard crashing on Alembic's CWD-relative
    # resolution. Same `__file__`-based technique the helper
    # already uses to find ``alembic.ini`` (the .ini lives at
    # apps/api/alembic.ini; the migrations live at apps/api/alembic/
    # — sibling directories; one ``..`` from the .ini's parent
    # path).
    config_dir = Path(_alembic_cfg_path()).parent  # apps/api/
    cfg.set_main_option("script_location", str(config_dir / "alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
```

This pins `script_location` to an absolute path. The Alembic `ScriptDirectory.from_config()` reads `cfg.script_location` (absolute), bypassing the relative resolution.

### Step 2 — Keep the `prepend_sys_path` (relative) as-is

`prepend_sys_path = .` is also relative. The `_alembic_cfg_path()` resolution DOES NOT depend on `prepend_sys_path` (only on the `__file__` location). The Alembic env's `sys.path` prepend is for migration script imports (e.g. `from alembic.operations import ops`); not strictly required for the schema-drift guard (the guard never imports migration scripts). Leave as-is.

### Step 3 — Verify the existing `_alembic_cfg_path` test still passes

`apps/api/tests/test_schema_guard.py` mocks `ScriptDirectory.from_config` directly; the test does NOT exercise the CWD path. After this plan's fix, the test continues to mock the same call site (line 71 → 81 in the post-fix source).

---

## Tests

### Test file 1 — NEW `apps/api/tests/test_schema_guard_cwd_independence.py`

Pattern reference: `apps/api/tests/test_schema_guard.py` (existing hermetic tests).

4 hermetic tests:

1. `test_script_location_is_absolute_after_fix` — call `check_schema_drift()` (mocking the SQLAlchemy + `ScriptDirectory` paths). Inspect `AlembicConfig.set_main_option` calls (via a wrapped class or by capturing the mock). Assert `script_location` was set to an absolute path (starts with `/` on POSIX, drive letter on Windows).

2. `test_check_schema_drift_from_repo_root_cwd` — `monkeypatch.chdir(repo_root)` (the bug repro). The previous expectation: `CommandError: Path doesn't exist: alembic` raised. Post-fix: `check_schema_drift()` returns normally + `get_current_head()` is called on the absolute path.

3. `test_check_schema_drift_from_apps_api_cwd` — `monkeypatch.chdir(apps_api_dir)`. Both pre-fix and post-fix work; the test confirms no regression on the canonical `cd apps/api && uvicorn` launch mode.

4. `test_check_schema_drift_from_arbitrary_cwd` — `monkeypatch.chdir("/tmp")` (a far-away CWD). Pre-fix: fails with CommandError. Post-fix: returns normally. Pins the operator-experience fix.

### Test file 2 — EXTEND `apps/api/tests/test_schema_guard.py`

Add 1 regression test:

`test_alembic_config_uses_absolute_script_location` — mock `AlembicConfig` constructor; capture all `set_main_option(...)` calls; assert `"script_location"` was set, AND the value is `os.path.isabs()` True. Pins the production fix without depending on Alembic's internals.

---

## Out of scope

- Migrating `script_location` in `alembic.ini` to an absolute path (the `ini` file pattern is canonical — relative is preferred). This plan overrides at the Python `set_main_option` layer to avoid touching the ini file (which is shared with `alembic upgrade head` from the CLI, where relative paths work).
- Switching Alembic's `prepend_sys_path` to absolute (out of scope: the schema-drift guard doesn't import migration scripts).
- A `Settings`-driven override for `alembic.ini` path (currently hardcoded to `apps/api/alembic.ini` via `_alembic_cfg_path`). Out of scope.
- Diagnosing the v0.10.8 real-payload testing failure (different bug — was about ORM registry staleness after migration edit, not CWD resolution).

---

## Done criteria

Run from repo root after the fix is applied:

```bash
# 1. Ruff is clean.
uv run ruff check apps/api/

# 2. mypy --strict tolerates the change (the new local variable + set_main_option call is fully typed).
uv run mypy libs apps --no-incremental

# 3. Both new/extended test files pass.
uv run pytest apps/api/tests/test_schema_guard_cwd_independence.py -v
uv run pytest apps/api/tests/test_schema_guard.py -v

# 4. The full apps/api tests stay green.
uv run pytest apps/api/tests/ -q

# 5. The legacy `_alembic_cfg_path` helper is unchanged (no test regression).
grep -nE '_alembic_cfg_path' apps/api/src/gw2analytics_api/schema_guard.py
# Expected output: 1 match in `cfg = AlembicConfig(_alembic_cfg_path())` + 1 match in the helper definition.

# 6. The CWD-independent launch mode works end-to-end. From repo root, run:
cd /home/roddy/Gw2Analytics && uv run python -c "
from gw2analytics_api.schema_guard import check_schema_drift
import os
# Mock the DB call: skip the actual drift check.
os.environ['SKIP_SCHEMA_GUARD'] = '1'
check_schema_drift()
print('OK: schema-drift guard boots from repo root')
"
# Expected: "OK: schema-drift guard boots from repo root" (with the SKIP_SCHEMA_GUARD bypass log).
```

---

## Maintenance note

- `_alembic_cfg_path()` continues to derive `apps/api/alembic.ini` from `__file__`. If the project restructures (e.g. moves to `apps/api/db/`), update BOTH the helper + the new `set_main_option("script_location", ...)` line in lockstep. A grep check (`grep -rn 'alembic.ini' apps/api/`) is a reasonable CI guard.
- The `ScriptDirectory.from_config(cfg)` call is Alembic-version-sensitive. Across major Alembic versions (1.4 → 1.13+), the call signature is stable; minor versions don't change it. Pin Alembic in `pyproject.toml` if a future operator raises the floor.
- The `prepend_sys_path = .` in the `.ini` is preserved. If a future executor moves the migration scripts to a sub-directory (e.g. `apps/api/migrations/`), BOTH `script_location` AND `prepend_sys_path` need updates; this plan's fix is local to `set_main_option` and doesn't propagate.

---

## Escape hatches

- **`AlembicConfig.set_main_option` is renamed in a future Alembic version?** Update the line. The function is documented as stable but Pin Alembic's `>=` constraint if the operator's environment floats to a future major. Test `test_alembic_config_uses_absolute_script_location` will fail on a future Alembic API rename; surface this in the test name's `pytest.mark.skipif` accordingly.
- **Operator's `.ini` already has an absolute `script_location`?** The post-fix `set_main_option(...)` argument is a SET-MAIN-OPTION (overrides the ini's value); absolute your-override wins. No conflict. Tested implicitly in `test_alembic_config_uses_absolute_script_location`.
- **STOP and report back if**: a different deployment suddenly fails the `script_location` resolution post-fix. The bug is then in Alembic's `ScriptDirectory.from_config` accepting a non-path-like object (e.g. a relative path with a special character); surface as a separate Alembic-version audit, not this plan's surface.

---

## Dependency graph

- **Independent.** Touches only `apps/api/src/gw2analytics_api/schema_guard.py` + 1 NEW test file + 1 EXTENDED test file. No plan depends on this one; this plan doesn't depend on any.

## Cross-references

- Plan 010 (v0.10.1) — the original schema-drift guard (which introduced this CWD dependency). This plan closes a defect that plan 010 itself created.
- Plan 030 ↔ Plan 031: both touch `schema_guard.py`. Land them in the same PR for review convenience, OR in two atomic PRs if maintainer prefers per-concern commits. The two plans DO NOT depend on each other.
