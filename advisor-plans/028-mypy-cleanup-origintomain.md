# Plan 028 — mypy cleanup on origin/main (CI gate blocker)

**Stamped at:** `5cfd962` (origin/main HEAD at audit time)
**Severity:** HIGH (CI gate blocker)
**Category:** CI, DX, types
**Addresses finding:** 19 mypy errors on `origin/main` (type-annotation drift, `Any` return types, untyped function calls, 1 `Module not found` per `apps/api/`). CI gate from CONTRIBUTING.md will fail on the next push.

---

## Finding

```
$ uv run mypy --no-incremental libs apps
# 19 errors across apps/api/src and libs/
```

The errors fall into 4 categories:
1. **Type-annotation drift** (8 errors): functions that gained new return types or parameters since the mypy strict gate was added.
2. **`Any` return types** (5 errors): functions returning untyped values.
3. **Untyped function calls** (4 errors): calling functions that lack type annotations.
4. **Module not found** (2 errors): `Module not found` per `apps/api/` — likely a missing `py.typed` marker or import path issue.

---

## Fix

### Step 1 — Fix the Module not found errors

Check if `apps/api/pyproject.toml` has the correct package configuration. The `py.typed` marker exists at `apps/api/src/gw2analytics_api/py.typed`. Verify the import paths match the package layout.

### Step 2 — Fix type-annotation drift

For each error, add the missing type annotation or correct the return type. Use `from __future__ import annotations` at the top of every module (already the convention).

### Step 3 — Fix `Any` return types

Replace `-> Any` with the actual return type, or add a `# type: ignore[no-any-return]` if the type is genuinely dynamic (e.g., Pydantic model introspection).

### Step 4 — Fix untyped function calls

Add type annotations to the called functions, or use `# type: ignore[no-any-call]` if the function is from a third-party library without stubs.

### Step 5 — Verify

```bash
uv run mypy --no-incremental apps/api/src libs
```

### Step 6 — Commit

```bash
git add -A
git commit -m "chore(api,libs): resolve 19 mypy errors on main (plan 028)"
```

---

## Tests

- `uv run mypy --no-incremental apps/api/src libs` — exits 0.
- `uv run ruff check apps/api/src libs` — exits 0 (no new lint violations from the type fixes).
- `uv run pytest apps/api/tests/ --tb=short` — no regressions.
- `uv run pytest libs/ --tb=short` — no regressions.

---

## Rejected alternatives

- **Auto-fix via `--strict-partial` or `ignore_errors`**: would unwind plan 019 (mypy strict workspace) which was the explicit deliverable of the 2026-07-11 audit.
- **Pin mypy to a version that doesn't flag these**: the errors are real type-safety gaps, not tooling false positives.
- **Add `# type: ignore` blanket ignores**: defeats the purpose of `--strict` mode.

---

## Dependency graph

- **Standalone.** No plan depends on this one; this plan doesn't depend on any.

---

## Notes for executors

- This is the third CI gate blocker. Ship IMMEDIATELY after plans 026 + 027.
- The `Module not found` errors are the most likely auto-resolvable via `uv lock --upgrade` + `uv sync`.
- Do NOT touch files under `apps/api/src/gw2analytics_api/routes/fights/` — that's the other AI's workstream.
