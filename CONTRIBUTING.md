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

Until the spending-limit unblock lands (tracked as an open item
in `docs/ROADMAP.md` §3 "Strategic items (v1.0+)"), the CI
workflow at `.github/workflows/ci.yml` is **not** triggered by
``push`` or ``pull_request`` events -- its only trigger is
``workflow_dispatch``, which means CI must be invoked manually via
the Actions tab or ``gh workflow run ci.yml --ref main`` for the
6 jobs (``lint-python``, ``test-python``, ``lint-web``,
``playwright-chromium``, ``playwright-visual-regression``,
``arq-integration``) to execute. The "Required status checks" row
below should be filled in once the auto-trigger is restored; until
then, leave it empty (or pick ``None`` in the ruleset UI) so PRs
aren't blocked by an absent gate.

## Pre-commit / CI mirror

The same checks run locally via `pre-commit` and remotely on every push
and PR via GitHub Actions:

| Gate                   | pre-commit | ci.yml       |
|------------------------|------------|--------------|
| trim trailing whitespace | ✅         | (auto-cached) |
| ruff check             | ✅         | ✅            |
| ruff format            | ✅         | ✅            |
| mypy (`--strict`)      | ✅         | ✅            |
| pytest                 | (manual)   | (n/a -- CI is dispatch-only) |

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

This project is **proprietary software, all rights reserved** --
see [`LICENSE`](./LICENSE) and [`NOTICE.md`](./NOTICE.md) at the
repo root for the full legal text + a plain-language summary of
what is and isn't permitted.

### What "contributing" means under an All Rights Reserved license

Unlike MIT/Apache/GPL projects, this codebase does **not** accept
outside contributions under a pre-existing open-source contribution
agreement. Instead, the project operates on a **Developer Certificate
of Origin (DCO) model** that mirrors the Linux kernel's:

1. **You retain copyright** in any contribution you submit. Submitting
   a Pull Request does not transfer your rights to the copyright
   holder.
2. **You certify** that the contribution is your original work (or
   you have authority to submit it under these terms) by appending a
   ``Signed-off-by:`` line to every commit message. The line must use
   your real name + a reachable email address. Example:

   ```text
   feat(parsers): handle new buff ID range

   Signed-off-by: Jane Contributor <jane@example.com>
   ```

3. **You grant an irrevocable, perpetual, worldwide, sublicensable
   license** to the copyright holder to use, modify, sublicense,
   and redistribute the contribution under the project's proprietary
   ``LICENSE``, including the right to incorporate it into derivative
   works. This lets the copyright holder ship your contribution
   without asking for further paperwork, while you retain authorship
   credit + the right to use the same code in other projects of your
   own.

