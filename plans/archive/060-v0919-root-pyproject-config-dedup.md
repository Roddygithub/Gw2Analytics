# Plan 060 — v0.9.19: dedupe `ruff` / `mypy` / `pytest` config between root `pyproject.toml` and the canonical files

## Drift base

`44ea862`. Drift cleanup only — additive, no migration.

## Surface

Root `pyproject.toml` (the workspace root),
`ruff.toml` (canonical ruff config),
`mypy.ini` (canonical mypy config),
`pytest.ini` (canonical pytest config).

## Finding (part 1: `[tool.ruff]` dead block in root pyproject.toml)

Root `pyproject.toml` has a `[tool.ruff]` block:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "S", "RUF"]

[tool.ruff.lint.per-file-ignores]
"**/tests/**/*.py" = ["S101", "S105", "S311", "PLR2004", "N801"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

This is **dead config** because:
- The canonical ruff config is `ruff.toml` (at the repo
  root), which has a more comprehensive `select` + `ignore` +
  `per-file-ignores` + `isort.known-first-party`.
- Ruff's config discovery (per the ruff docs §"Config file
  discovery") reads `ruff.toml` if present and ignores
  `[tool.ruff]` in `pyproject.toml` for the SAME config
  keys.
- The two configs are **drifted**: the root `pyproject.toml`
  `select` has 7 categories; the `ruff.toml` has 19. The
  ruff.toml wins. The root's `select` is invisible.

## Finding (part 2: `[tool.mypy]` partial + drifted block in root pyproject.toml)

Root `pyproject.toml` has a `[tool.mypy]` block:

```toml
[tool.mypy]
python_version = "3.12"
strict_optional = true
warn_unused_ignores = true
warn_redundant_casts = true
no_implicit_optional = true
check_untyped_defs = true

[[tool.mypy.overrides]]
module = ["fastapi_mcp"]
ignore_missing_imports = true
```

This is **partial + drifted** because:
- The canonical mypy config is `mypy.ini` at the repo root,
  which has `strict = True` (the umbrella flag that implies
  most of the root's per-flag settings), `disallow_untyped_defs = True`,
  `warn_return_any = True`, `plugins = pydantic.mypy`,
  `exclude = ...`, and the per-module `[mypy-tests.*]` and
  `[mypy-pydantic.*]` overrides.
- Mypy's config discovery (per the mypy docs §"Config
  file") reads BOTH `mypy.ini` AND `[tool.mypy]` in
  `pyproject.toml` and merges them. The merging is
  per-key (the LATER-loaded config wins for the same
  key). The order is implementation-defined; in practice,
  mypy reads `mypy.ini` first then overlays
  `pyproject.toml`'s `[tool.mypy]`.
- The drift: the root's `python_version = "3.12"` (with
  quotes) overrides the `mypy.ini`'s `python_version = 3.12`
  (without quotes). Both are valid mypy syntax, but the
  inconsistency is a smell.
- The root's `[[tool.mypy.overrides]] module = ["fastapi_mcp"]`
  is duplicated by an absent `mypy.ini` override (the
  mypy.ini has no equivalent). The mypy.ini does NOT
  override `fastapi_mcp`; the root does. This means the
  root's block is the canonical source for that one
  override.

## Finding (part 3: `[tool.pytest.ini_options]` + `asyncio_mode` semantic drift)

Root `pyproject.toml` has a `[tool.pytest.ini_options]` block:

```toml
[tool.pytest.ini_options]
asyncio_mode = "strict"
filterwarnings = [
    "ignore::starlette.exceptions.StarletteDeprecationWarning",
]
```

The canonical `pytest.ini` has:

```ini
[pytest]
testpaths = libs apps
pythonpath = .
addopts = --strict-markers --strict-config --tb=short -ra -q
asyncio_mode = auto
filterwarnings =
    ignore::starlette.exceptions.StarletteDeprecationWarning
    ignore::DeprecationWarning
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: tests requiring a live database/redis/minio
```

This is **critical drift** because:
- `asyncio_mode = "strict"` (root) vs `asyncio_mode = auto`
  (pytest.ini) is a **semantic** difference. `auto` means
  pytest auto-applies `@pytest.mark.asyncio` to all `async def`
  test functions. `strict` means the operator must add the
  decorator explicitly. The two configs disagree.
- Pytest's config discovery (per the pytest docs §"Configuration
  file") reads `pytest.ini` first, then overlays
  `[tool.pytest.ini_options]` from `pyproject.toml`. The
  `pytest.ini` wins for the keys it defines; the root's
  `asyncio_mode = "strict"` is silently ignored.
- The canonical behaviour is `asyncio_mode = auto` (per
  `pytest.ini`); the root's `"strict"` is dead config.
- The `filterwarnings` lists also drift: `pytest.ini` has
  TWO `ignore::` lines; the root has ONE. The pytest.ini
  wins (it has more). The root's `filterwarnings` is dead
  config.

## Fix

1. **Remove the 3 dead/partial blocks from root
   `pyproject.toml`**:
   - `[tool.ruff]` and its sub-blocks
     (`[tool.ruff.lint]`, `[tool.ruff.lint.per-file-ignores]`,
     `[tool.ruff.format]`)
   - `[tool.mypy]` and its sub-block
     (`[[tool.mypy.overrides]] module = ["fastapi_mcp"]`)
   - `[tool.pytest.ini_options]`

2. **Move the `fastapi_mcp` ignore-missing-imports override
   to `mypy.ini`** (the canonical config):

   ```ini
   [mypy-fastapi_mcp]
   ignore_missing_imports = True
   ```

3. **Keep `[tool.uv.workspace]`, `[tool.uv.sources]`, and
   `[tool.uv]` in root `pyproject.toml`** — these are the
   uv-specific workspace declarations, not the dead blocks.

4. **Keep `[tool.pytest_env]` in root `pyproject.toml`** —
   pytest-env is configured via the `[tool.pytest_env]`
   block in pyproject.toml, NOT via `pytest.ini`. This is
   the canonical pattern (pytest-env reads the
   pyproject.toml block). Removing it would break the
   test env-var injection.

5. **Add a CI / pre-commit drift detector** that asserts
   the root `pyproject.toml` does NOT contain any of the
   3 dead blocks. The detector is a 20-line Python script
   that parses the file with `tomllib` + checks for the
   presence of `[tool.ruff]`, `[tool.mypy]`,
   `[tool.pytest.ini_options]` keys at the top level.
   The script exits 1 with a clear drift message if any
   are found.

## Why the canonical files (ruff.toml / mypy.ini / pytest.ini) win

- `ruff.toml` has a comprehensive `select` (19 categories)
  + `ignore` + `per-file-ignores` + `isort.known-first-party`.
  It's the canonical source per the ruff docs.
- `mypy.ini` has `strict = True` + `plugins = pydantic.mypy`
  + `exclude` + per-module overrides. It's the canonical
  source per the mypy docs.
- `pytest.ini` has `testpaths` + `addopts` + `asyncio_mode =
  auto` + `markers` + comprehensive `filterwarnings`. It's
  the canonical source per the pytest docs.

The 3 canonical files are MORE comprehensive than the dead
blocks. Removing the dead blocks has zero functional impact
(the canonical files cover everything).

## Risks

- The `mypy.ini` change (add `[mypy-fastapi_mcp]
  ignore_missing_imports = True`) is a new entry. The
  pre-existing root `[tool.mypy.overrides]` block was the
  source of truth for this one override; moving it to
  `mypy.ini` is a 1-time edit.
- A future operator who adds a `[tool.ruff]` block to
  root `pyproject.toml` thinking it's the canonical
  place (e.g., a StackOverflow answer) will see the
  drift detector fail. The detector's clear error
  message ("ruff config lives in ruff.toml") will
  redirect them.
- The CI drift detector adds a new CI step (~1s
  overhead). The pre-commit hook integration is
  optional (per the existing pre-commit mypy hook
  pattern, a Python script with `language: system`
  + `entry: python -m`).

## Tests

1. `test_root_pyproject_has_no_tool_ruff_block` — parse
   root `pyproject.toml`; assert no `[tool.ruff]`,
   `[tool.ruff.lint]`, `[tool.ruff.lint.per-file-ignores]`,
   `[tool.ruff.format]` keys are present.
2. `test_root_pyproject_has_no_tool_mypy_block` — parse
   root `pyproject.toml`; assert no `[tool.mypy]` or
   `[[tool.mypy.overrides]]` keys are present.
3. `test_root_pyproject_has_no_pytest_ini_options_block` —
   parse root `pyproject.toml`; assert no
   `[tool.pytest.ini_options]` key is present.
4. `test_mypy_ini_has_fastapi_mcp_override` — parse
   `mypy.ini`; assert `[mypy-fastapi_mcp]` section with
   `ignore_missing_imports = True` is present.
5. `test_pytest_asyncio_mode_is_auto` — read `pytest.ini`;
   assert `asyncio_mode = auto` (not `strict`).
6. `test_pytest_filterwarnings_has_two_lines` — read
   `pytest.ini`; assert the `filterwarnings` block has
   2 lines (`StarletteDeprecationWarning` +
   `DeprecationWarning`).
7. `test_drift_detector_exits_1_on_drift` — write a
   fake `pyproject.toml` with a `[tool.ruff]` block;
   run the drift detector; assert exit code 1.
8. `test_drift_detector_exits_0_on_clean` — read the
   canonical `pyproject.toml`; run the drift detector;
   assert exit code 0.

## Rejected alternatives

- **Keep the root blocks but mark them as "legacy / do
  not use" with a comment**: tempting (preserves history).
  The dead config is still parsed by tools that don't know
  to skip it (e.g., a future IDE that merges both configs).
  Removal is the canonical fix.
- **Move the canonical config INTO root `pyproject.toml`**
  (delete `ruff.toml` / `mypy.ini` / `pytest.ini`):
  tempting (single source of truth). The canonical files
  exist for a reason: `pytest.ini` and `mypy.ini` are the
  pytest/mypy-native config paths (per their docs), and
  the pre-commit `mypy` local hook is a self-contained
  unit that reads `mypy.ini` directly. Centralizing in
  `pyproject.toml` is a future refactor; the v0.9.19
  minimum is to remove the dead blocks.
- **Add a `pre-commit` hook for the drift detector**:
  the detector runs in CI (the canonical "drift gate"
  pattern). A pre-commit hook adds local-rerun overhead
  for a 1-second script; the CI-only placement is
  sufficient.
- **Use `ruff check --no-cache --config ruff.toml` to
  detect the dead blocks**: out of scope. The dead
  blocks are at the TOML level (before ruff even reads
  them); the drift detector parses `pyproject.toml`
  with `tomllib` and checks for the keys.
