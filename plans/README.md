# Advisor Plans Index

This directory holds the forward-looking advisor audits for the GW2Analytics
monorepo. Each audit is a senior-advisor survey (improve skill, `next`
invocation, `quick` effort) that scopes the next cycle's direction-only
candidates. The plans are self-contained implementation specs that a
different, less-context-aware executor can ship without further
clarification.## v0.9.1 audit (security + correctness + correctness-tighter focus)

Five plans selected from the v0.9.1 audit (drift base `ef5e4f3`). Each plan addresses one HIGH-confidence finding; ordering below reflects the recommended implementation sequence (most-blocking → least-blocking).

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 004 | [004-v091-webhook-schema-id-type-fix](./004-v091-webhook-schema-id-type-fix.md) | **shipped** (`WebhookDeliveryOut.id` + `WebhookDeliveryReplayOut.delivery_id` → `str` with `Field(min_length=1, max_length=64)`; `Field` import added to `schemas.py`; hermetic regression test on schema shape) | #1 schema `int` ↔ `str` mismatch on `WebhookDeliveryOut` + `WebhookDeliveryReplayOut` | S |
| 005 | [005-v091-webhook-ssrf-block-https](./005-v091-webhook-ssrf-block-https.md) | **shipped** (universal IP-block on resolved addresses in `_validate_webhook_url` — direct IP literals classified via `ipaddress.ip_address`, hostnames via `getaddrinfo` for IPv4+IPv6; opt-out via `GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS` env; fail-closed on DNS errors; 5 new SSRF regression tests covering RFC1918, link-local, IPv6 loopback, hostname-resolves-to-private, and the opt-out escape hatch) | #2 SSRF bypass in `_validate_webhook_url` for `https://` schemes | S |
| 006 | [006-v091-upload-bg-task-closed-session](./006-v091-upload-bg-task-closed-session.md) | **shipped** (`process_parse(db)` → `process_parse(session_factory, upload_id, raw_bytes)`; body wrapped in `with session_factory() as db:`; both BG-task callers updated to `get_sessionmaker()`; regression test verifies the session is alive at task invocation time) | #3 closed-session bug in `process_parse` BackgroundTasks path | S |
| 007 | [007-v091-webhook-retry-dlq-replay-tests](./007-v091-webhook-retry-dlq-replay-tests.md) | **shipped** (4 NEW tests: scheduler first-attempt success, exponential backoff (single 10s step at attempt 2) → DLQ promotion on hitting ``_MAX_ATTEMPTS = 3``, replay idempotency under concurrent ``ThreadPoolExecutor`` + ``Session.commit`` race-widener, and HMAC byte-for-byte integrity across replays; the multi-tick ``test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts`` landed in standalone ``apps/api/tests/test_webhooks_e2e_scheduler.py`` after an in-session deferral -- flat per-tick ``with``-block structure escapes the nested dedent footgun; original ``pytest.skip()`` placeholder in ``test_webhooks_e2e.py`` replaced with a stub-by-name pointer to the new module; ``time-machine`` dev-dep added; 22 tests collected across the 2 files; pytest --collect-only clean; mypy clean; ruff clean except 1 cosmetic E501 docstring line in the stub pointer) | #4 v0.9.1 retry+DLQ+replay test gap (0 tests on the scheduler tick + DLQ promote + replay idempotency) | M |
| 008 | [008-v091-openapi-drift-gate-fix](./008-v091-openapi-drift-gate-fix.md) | **shipped** (`src/lib/api/schema.d.ts` un-gitignored + committed as 71 KB baseline; CI `Detect API client drift` step (`git diff --exit-code -- web/src/lib/api/schema.d.ts`) inserted between `OpenAPI: regenerate web TypeScript client` and `Type-check web`; `CONTRIBUTING.md` `## Regenerating the web TypeScript client` section documents the contract — `Schema.d.ts` must be regenerated + committed in the SAME PR as any backend `apps/api/src/gw2analytics_api/routes/*` shape change; `openapi.json` remains gitignored as ephemeral intermediate artifact; deterministic re-regen verified via drift-gate smoke test (no diff after re-run)) | #5 broken OpenAPI drift gate (schema.d.ts is .gitignored, gate never has anything to diff) | S |

### Considered but deferred

