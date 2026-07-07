# Advisor Plans Index

This directory holds the forward-looking advisor audits for the GW2Analytics
monorepo. Each audit is a senior-advisor survey (improve skill, `next`
invocation, `quick` effort) that scopes the next cycle's direction-only
candidates. The plans are self-contained implementation specs that a
different, less-context-aware executor can ship without further
clarification.

## v0.9.0 audit (current)

**Author:** senior-advisor audit (improve skill, `next` invocation, `quick` effort)
**Stamped at:** `9fcf1de` (origin/main HEAD at audit time -- after the v0.8.9 cycle fully closed: 3 plans executed + CHANGELOG + `v0.8.9` tag + README Phase Status + 2 followup commits for the visual-regression workflow tightening + the dimension mismatch fix)
**Recon scope:** README + CHANGELOG + plans/001-003 (v0.8.9) + libs/gw2_analytics + libs/gw2_evtc_parser/parser.py + apps/api routes + web/app pages
**Audit mode:** direction-only (3 candidates below); correctness/security/perf/etc. out of scope

### v0.9.0 status table

| # | Finding | Category | Impact | Effort | Risk | Plans |
|---|---------|----------|--------|--------|------|-------|
| 1 | `PlayerTimelineChart` (v0.8.0) + `PerFightTimelineChart` (v0.8.9) duplicate ~120 lines of near-identical SVG rendering logic; the v0.8.9 plan/002 entry noted this as a future refactor | direction (UX + DX) | Medium (DRY win, isolates complex SVG logic) | S | Low | [001](./001-v090-shared-timeline-chart.md) |
| 2 | `/players` AG Grid has no filter UI; an analyst looking for "all Mesmer players" has to scan the full table + sort client-side. The `profession` field is already in the response | direction (UX) | High (server-side filter is a one-line SQL WHERE + a dropdown) | M | Low | [002](./002-v090-filter-by-profession.md) |
| 3 | The v0.8.9 visual-regression spec covers 8 PNGs; 4 high-leverage UI states (second-fixture-fight, sorted-players, fight-with-timeline, account-with-tz) are missing | direction (testing) | Medium (catches v0.8.9 UI regressions that the current 8 PNGs miss) | S | Low | [003](./003-v090-vr-suite-expansion.md) |
| - | Buff uptime tracking (new visualization) | not a finding — the Python parser explicitly skips state-change records (`if is_statechange != 0: continue`); arcdps encodes buff applications as state changes. Implementing requires a major v1.4+ parser update before any aggregators could be built | — | — | — | rejected |
| - | Defense events ("what hit me") | not a finding — the parser only evaluates `is_nondamage == 0 + value > 0` (outgoing damage). Gathering incoming/defense events requires parser-level work + validation of arcdps's target tracking. Too undefined for v0.9.0 | — | — | — | rejected |
| - | AG Grid Community → Enterprise upgrade / Sentry integration | not a finding — same rejections as v0.8.9 (license cost + no production traffic) | — | — | — | rejected |

### Recommended execution order (v0.9.0)

1. **Plan 002** (filter by profession on `/players`) — M effort, the
   highest-leverage new feature. Self-contained (no parser/UX
   dependencies). A server-side `?profession=` query param + a small
   Client Component dropdown unlocks the existing `profession` field
   that's already in the response.
2. **Plan 001** (shared `<TimelineChart>` refactor + unified
   `?window_s=` UI) — S effort, a quick DRY win that depends on the
   v0.8.9 plan/002 being shipped (the per-fight timeline chart is
   one of the 2 refactor targets). The unified window-size UI is a
   small Server-Component change that drives both endpoints.
3. **Plan 003** (visual regression suite expansion) — S effort,
   additive coverage. Locks the v0.8.9 features in CI by capturing
   4 new PNGs (second-fixture-fight, sorted-players,
   fight-with-timeline, account-with-tz). The data-driven spec loop
   picks them up automatically.

There are no inter-plan dependencies blocking. All 3 are independent
and could ship in any order. The recommended order is by highest
leverage (plan/002 = new feature), then DRY win (plan/001), then
additive test coverage (plan/003).

### Considered and rejected (v0.9.0)

- **"Buff uptime tracking"**: a compelling visualization, but the
  Python parser explicitly skips state-change records (`parser.py:201`
  reads `if is_statechange != 0: continue`). arcdps encodes buff
  applications as state changes. Implementing this requires a major
  v1.4+ update to the core parser's binary extraction loop before
  any aggregators could be built. Defer to a future cycle that
  includes a parser overhaul.
- **"Defense events / 'what hit me'"**: complements the v0.8.9
  per-fight timeline ('what I did') with the reverse view. But the
  parser only evaluates `is_nondamage == 0 + value > 0` (outgoing
  damage). Gathering incoming/defense events requires parser-level
  work + validation of arcdps's target tracking. Too undefined for
  v0.9.0.
- **"AG Grid Community → Enterprise upgrade" / "Sentry integration"**:
  same rejections as the v0.8.9 audit. License cost + no production
  traffic.
- **"Compare 2 fights side-by-side"**: could use the v0.9.0 plan/001
  shared `<TimelineChart>` as the base. The side-by-side layout is a
  separate concern; deferred to v0.9.0+ (would depend on plan/001).
- **"Visual regression dashboard"**: a thin Server Component page at
  `/dev/visual-regression` that displays the latest captured PNGs +
  diff-vs-baseline percentages. Deferred to v0.9.0+; would need a
  "latest diff" artifact store that doesn't exist yet.

---

## v0.8.9 audit (closed)

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
