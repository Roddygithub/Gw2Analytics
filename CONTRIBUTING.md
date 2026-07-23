# Contributing to GW2Analytics

Welcome! This document covers the day-to-day workflow for anyone
contributing to the GW2Analytics monorepo (``libs/gw2_core``,
``libs/gw2_evtc_parser``, ``libs/gw2_analytics``, ``libs/gw2_api_client``,
``apps/api``, ``web``).

## Local development setup

The fastest path is the one-shot developer-onboarding target, which
checks your tools, bootstraps `.env`, brings up the infrastructure
with a per-service health-wait, syncs all monorepo deps (Python +
Node), applies Alembic migrations, and regenerates the OpenAPI
TypeScript client -- all in one command:

```bash
make dev-onboard
```

Equivalent manual steps (only use these if you don't have GNU Make or
prefer fine-grained control):

```bash
# 1. Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Configure local app env (operator-side .env file)
cp .env.example .env

# 3. Bring up the infrastructure for end-to-end tests
docker compose up -d

# 4. Sync all monorepo deps (libs + apps + dev) and apply migrations
uv sync
uv run --directory apps/api alembic upgrade head

# 5. Install web deps (frozen lockfile) and regenerate the OpenAPI client
(cd web && pnpm install --frozen-lockfile && pnpm generate:api)

# 6. Install git hooks (pre-commit + pre-push)
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

The ordering differs from the historical manual list because
`alembic upgrade head` needs the running Postgres **plus** the
`uv`-synced Python env (alembic is installed via `uv sync`), and
`pnpm generate:api` needs the `web/` deps present. `make dev-onboard`
sequences these explicitly; the manual list above mirrors that order.

### Rolling back

If `make dev-onboard` turns out to be too aggressive for your local
workflow (e.g. you only need the Postgres driver, not MinIO), revert
**all** of the dev-onboard commits — not just the most recent one.
The SHA list is self-locating and the loop handles 1+ commits
transparently:

```bash
# Revert every commit whose subject line contains `dev-onboard` and
# that touched `Makefile`, newest first. Capped at 5 to prevent runaway
# loops on a corrupted history:
for _ in 1 2 3 4 5; do
  sha=$(git log --oneline --grep='dev-onboard' Makefile | head -1 | cut -d' ' -f1)
  [ -z "$sha" ] && break
  git revert --no-edit "$sha" \
    || { echo >&2 "conflict on $sha — resolve manually, then continue the loop"; break; }
done
```

After the cascade-squash followup lands, every dev-onboard touch
collapses into ONE combined commit whose subject line typically does
**not** contain `\u2018dev-onboard\u2019` (the new subject is whatever you
chose for the merged commit, e.g. `\u2018ci: green-up cumulative suite\u2019`).
In that state, the loop above returns without reverting anything —
fall back to reverting the most-recent Makefile commit:

```bash
# Post-cascade-squash fallback: pick the most-recent commit touching Makefile
# (which contains the merged dev-onboard changes among everything else):
git revert --no-edit $(git log --oneline -1 Makefile | cut -d' ' -f1)
```

If neither variant reverts what you expected, run `git log --oneline
Makefile` manually to see the history directly. The revert is safe to
discard later (`git revert --abort` or drop the follow-up commit
before pushing); the underlying behaviour (the manual 5-step setup
above) is unchanged.

### Why a portable POSIX-loop instead of `timeout`

The 60s health-wait per Docker service is implemented as a pure
POSIX `date +%s`-arithmetic loop (`start=$$(date +%s); until <probe>;
do [ $$(($$(date +%s) - start)) -ge 60 ] && exit 1; sleep 2; done`).
It does **not** call GNU `timeout` — GNU `timeout` is not on stock
macOS (requires `brew install coreutils` + a `gtimeout` alias). This
keeps the target usable on a fresh macOS checkout with zero extra
dependencies, at the cost of two extra shell invocations per iteration
(`date +%s` once per loop).

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

## Visual regression

The `web/tests/e2e/visual-regression.spec.ts` spec pixel-diffs
the 8 tracked PNGs at `docs/screenshots/` against fresh full-page
captures of the corresponding routes (shipped in v0.8.9
plan/003). The CI gate is **PR-only** ("Visual regression e2e
(PR only)" step in `.github/workflows/ci.yml`); pushes to `main`
don't pay the ~2-4 s of browser time.

### When to refresh the baselines

Refresh the 8 PNGs at `docs/screenshots/` whenever an intentional
UI change would otherwise fail the diff (e.g. a new colour on the
landing page, a layout shift on `/fights`, a re-rendered AG Grid
column, a new SVG asset on the player timeline). The procedure:

```bash
# 1. From web/, start the mock server (port 8080) + Next dev
#    server (port 3000). The pnpm dev script auto-regenerates
#    the OpenAPI client first.
(cd web && pnpm dev)

