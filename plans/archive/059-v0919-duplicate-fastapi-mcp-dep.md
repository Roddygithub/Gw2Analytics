# Plan 059 — v0.9.19: dedupe `fastapi-mcp` in `apps/api/pyproject.toml` + httpx on shared line

## Drift base

`44ea862`. Drift cleanup only — additive, no migration.

## Surface

`apps/api/pyproject.toml` (the API package's `dependencies` list).

## Finding

The `dependencies` array in `apps/api/pyproject.toml` has 2
real issues:

1. **Duplicate `fastapi-mcp` constraint with conflicting
   minimums** (line 12: `fastapi-mcp>=0.4` AND line 22:
   `fastapi-mcp>=0.1`). Both entries are kept by the TOML parser
   (TOML arrays are order-preserving), but `uv` / `pip` resolve
   the union of constraints — `>=0.4` and `>=0.1` resolve to
   `>=0.4` (the higher minimum wins). So the dependency is
   *functionally* correct, but:
   - the two entries are syntactically sloppy (a human reading
     the file cannot tell which is the canonical constraint)
   - drift risk: a future operator who edits one entry to
     `fastapi-mcp>=0.5` (to opt into a new feature) will leave
     the other at `>=0.1`, and the union becomes `>=0.5` —
     correct, but the intent is unclear
   - the `uv lock` output will be confusing (two entries
     collapsed in the lockfile but visible in the source)

2. **`httpx>=0.27"` and `"gw2_core"` on the same line** (line 23).
   The list line reads `"httpx>=0.27",    "gw2_core",` (4-space
   separator). Valid TOML, but unusual. The "first item" of the
   line is `"httpx>=0.27"`; the rest of the line is the start of
   `gw2_core`. The line is hard to read; a future operator
   skimming the file for `gw2_core` may miss it because the
   grep `^.*gw2_core` returns 5 lines but the eyeball-pairing
   is non-canonical.

## Fix

1. Remove the second `fastapi-mcp>=0.1` entry. Keep the
   canonical `fastapi-mcp>=0.4` entry on its own line.

2. Split the `"httpx>=0.27",    "gw2_core",` shared line so
   each item is on its own line.

3. Re-sort the `dependencies` list alphabetically for
   readability (the existing order is roughly alphabetical
   with 2 stray items; the re-sort surfaces any future drift
   in PR review).

4. After the cleanup, the canonical `dependencies` list:

   ```toml
   dependencies = [
       "alembic>=1.13",
       "fastapi-mcp>=0.4",
       "fastapi>=0.115",
       "gw2_analytics",
       "gw2_api_client>=0.1.0",
       "gw2_core",
       "gw2_evtc_parser",
       "httpx>=0.27",
       "minio>=7.2",
       "psycopg[binary]>=3.2",
       "pydantic-settings>=2.6",
       "pydantic>=2.9",
       "python-multipart>=0.0.20",
       "sqlalchemy>=2.0",
       "uvicorn[standard]>=0.32",
   ]
   ```

## Why `fastapi-mcp>=0.4` is the canonical minimum

The MCP integration in `main.py` uses `FastApiMCP(app).mount()`
which was added in `fastapi-mcp` 0.2+. The `>=0.4` minimum
includes the latest MCP spec support + the `mount()` API
stability. The `>=0.1` minimum would have been the v0.1.0
alpha and is not the canonical pick.

## Risks

- `uv lock` will re-resolve the dependency tree. The
  resolved versions are unchanged (the `>=0.4` minimum
  already constrained the resolution). The lockfile diff
  is purely cosmetic (the canonical list has 14 entries
  instead of 15).
- A future change to the `fastapi-mcp` constraint (e.g.,
  `>=0.5`) is now a single-line edit instead of a
  two-line edit. Less drift risk.

## Tests

1. `test_no_duplicate_fastapi_mcp` — parse
   `apps/api/pyproject.toml`; assert `fastapi-mcp` appears
   exactly once in the `dependencies` list.
2. `test_fastapi_mcp_minimum_is_0_4` — assert the canonical
   constraint is `>=0.4` (not `>=0.1`).
3. `test_dependencies_are_one_item_per_line` — parse the
   list; assert no line has more than one `"..."` string
   literal separated by `,    ` (the "shared line" pattern).
4. `test_dependencies_are_alphabetically_sorted` — assert
   the list is in alphabetical order (case-insensitive;
   the canonical sort places `fastapi-mcp` before
   `fastapi` because of the hyphen; the canonical Python
   sorted order with hyphens is well-defined).
5. `test_uv_lock_remains_valid` — run `uv lock --check`;
   assert the exit code is 0 (the cleanup doesn't break
   the lockfile resolution).

## Rejected alternatives

- **Sort the list by purpose (web framework, ORM, MCP,
  storage, ...)**: tempting (groups related deps). The
  alphabetical sort is the canonical Python community
  convention (per PEP 8 for `__all__` + the pip-tools
  default); a purpose-based sort is a future
  customisation.
- **Drop `fastapi-mcp` from `[project].dependencies` and
  add it to a `mcp` dependency group**: out of scope. The
  package is a production runtime dep (the `mount()` runs
  at import time per plan 042's `_build_app()` factory).
  A future plan can move it to an optional group if the
  MCP integration becomes opt-in (per plan 042's
  `ENABLE_MCP` flag).
- **Pin `fastapi-mcp` to an exact version (e.g.,
  `fastapi-mcp==0.4.2`)**: out of scope. The `>=0.4`
  minimum is the canonical "minimum compatible" pin; an
  exact pin forces every release to bump the dep.
- **Add a CI test that fails on duplicate dep entries**:
  tempting (prevents future drift). A `toml` parser-based
  test is a 1-time-write; the canonical pattern is to
  enforce the rule via a `ruff` custom rule (out of
  scope — the v0.9.x audit pass doesn't introduce
  custom ruff rules).