The Agent B perf + tech-debt re-run surfaced 5 additional findings after the security+correctness pass was over. They are tracked here for the next cycle (v0.9.1 hardening or v0.10):

| # | Finding (drift base `ef5e4f3`) | Implication | Suggested phase |
|---|---|---|---|
| 12 | `routes/fights.py:list_fights` N+1 query across `agents` + `skills` relationships | `limit=50` triggers 101 SELECTs | v0.10 perf |
| 13 | `webhook_scheduler.process_scheduled_retries` sync HTTP serially blocks up to 10s per row | One slow webhook stalls the queue | v0.9.1 hardening (combine with plan 006) |
| 14 | `_load_fight_events` re-downloads + decompresses + re-validates per endpoint (4× per fight hit by parallel frontend) | Massive OOM risk on busy fights | v0.10 perf |
| 15 | `_attempt_retry` subscription lookup N+1 in scheduler tick | One query per delivery on retry path | v0.9.1 hardening (combine with plan 007 tests) |
| 16 | `services.read_zevtc_bytes` fully unzips in memory | Scaling poor under BG-worker concurrency | v0.10 perf (streaming parser redesign) |

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

### Hardening followups (post v0.9.1 ship)

Two followup cycles landed during the v0.9.1 hardening pass after the 5 audit plans shipped:

| # | Action | Addresses | Outcome |
|---|---|---|---|
| H1 | **Plan 007 re-attempt** — the originally-deferred multi-tick scheduler test `test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts` (exponential backoff at attempt 2 + DLQ-promote at attempt 3, seeded via `time-machine` clock advances + respx 500 mock) moved to a standalone `apps/api/tests/test_webhooks_e2e_scheduler.py` module with FLAT per-tick `with`-block structure (`_respx.mock` OUTERMOST + short-lived `time_machine.travel` per tick, no nesting); the original `pytest.skip()` placeholder in `apps/api/tests/test_webhooks_e2e.py` replaced with a stub-by-name pointer for search-by-name discoverability; ``assert count1 == 1``/``assert count2 == 1`` assertions moved to 8-space (inside each `time_machine.travel`) so they re-anchor unambiguously after future str_replace cleanups | deferred slot in plan 007 (the in-session deferred multi-tick scheduler test) | **shipped** -- all 4 retry+DLQ+replay tests from plan 007 now land; 22 tests collected across the 2 files; ruff + mypy + pytest collect-only all clean |
| H2 | **Pre-existing lint-debt cleanup** -- 9 ruff errors + 9 ruff-format fixes + 3 mypy errors in `apps/api/tests/` (all pre-existing from prior v0.9.0/v0.9.1 cycles, NOT introduced by plans 004-008). Auto-fixes via `ruff check --fix --unsafe-fixes` (cleared 2 F841 unused-vars in test_players.py) + `ruff format` (10 files reformatted); targeted str_replace / Python edits cleared the rest: dropped 2 unused `# noqa:` directives in test_players.py (PLC0415 on top-level `struct`, F401 on actively-used `_uuid`), dropped extra isort blank-line split, hoisted `import time` to top-level + dropped the inline `import time as _time  # noqa: PLC0415, F811` + converted 2× `_time.sleep(0.1)` to `time.sleep(0.1)`, reordered the stdlib imports in test_uploads_e2e.py (`from X` before `import X`), wrapped the long docstring line in test_webhooks_e2e_scheduler.py via `See  \`\`...\ntest_retry_scheduler_failure_promotes_to_dlq_after_max_attempts\`\``, ran `ruff check --fix` (auto-fixed the trailing W293 whitespace + the residual I001 group split) + `ruff format` for a final pass | accumulated lint debt from test_players.py / test_uploads_e2e.py / test_webhooks_e2e.py / test_webhooks_e2e_scheduler.py | **shipped** -- `ruff check` + `ruff format --check` + `mypy libs apps --no-incremental` all 0 errors; 22 pytest tests collect; ``git status`` shows the 4 affected test files modified (no behavioural changes in production code) |

Both followups are docs-only + test-fixture-touch-ups; no production code paths were affected. The v0.9.1 hardening cycle is now ready for the operator-side close-out: the atomic `feat(api+web): v0.9.1 security + correctness hardening (schemas, SSRF, BG-task, retry+DLQ+replay tests, OpenAPI drift gate)` commit + CHANGELOG `[0.9.1]` entry + `v0.9.1` tag.

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
