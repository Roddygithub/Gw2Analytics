# Contributing to GW2Analytics

Welcome! This document covers the day-to-day workflow for anyone
contributing to the GW2Analytics monorepo (``libs/gw2_core``,
``libs/gw2_evtc_parser``, ``libs/gw2_analytics``, ``libs/gw2_api_client``,
``apps/api``, ``web``).

## Local development setup

```bash
# 1. Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Sync all monorepo deps (libs + apps + dev)
uv sync

# 3. Install git hooks (pre-commit + pre-push)
uv run pre-commit install --hook-type pre-commit --hook-type pre-push

# 4. Bring up the infrastructure for end-to-end tests
docker compose up -d

# 5. Configure local app env (operator-side .env file)
cp .env.example .env
```

## Architecture reminders

- `libs/gw2_core` is the **single source of truth** for data shapes.
  Everything depends on it; it depends on nothing but Pydantic.
- The parser is replaceable behind the `EvtcParser` Protocol. We currently
  ship a pure-Python implementation (`PythonEvtcParser`); a Rust + PyO3
  binding is anticipated but not in scope for the current slice.
- The frontend never knows about EVTC internals, the parser, or the
  database schema -- only the OpenAPI surface from `apps/api`.
- Each component evolves independently (`pyproject.toml` per lib/app).

## Commit conventions

