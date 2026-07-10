# v0.10.5 — 5 HIGH-RISK dependabot PRs requiring manual review (Followup 3)

## Context

Following the v0.10.5 dep-cycle CI recovery (planning documents
`0047-…` through `0098-…`), 15 dependabot PRs were open on
origin/main. Phase 2 of the recovery auto-merges the 10 SAFE
PRs (CI-clearing patch/minor/floating-min bumps). The 5 remaining
PRs (#7, #9, #10, #11, #13) are major-version bumps with
potentially-breaking API/behavior changes that require MANUAL
REVIEW before merging.

This plan documents the breaking-change summary, local-impact
assessment, and manual-review checklist for each of the 5
HIGH-RISK PRs. It serves as the go/no-go checklist for the
reviewer(s) before merging.

## The 5 HIGH-RISK PRs

### PR #7 — `jsdom 25.0.1 → 29.1.1` (npm major)

**Breaking changes (per upstream release notes)**:
- v26: `ResourceLoader` API renamed/removed; `Window` instance no
  longer scoped per-instance by default; `JSDOM.fromURL`
  returns a promise in async mode only.
- v27: drops Node 18 support (irrelevant; we run Node 20+ in CI).
- v28: `atob`/`btoa` polyfills REMOVED in favor of platform-native
  (Node 20+ has both natively → no impact for our setup).
- v29: `Reconfigure` API renamed to `Reconfigure`. Vitest 1.x
  compatibility; vitest 2.x dropped jsdom env default — verify
  our `vitest.config.ts` still resolves.

**Local impact**:
- web's vitest unit test suite uses jsdom via `tests/setup.ts`
  (vitest.config.ts likely configures it). Test environment
  isolation in CI.
- No production-code dependency on jsdom (it's only used by
  vitest for component testing).

**Review checklist**:
- [ ] Run `pnpm install --frozen-lockfile=false` to surface
  pnpm-lock.yaml changes; review diff (lines added/removed).
- [ ] Run `pnpm exec vitest run --reporter=verbose` locally;
  confirm 100% test pass.
- [ ] Run `pnpm exec playwright test`; confirm Playwright
  Chromium tests pass (Playwright uses its OWN bundled Chromium,
  not jsdom — should be unrelated).
- [ ] Check `web/vitest.config.ts` and `web/tests/setup.ts`
  for jsdom-env configuration; verify still resolves.

### PR #9 — `ag-grid-react 34.3.1 → 36.0.0` (npm major)

**Breaking changes**:
- v35: React 19 compatibility (we have React 19.2.4 — fine).
- v35: drop legacy `gridOptions.columnApi` API.
- v36: removed `infiniteRowModel`; replaced by `infiniteScrollRowModel`.
- v36: ag-grid theme system changed — `ag-theme-alpine` is now
  `ag-theme-quartz` (CSS class names changed).

**Local impact**:
- web/ uses ag-grid-react in `web/src/components/` for
  combat-log tables (referenced in main fights view).
- Theme CSS imports in `web/src/app/globals.css` or
  `web/src/styles/`.

**Review checklist**:
- [ ] Run `pnpm exec tsc --noEmit` after merge; flag any
  `infiniteRowModel`-related TS errors.
- [ ] Check `web/src/components/` for `infiniteRowModel` /
  `columnApi` usages; rename to new APIs.
- [ ] Update CSS class from `ag-theme-alpine` to
  `ag-theme-quartz` in theme files.
- [ ] Visual regression: re-run `pnpm exec playwright test
  --project=visual-regression` to confirm no pixel drift.
- [ ] Verify `web/package.json` peerDeps still satisfied (the
  web React 19 + ag-grid-react 36 combination).

### PR #10 — `redis 5.3.1 → 8.0.1` (python major)

**Breaking changes**:
- v6: `decode_responses` kwarg renamed to `decode_responses=True`
  (unchanged in v8 but flagged in v6 release notes).
- v7: `Redis.client()` returns new client class (`AbstractRedis`
  → `Redis` wrapper change).
- v8: removed `redis.cluster.RedisCluster.deprecated_old_api`
  arg; cluster `pipeline()` strict mode is now default.

**Local impact**:
- Used in `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py`
  (per recent file reads) — sends/receives pub/sub messages
  for webhook delivery.
- arq worker (background queue) also uses redis 5.x as the
  broker.

**Review checklist (CRITICAL — CI does NOT have a live Redis service)**:
- [ ] Run webhook_scheduler smoke tests with live redis locally
  (`docker compose up -d gw2-redis` then `uv run pytest
  apps/api/tests/test_webhooks_e2e_scheduler.py`).
- [ ] Verify `Redis.from_url(s3_endpoint_url)` call site still
  resolves in v8 (Redis constructor signature changed).
- [ ] Check `decode_responses=True` flag behavior unchanged.
- [ ] Run arq worker locally against the live redis container;
  verify ScheduledJob execution + queue dispatch.

### PR #11 — `ag-grid-community 34.3.1 → 36.0.0` (npm major)

**Breaking changes (overlap with PR #9 — community-core)**:
- v35/v36: `infiniteRowModel` removed; CSS theme rename
  `alpine → quartz`; React 19 compat.
- v35: removed deprecated `colDef.headerComponent` in favor of
  `headerComponentParams` shape.

**Local impact**:
- Companion to PR #9 (ag-grid-react). Same files affected.

**Review checklist**: See PR #9 (joint review).

### PR #13 — `@types/node 20.19.43 → 26.1.1` (npm major)

**Breaking changes**:
- Major version jumps typically align with the underlying Node.js
  version. `@types/node 20.x` ← Used for `node:process`,
  `node:fs`, `node:http`, etc.
- v22: `process.features` becomes authoritative; `globals`
  surface changes.
- v24: removes `global.gc()` (use `--expose-gc` flag instead).
- v26: aligns to Node 26 LTS. New `node:sqlite` types added.

**Local impact**:
- web/ uses `@types/node` for build scripts, tooling (Next.js
  build path uses Node API).
- apps/api may have indirect dependency if any web code is
  imported into API tests.

**Review checklist**:
- [ ] Run `pnpm install --frozen-lockfile=false`; review pnpm
  diff.
- [ ] Run `pnpm build` (next build) locally; flag any TypeScript
  errors involving node types.
- [ ] Run `pnpm exec tsc --noEmit`; verify clean.
- [ ] Check `web/package.json` — `@types/node` is a `devDependency`
  so only build-time impact (not production bundle).

## Summary

| PR | Package | Bump | Risk level | Blocker |
| --- | --- | --- | --- | --- |
| #7 | jsdom | 25→29 (major) | MEDIUM (vitest isolation) | local vitest run |
| #9 | ag-grid-react | 34→36 (major) | HIGH (UI changes) | pixel-diff + theme rename |
| #10 | redis | 5→8 (major) | **CRITICAL** (no CI smoke coverage) | local redis smoke |
| #11 | ag-grid-community | 34→36 (major) | HIGH (joint with #9) | joint review with #9 |
| #13 | @types/node | 20→26 (major) | LOW (build-time only) | next build + tsc |

## Why NOT auto-merge

The Phase 1 CI recovery completes the green-baseline contract for
the 10 SAFE PRs (no breaking API changes, CI re-runs cleanly). For
the 5 HIGH-RISK PRs above:

1. **REDIS MAJOR (#10)** is FLAGGED CRITICAL because real Redis
   failures (commercial multi-tenant SaaS behavior changes,
   cluster-mode breaking changes in v7/v8) won't be caught by
   `ruff check` + `mypy --no-incremental`. The CI workflow has
   no `redis:` services container — only postgres.

2. **AG-GRID MAJOR (#9, #11)** requires visual regression
   testing against `web/tests/e2e/.visual-regression-output/`.
   A CSS class change + theme rename will trigger pixel-diff
   failures unless manually migrated.

3. **TYPES-NODE MAJOR (#13)** is build-time-only but cascades
   into Next.js build; pre-merge build + tsc verification is
   required.

4. **JSDOM MAJOR (#7)** is most isolated (vitest-only) but
   vitest 2.x vs 1.x mismatch can cause silently-failing test
   environment changes.

## Decision

Recommend MANUAL REVIEW by maintainer(s) before merging any of
the 5 HIGH-RISK PRs. Per-PR review checklist is the fastest path
to a defensible merge decision.

Followups:
- Begin Phase 2 — squash-merge 10 SAFE PRs sequentially via
  `gh pr merge --squash --delete-branch` (Followup 2).
- Open PR-review sub-plans (`plans/136-v0105-pr-7-jsdom-review.md`,
  etc.) when the manual review starts for each HIGH-RISK PR.

## Verification

After all 10 SAFE PRs are merged, Main CI should remain GREEN
(since we already verified the green-baseline contract via
Phases 1A through 1C-round-5 — 9 commits).