4. **You waive moral rights to the maximum extent permitted by
   applicable law.** Many jurisdictions (France under CPI Article
   L121-1, the rest of the EU, and several non-EU copyright regimes)
   recognize *moral rights* (*droit moral*) that are distinct from
   economic copyright: the right of attribution (paternité -- to be
   credited as author), the right of integrity (to object to
   modifications that harm the author's reputation), the right of
   withdrawal / modification (to stop or modify distribution under
   certain conditions), **and** the right of respect of name,
   quality, and the work itself (L121-1: *"droit au respect de son
   nom, de sa qualité et de son œuvre"*). These rights are
   inalienable but waivable. By signing off on a contribution, you
   waive them **to the maximum extent permitted by applicable law**
   so the copyright holder can ship derivative works without
   renegotiating attribution waivers per change.

5. **CI / branch protection may enforce the DCO sign-off** before a
   PR can merge. Maintainers may also reject a contribution for any
   other reason (style mismatch, doesn't fit the project direction,
   etc.) without obligation to incorporate it.

### How to set up DCO sign-off locally

```bash
# Tell git your real name + reachable email (used for Sign-off-by):
git config user.name "Jane Contributor"
git config user.email "jane@example.com"

# Always use ``git commit -s`` (or ``--signoff``) so the
# ``Signed-off-by:`` trailer is appended automatically.
git commit -s -m "feat(parsers): handle new buff ID range"
```

DCO ``Signed-off-by:`` trailers are checked by GitHub's native
``Require contributors to sign off on web-based commits`` branch
protection (recommended in the ruleset below). They are also
verifiable by any interested party from the git history itself
without a separate CLA database.

## Historical: private-mode unblock appendix

This section is kept for the case where the repo is ever
re-flipped from **public** back to **private** on a free GitHub
plan and the spending-limit block returns. As of v0.15.2 the
repo is public; the canonical reference for the 3 historical
private-mode workarounds is commit ``8a1bfe4``.

### Public-flip cheatsheet (what is about to happen)

**⚠ Critical: do steps 1-4 BEFORE the visibility flip in step 5.**
The 4 hardcoded ``SECRETS_KEK: "YWFhYWFh..."`` env entries in
``.github/workflows/ci.yml`` must be swapped for ``${{ secrets.SECRETS_KEK }}``
+ a real repo secret **before** re-enabling the ``push:`` trigger
— otherwise the deterministic ``aaaa...`` test fixture lands in
the public CI log on the first push, which is ugly first-impression
hygiene.

```bash
# Step 1 — sanity-check license / metadata / file consistency.
#    (no phantom-suffix text should be in tracked files)
git log --oneline origin/main -10
gh api repos/:owner/:repo/license   # expect "Other (Proprietary -- All rights reserved)"
grep -nE 'PlaceholderEnd|Old1End|Old2End|DeferredInTextComment|DepartureComment' \
    apps/api/pyproject.toml libs/gw2_analytics/pyproject.toml \
    pyproject.toml CONTRIBUTING.md      # expect NO output

# Step 2 — locate the hardcoded test KEK literals that step 4 will replace.
grep -nE 'SECRETS_KEK.*YWFh' .github/workflows/ci.yml
#   Expect 4 matches (one per job env: dict in lint-python, test-python,
#   lint-web, arq-integration).

# Step 3 — set the SECRETS_KEK repo secret FIRST so step 4 env refs
#    resolve on the first push. Generate a fresh Fernet key + store it.
gh secret set SECRETS_KEK \
    --body "$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
#   PASTE THE OUTPUT into your local .env file too. This is the SOLE
#   key for ALL webhook-subscription ciphertexts — if lost, all rows
#   become unreadable per the v0.10.0 plan 031 KEK flow.

# Step 4 — edit .github/workflows/ci.yml:
#    a) replace the 4 hardcoded ``SECRETS_KEK: "YWFhYWFhYWFh..."`` entries
#       with ``SECRETS_KEK: ${{ secrets.SECRETS_KEK }}``
#    b) under the ``on:`` block, replace ``workflow_dispatch:`` with:
#         push:
#           branches: [main]
#         pull_request:
#           branches: [main]
#         workflow_dispatch:

# Step 5 — flip the visibility NOW (push triggers are back, secret is set,
#    but they cannot fire while the repo is private on the spending-limit
#    cap). The flip is the moment CI is unblocked:
gh repo edit --visibility public --accept-visibility-change-consequences

# Step 6 — configure git sign-off locally (LOCAL repo config matches
#    the DCO setup section at the top of this file). MUST run before
#    step 7, otherwise ``git commit -s`` fails with "Please tell me
#    who you are" on a fresh clone / CI runner.
git config user.name "Your Name"
git config user.email "your-real-email@example.com"

# Step 7 — verify CI runs end-to-end with the secret resolved, BEFORE
#    applying the ruleset in step 8, so any CI failures surface without
#    the ruleset in the way (iteration is cheaper). Uses ``git commit -s``
#    (the **-s** flag) so git itself appends the ``Signed-off-by:``
#    trailer from the ``user.name`` + ``user.email`` configured in
#    step 6 — the canonical DCO-compatible commit pattern (avoids
#    hand-typed trailers that bash word-splits on the embedded
#    newline) and matches the ``-s`` pattern documented at the top
#    of this file.
git commit --allow-empty -s -m "ci: smoke-test SECRETS_KEK secret resolution + 6-job public pipeline"
git push origin main
#   All 6 jobs should now run on every push + PR, with SECRETS_KEK
#   resolved from the repo secret (no ``YWFh...`` literal in the log).

# Step 8 — apply the branch-protection ruleset via the GitHub web UI:
#    Settings → Rules → Rulesets → New branch ruleset, target = main.
#    Enable these rules:
#      - Require linear history (no merge commits)
#      - Block force pushes (admin included)
#      - Block branch deletion
#      - Require status checks: pick the CI workflow's 6 jobs
#      - **Require contributors to sign off on web-based commits**  ← the
#        GitHub-native DCO check for web-editor commits; pairs with
#        the dco-action step below to make DCO enforceable for ALL
#        commits (web + CLI / IDE), not just web-editor ones
#
#    **⚠ Caveat — the GitHub web-DCO toggle only covers commits
#    authored via github.com's web editor.** For CLI / IDE commits
#    (``git commit -s`` from outside the github.com editor), also
#    wire a dedicated DCO check into ``.github/workflows/ci.yml``
#    as a required status check. The maintained actions are
#    ``crazy-max/ghaction-dco@v1`` or the older
#    ``suzuki-shunsuke/dco-action@v1``; either approach makes the
#    DCO model enforceable for ALL commits, not just web-editor
#    ones. Without this extra check, CLI-signed PRs slip through
#    the web-DCO gate and ``-s`` sign-off becomes decorative again.
#
#    (The ``gh ruleset`` CLI to apply rulesets programmatically is a
#    GitHub-Enterprise feature; on the free plan the UI is the only
#    path. The legacy ``gh api .../branches/main/protection`` PATCH
#    endpoint works on free plans for the classic branch-protection
#    fields — ``required_status_checks`` / ``enforce_admins`` /
#    ``required_pull_request_reviews`` / ``required_signatures`` /
#    ``linear_history`` — but not for the new Rulesets UI.)

# (Step 6b git-config block was moved up + renamed Step 6 to
#  document the right execution order: git config MUST precede
#  step 7's smoke-test commit; the ``--global`` flag was dropped
#  in favour of LOCAL repo config to match the DCO setup section
#  earlier in this file.)
```

### If the repo flips back to private + the billing block returns

1. Add a paid plan (Settings → Billing and plans).
2. Set the spending limit > 0 (Settings → Billing → Plans and budget).
3. Configure a self-hosted runner on a free cloud VM (e.g. Oracle
   Cloud Always Free tier) -- the advisor plan stub
   ``advisor-plans/011-nextjs-headers-fallback.md`` carries the
   legacy reasoning in case it is useful when picking the
   runner host.

The right "go-forward" answer is to keep the repo **public**
(unlimited free GitHub Actions minutes) and only re-flip to
private if there's a confidentiality reason strong enough to
justify the billing work. The license stance in ``LICENSE``
(All Rights Reserved) does **not** require private visibility
to remain effective against idea theft.