We follow [Conventional Commits](https://www.conventionalcommits.org/).

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

| Type       | When                                                |
|------------|-----------------------------------------------------|
| `feat`     | New feature visible to users                        |
| `fix`      | Bug fix                                             |
| `refactor` | Code change that neither fixes nor adds             |
| `perf`     | Performance improvement                             |
| `test`     | Adding or fixing tests                              |
| `docs`     | Documentation only                                  |
| `chore`    | Tooling, dependencies, build config                 |
| `ci`       | CI configuration only                               |
| `revert`   | Revert a previous commit                            |

### Scopes

Common: `parser`, `analytics`, `api`, `web`, `core`, `hooks`, `ci`,
`infra`, `deps`, `readme`, `pyproject`, `gitignore`.

### Subject line

- Imperative mood ("Add X", not "Added X").
- No trailing period.
- ≤72 characters; wrap the detail in the body.

### Body

- Wrap at 100 characters (matches `line-length = 100` in `pyproject.toml`).
- Explain *what* and *why*, not *how* (the diff shows the how).

### Breaking changes

We ship **both** for tooling redundancy:

1. **`!` after type/scope.** e.g. `feat(api)!: ...`
2. **`BREAKING CHANGE:` footer** explaining the migration.

Either signal alone satisfies CC v1.0.0 §8; using both keeps
changelog generators / commit parsers consistent.

Example:

```
feat(api)!: require credentials via env vars (S3_* and DATABASE_URL)

Operators must now set DATABASE_URL + S3_* env vars before running
uvicorn. The previous sentinel defaults have been removed; pytest-env
injects dev credentials at test time via [tool.pytest_env] in
pyproject.toml.

BREAKING CHANGE: callers previously relying on the hardcoded
localhost defaults will see a fail-fast ValueError on app startup
until they configure .env via `cp .env.example .env`.
```

## Branch protection for ``main``

Recommended GitHub repository ruleset (Settings → Rules →
Rulesets → New branch ruleset):

| Setting                                          | Value                                |
|--------------------------------------------------|--------------------------------------|
| Target branches                                  | `main` only                          |
| Restrict creations                               | Enable (only via PR)                 |
| Restrict updates                                 | Enable (PR or admin bypass only)     |
| Required status checks                           | `lint-and-test` (CI workflow)        |
| Require linear history                           | Yes (no merge commits)               |
| Require deployments before merging               | No (no deploys from `main` directly) |
| Block force pushes                               | **Yes** (admin included)             |
| Block branch deletion                            | **Yes**                              |

The `lint-and-test` job from `.github/workflows/ci.yml` is the single
gate; it runs `ruff check`, `ruff format --check`, `mypy`
(`--no-incremental`), and `pytest` (full suite).

## Pre-commit / CI mirror

The same checks run locally via `pre-commit` and remotely on every push
and PR via GitHub Actions:

| Gate                   | pre-commit | ci.yml       |
|------------------------|------------|--------------|
| trim trailing whitespace | ✅         | (auto-cached) |
| ruff check             | ✅         | ✅            |
| ruff format            | ✅         | ✅            |
| mypy (`--strict`)      | ✅         | ✅            |
| pytest                 | (manual)   | ✅            |

Run them yourself before pushing:

```bash
uv run ruff check
uv run ruff format --check
uv run mypy libs apps --no-incremental
uv run pytest --tb=short
```

The pytest-suite runs against synthetic fixtures constructed in-memory;
the Postgres-dependent `test_uploads_e2e.py` self-skips via the
`db_reachable` fixture when the docker-compose database isn't running
on the runner.

## Test requirements

- Every PR must include or update tests covering the change.
- Cross-field invariants on pydantic models need at least one
  explicit test (don't rely on indirect assertions across multiple
  test cases).
- Lenient-parser edge cases (empty / null / unprefixed inputs)
  must be locked down at unit-test level. Real-fixture integration
  tests are not a substitute for unit coverage of a parser quirk.
- Reuse existing `_build_*_record` helpers in test files whenever
  available. Don't reinvent fixture assembly in a new test.

## Pull request workflow

1. Branch off `main`.
2. Make atomic commits (one logical change per commit).
3. Push and open a PR.
4. `lint-and-test` must pass before review.
5. Squash-merge once approved -- linear history.

When pushing, ``pre-commit`` runs trim-trailing-whitespace, ruff, and
the formatter for any file in the index. If it auto-fixes something,
add the fix to the **same commit** (not a follow-up) to keep each commit
self-contained.

## Tagging

We use **semver with a scope suffix**:

- ``v0.X.Y-parser``            -- Phase 1 deliverables (parser only)
- ``v0.X.Y-analytics-prototype`` -- Phase 3 prototype builds
- ``vX.Y.Z-web``               -- web/ component releases (frontend
  only, e.g. ``v0.3.0-web`` shipped the upload UI in isolation)
- ``vX.Y.Z``                   -- full-stack releases (CI green +
  deployable). The ``apps/api`` + ``libs/*`` backend renders here.

Tags are created locally with ``git tag -a`` and pushed with
``git push origin <tag>``. Release notes are then published via
``gh release create <tag> --notes-file <path> --target main``.### Known cosmetic noise

``pnpm install`` may emit ``[ERR_PNPM_IGNORED_BUILDS]`` warnings
for ``sharp`` and ``esbuild`` even though we now set
``dangerouslyAllowAllBuilds=true`` in ``web/.npmrc``. pnpm's
success-with-warning contract keeps the install exit code at
``0`` (vitest + Next.js optimize work fine via the JS-only
fallback for esbuild, and ``sharp`` has a prebuilt-binary
download path that does not require a postinstall script).

- **Local first install:** run ``pnpm approve-builds --all``
  once if you want per-dep approval; pnpm writes the entry to
  the user-level ``~/.npmrc``. Not required.
- **CI:** the ``.github/workflows/ci.yml::lint-and-test`` step
  uses ``pnpm install --frozen-lockfile`` directly; the
  ``dangerouslyAllowAllBuilds`` flag in ``web/.npmrc``
  guarantees the install gate returns ``0`` on a fresh
  container (no user-level cache). If a future pnpm version
  starts returning non-zero again, add ``--ignore-scripts`` to
  the install invocation -- verify ``next build`` image
  optimisation still picks up ``sharp``'s prebuilt binary
  before flipping.
- The ``verify-deps-before-run: false`` flag in
  ``web/pnpm-workspace.yaml`` only affects ``pnpm run`` /
  ``pnpm dev``; it does **not** suppress the install-time
  verification gate.

## Code style

- `ruff format` (already auto-applied by the formatter hook).
- Type hints mandatory on every public function/method. Use
  `from __future__ import annotations` at the top of each module.
- Imports ordered by `ruff` (`I` rule).
- No bare `except:` -- catch specific exception types.
- One public class per module minimum (avoid "dump modules").
- Models use `frozen=True` and `extra="forbid"` for stability.

## License

By contributing you agree to MIT-license your contributions under the
terms of the LICENSE file.
