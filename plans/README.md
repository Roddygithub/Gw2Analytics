# Advisor Plans Index

This directory holds the forward-looking advisor audits for the GW2Analytics
monorepo. Each audit is a senior-advisor survey (improve skill, `next`
invocation, `quick` effort) that scopes the next cycle's direction-only
candidates. The plans are self-contained implementation specs that a
different, less-context-aware executor can ship without further
clarification.

## v0.8.9 audit (current)

**Author:** senior-advisor audit (improve skill, `next` invocation, `quick` effort)
**Stamped at:** `1b1de47` (origin/main HEAD at audit time -- after the
v0.8.8 cycle fully closed: 3 plans executed, CHANGELOG entry, `v0.8.8`
tag on origin, README `## Release Tags` + `## Phase Status` synced)
**Recon scope:** README + CHANGELOG + pyproject.toml + apps/api routes +
web/app pages + recent commits + plans/001 + plans/002 + plans/003
**Audit mode:** direction-only (3 candidates below);
correctness/security/perf/etc. out of scope

### v0.8.9 status table

| # | Finding | Category | Impact | Effort | Risk | Plans |
|---|---------|----------|--------|--------|------|-------|
| 1 | Per-day bucketing on `/players/[name]/timeline` is UTC-only; the v0.8.1 CHANGELOG already noted a future `?tz=Europe/Paris` query param | direction (DX + correctness) | Medium (per-day bucketing only really makes sense in an analyst's TZ) | S | Low | [001](./001-tz-param-player-timeline.md) |
| 2 | `/fights/[id]` has per-target trio + per-subgroup + per-skill + event windows; no temporal view within a single fight (the v0.8.0 player timeline is cross-fight only) | direction (analytics + UX) | High (new visualization; complements the per-target trio) | M | Low | [002](./002-per-fight-timeline-tab.md) |
| 3 | v0.8.8 shipped 8 tracked PNGs at `docs/screenshots/` but no automated check that a UI refactor doesn't change them | direction (testing) | High (catches UI regressions in CI) | M | Low | [003](./003-visual-regression-testing.md) |
| - | AG Grid Community → Enterprise upgrade (Row Grouping, Master/Detail, Server-Side Row Model) | not a finding — vendor + license decision; current dataset size doesn't justify the cost | — | — | — | rejected |
| - | Sentry integration for error tracking | not a finding — defer until production traffic warrants it (current setup has no production traffic) | — | — | — | rejected |

### Recommended execution order (v0.8.9)

1. **Plan 001** (`?tz=Europe/Paris` on player timeline) — S effort, the
   smallest + highest-leverage of the 3 plans. Well-scoped extension
   to the v0.8.1 day-bucketing work; the service-layer swap is a
   1-line `to_user_tz(started_at).date()` change. Closes the long-
   standing "TZ assumption documented inline" technical-debt note from
   the v0.8.1 CHANGELOG.
2. **Plan 002** (per-fight timeline tab on `/fights/[id]`) — M effort,
   new visualization that complements the per-target trio. Reuses the
   v0.8.0 `PlayerTimelineChart` data shape (3 polylines, per-series
   normalisation, SVG-native `<title>` tooltip); a future refactor
   could extract a shared `<TimelineChart>` base component. The
   `GET /api/v1/fights/{id}/timeline` route is a thin wrapper over
   the existing events-blob decompress.
3. **Plan 003** (visual regression testing) — M effort, M payoff.
   Closes the gap between "we have 8 tracked PNGs" and "CI fails on
   a UI refactor that changes any of them by > 1%." Uses
   `playwright.screenshot()` + `pixelmatch` (npm, ~50 KB).

There are no inter-plan dependencies blocking. All 3 are independent
and could ship in any order.

### Considered and rejected (v0.8.9)

- **"AG Grid Community → Enterprise upgrade"**: vendor + license
  decision; the current dataset size (single-fight pages with
  5-100 rows) doesn't justify the cost. Row Grouping + Master/Detail
  would be useful for cross-fight roll-ups, but the v0.7.0
  PlayerProfileAggregator already handles the cross-fight join
  server-side. Defer to v0.9.0+ when the dataset grows past 1000
  fights and the client-side rendering starts to struggle.
- **"Sentry integration for error tracking"**: the current setup has
  no production traffic, so error tracking is premature. Defer until
  the first production deployment warrants it.
- **"Upload round-trip e2e test"**: was deferred from v0.8.8 plan/002.
  The fixture-blob work is non-trivial (a real `.zevtc` fixture that
  exercises the parser without taking 30s), and the e2e suite would
  need a real-API CI run (the mock server doesn't exercise the actual
  upload parser). Defer to v0.9.0+ when a real-fixture integration
  test exists for the parser.
- **"Refactor 3 existing Playwright specs to add the `pageerror` check"**:
  was deferred from v0.8.8 plan/002. The 1-line change per spec is
  too small to be a standalone plan. Can be folded into plan 003
  (visual regression testing) as a sub-task if the visual regression
  work is in flight; otherwise, fold it into the first plan that
  touches the existing specs.

---

## v0.8.8 audit (closed)

**Author:** senior-advisor audit (improve skill, `next` invocation, `quick` effort)
**Stamped at:** `fe99cb7` (origin/main HEAD at audit time)
**Recon scope:** README + CHANGELOG + pyproject.toml + apps/api routes + web/app pages + recent commits
**Audit mode:** direction-only (4 candidates below); correctness/security/perf/etc. out of scope

### v0.8.8 status table (closed)

| # | Finding | Category | Impact | Effort | Risk | Status (final) | Plans |
|---|---------|----------|--------|--------|------|----------------|-------|
| 1 | `pnpm screenshots` produces 8 PNGs that are gitignored + invisible to end-users | direction (DX + docs) | High (UX) | S | Low | **shipped** (`6fc4fcb`) | [001](./001-screenshots-into-readme.md) |
| 2 | Playwright config + `pnpm test:e2e` exist but zero actual e2e tests in repo | direction (testing) | High (reliability) | M | Low | **shipped** (`1b1de47`) -- 3 of 6 specs + mock-server + CI already in `web/tests/e2e/` from v0.7.1/v0.7.2/v0.8.0; v0.8.8 added 3 new specs (landing/account/upload) + 2 mock endpoints (POST /api/v1/account + POST /api/v1/uploads) | [002](./002-real-playwright-e2e-suite.md) |
| 3 | `pnpm generate:api` is manual; web app often runs against a stale or absent `schema.d.ts` | direction (DX) | Medium (dev experience) | S | Low | **shipped** (`7f40d51`) | [003](./003-auto-codegen-on-pnpm-dev.md) |
| - | Web routes already cover all API endpoints (7/7 web pages vs 8 distinct API endpoint groups) | not a finding — already shipped | — | — | — | rejected |

### v0.8.8 execution summary

1. ~~**Plan 001** (Screenshots → README)~~ — shipped in `6fc4fcb`. 8
   PNGs tracked at `docs/screenshots/`, wired into a new `## Screenshots`
   section of the root README, with `pnpm screenshots --persist` as
   the refresh workflow.
2. ~~**Plan 002** (Close remaining e2e gaps)~~ — shipped in `1b1de47`.
   3 new spec files (`landing.spec.ts`, `account.spec.ts`,
   `upload.spec.ts`) + 2 mock endpoint additions to
   `web/tests/e2e/mock-server.mjs` (`POST /api/v1/account` +
   `POST /api/v1/uploads`). The plan was revised at `48fa91a` to
   reflect the 3 pre-existing specs (fights/players/players-timeline)
   that the v0.7.1/v0.7.2/v0.8.0 cycles had already shipped.
3. ~~**Plan 003** (Auto-codegen on dev)~~ — shipped in `7f40d51`.
   `pnpm dev` now chains `pnpm generate:api && next dev`; missing
   `openapi-typescript` dep added; `web/.gitignore` updated;
   `web/README.md` `## OpenAPI regeneration` section rewritten.

The v0.8.8 cycle is fully closed: 3 plans executed + CHANGELOG
`[0.8.8]` entry + `v0.8.8` tag on origin + README `## Release Tags` +
`## Phase Status` synced.

### Considered and rejected (v0.8.8)

- **"Build /fights/[id]/timeline tab" / "Upload progress feedback" / "Per-player-fights route"**: each is plausible but small-leverage vs the plans above; would need full design + UX validation first. **The per-fight timeline tab is now plan/002 in the v0.8.9 audit** (with the design + UX validation done); the other two remain reserved for v0.9.0+.
- **"S3-backed blob storage for evtc files"**: large infrastructure commitment (storage vendor, IAM, lifecycle, cost); proceed only after uploader has real-user volume proving the need. Out of scope for v0.8.8 (and v0.8.9).
- **"Web route coverage of remaining API endpoints"**: all 7 web pages already exist and route to the corresponding API endpoints; coverage is full. Not a finding.

---

## Conventions for the executor

- The repo uses Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `style:`, `refactor:`).
- Python: `uv run <cmd>` from repo root or `cd apps/api && uv run <cmd>` — never `pip`.
- JS: `pnpm <cmd>` from `web/` or repo root (pnpm workspace).
- Validation: `uv run ruff check`, `uv run mypy --no-incremental libs apps`, `uv run pytest <path>`, `pnpm typecheck`, `pnpm test:unit`, `pnpm exec playwright test`.
- Commit-style: every commit has substance (no empty commits); every feature gets a doc sync in the same cycle (README + CHANGELOG).
- Code-reviewer pattern: spawn `code-reviewer-minimax-m3` for **every** non-trivial commit with concrete prompt (≤70 words + focus questions).
- Plan pattern: every plan is self-contained. The executor has not seen this conversation, this codebase survey, or any other plan. If a plan references "the pattern discussed above," it is broken.