# 2. In another terminal, refresh + persist the baselines:
(cd web && pnpm screenshots --persist)
# This writes 8 PNGs to screenshots/ at the repo root
# (gitignored) AND mirrors them into docs/screenshots/
# (tracked) via the --persist flag.

# 3. Visually skim the 8 PNGs to confirm the change is
#    intentional + looks correct (open them in your image
#    viewer). Then commit them:
git add docs/screenshots/*.png
git commit -m "test(e2e): refresh 6 stale visual-regression baselines"
```

### Threshold rationale

Two tunable values, both in `web/tests/e2e/visual-regression.spec.ts`:

| Constant                      | Value  | Meaning                                                |
|-------------------------------|--------|--------------------------------------------------------|
| `DIFF_THRESHOLD`              | `0.01` | Total diff budget (1% of total pixel count).           |
| `pixelmatch({ threshold })`   | `0.05` | Per-pixel color-difference tolerance (anti-aliasing).   |

The 0.05 per-pixel tolerance was chosen empirically as the
strictest value that still passes 8/8 against the committed
baselines. A lower value (e.g. 0.02) would catch finer
font-rendering drift at the cost of more false-positive CI
failures from sub-pixel anti-aliasing differences between the
baseline capture host + the spec capture host. A higher value
(e.g. 0.1, pixelmatch's default) tolerates more drift but masks
smaller intentional UI changes. See the spec's "Maintenance
note" docstring for the full discussion.

### Debugging a failure

When the spec fails:

1. The Playwright report logs the diff ratio + diff pixel count
   for each case, e.g. `landing differs from 01-landing.png by
   1.34% (threshold: 1.00%, 17,356 of 1,296,000 pixels)`.
2. A diff PNG (a red highlight overlay on the changed pixels)
   is written to `web/tests/e2e/.visual-regression-output/<baseline>`
   (gitignored). The path is included in the failure message
   for direct access from the CI logs.
3. On CI, the same dir is uploaded as the
   `visual-regression-diffs` artifact (7-day retention; gated on
   `failure() && github.event_name == 'pull_request'`). Download
   it from the Actions run page → Artifacts section.
4. Compare the diff PNG to the committed baseline side-by-side
   to confirm whether the change is intentional (refresh
   baselines) or a regression (revert the offending commit).

If a diff > 0% surfaces on a **non-PR** run (i.e. locally
without changing any UI code), the most likely cause is
font-rendering drift between the capture host + the spec host.
Run `pnpm screenshots --persist` to re-baseline from the same
host the spec runs on, then commit the updated PNGs.

## Regenerating the web TypeScript client

`web/src/lib/api/schema.d.ts` is the TypeScript contract the
web tier consumes from the backend's FastAPI `app.openapi()`
schema. Per v0.9.1 plan 008, the file is committed (un-gitignored)
and the CI `Detect API client drift` step
(`git diff --exit-code -- web/src/lib/api/schema.d.ts`) fails any
PR where the regenerated client differs from the committed
baseline.

**When to regenerate:** any backend PR that touches
`apps/api/src/gw2analytics_api/routes/*` -- a new endpoint, a
renamed parameter, an added/changed response field, a changed
response shape -- MUST regenerate the schema and commit it in
the same PR.

**How:**

```bash
# From web/ (runs `uv run python scripts/dump_openapi.py` then
# `pnpm exec openapi-typescript` then cleans up openapi.json):
cd web && pnpm generate:api
```

Then `git add web/src/lib/api/schema.d.ts` and commit the
regenerated file alongside the backend change. If a PR slips
through with a stale schema, the CI drift gate will fail on
the next CI run (after the gate starts working).

The intermediate `openapi.json` is gitignored and removed
automatically by the `generate:api` script chain. Only the
final `web/src/lib/api/schema.d.ts` ships.

## Webhook discriminator IDs

`apps/api/src/gw2analytics_api/routes/webhooks.py` defines 3
discriminator generators: `_generate_subscription_id`,
`_generate_secret`, `_generate_delivery_id`. The encoding
convention (per v0.9.2 plan 009 Step 4) is:

- **Path-parameter discriminators** (`/webhooks/{id}`): use
  `base64.urlsafe_b64encode` -- standard `b64encode` emits
  `/` and `+` which break FastAPI path-param matching.
- **Byte-only discriminators** (HMAC secrets, never in a URL
  path): use standard `base64.b64encode` -- HMAC operates on
  bytes and format churn has migration cost for in-flight
  integrators.
- **UUID-based discriminators** (`_generate_delivery_id`):
  URL-safe by definition; no encoding needed.

When adding a new discriminator, classify it by where it
appears in the wire contract (path-param vs payload-only) and
pick the matching encoding. The 3 helper docstrings in
`routes/webhooks.py` mirror this rule for IDE-hover
discoverability.

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
