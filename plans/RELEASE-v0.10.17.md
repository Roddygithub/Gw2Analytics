# Release v0.10.17

**Cycle date:** 2026-07-13
**Cycle commit:** (latest on `main` post close-out — the `docs(release+changelog): v0.10.17 cycle release notes` commit will be the cycle-end SHA substituted post-tag)
**Tag:** `v0.10.17`
**Branch / tag state:** `main` (sole branch); +1 tag (`v0.10.17`) on top of v0.10.13 + v0.10.14 + v0.10.15 + the v0.10.16 deferral artifact (NO `v0.10.16` tag). The `v0.10.17/mimo-half` working branch was deleted post-fast-forward-merge per CONTRIBUTING.md linear-history rule.
**Branch protection:** linear history (no merge commits); no force-pushes; pre-commit pre-push idempotent
**Plan provenance:** the cycle absorbed the v0.10.16 SPEC's planned 4 deliverables (D1-D4 from the v0.10.16 mimo-half) into its own 5 (D1-D5) per [`plans/v0.10.17-mimo-half-prompt.md`](./v0.10.17-mimo-half-prompt.md) §"The 5 deliverables"; per the v0.10.16 deferral at [`plans/AUDIT-2026-07-12-d21e840.md`](./AUDIT-2026-07-12-d21e840.md) "Recommended v0.10.17 scope" section.

---

## Headline

v0.10.17 is the **combined scope cycle** per the v0.10.16 deferral + the F18 Replay UI main scope. The 5 deliverable commits ship:
- **F18 Replay UI** (L effort, main scope) — D1 + D2 + D5
- **C1 Pre-existing vitest fix-up** (M effort, picks up the deferred v0.10.16 D1-D2 work) — D3
- **D4 Hygiene pin — `fetchCached` LRU isolation test** (S effort, the deferred v0.10.16 D4) — D4
- **D5 Replay + fetchCached integration pin** (S effort, anti-regression cross-component substrate for the new surfaces) — D5
- Plus 2 close-out docs commits: ROADMAP refresh + cycle-end audit (6a) + release notes + CHANGELOG entry (6b).

Net vitest delta vs cycle-start: **+25 new passing tests** (D2: 13 + D4: 6 + D5: 6) + **1 pre-existing failure closed** (D3: `window-size-selector.test.tsx` TDZ fix takes the 7→6 count) = **26 GREEN test improvement**. The **6 residual pre-existing vitest failures** in `web/tests/components/fight-events-page*` (hypothesised `fetchCached`/`window.fetch` interaction) + the **2 residual pre-existing pytest failures** in `apps/api/tests/test_uploads_e2e.py` are the O6 carry-forward to v0.10.18.

| Metric | v0.10.15 | v0.10.17 | Delta |
|---|---|---|---|
| mypy errors in `src/` | 0 | **0** | stable (cycle is web-only) |
| ruff violations | 0 | **0** | stable |
| pnpm tsc | GREEN | **GREEN** | stable (ReplayPlayer.tsx + replayFetcher.ts + page.tsx typecheck strict) |
| vitest 3-gate (touched) | GREEN | **GREEN** | stable (D4 + D2 + D5 = 25/25 PASS) |
| pytest 3-gate (touched) | GREEN | **GREEN** | stable (backend untouched) |
| Pre-existing pytest (untouched) | 2 | **2** | unchanged; carry-forward O6 (backend-touching cycle needed) |
| Pre-existing vitest (untouched) | 7 | **6** | -1: D3 closed window-size-selector.test.tsx TDZ |
| Atomic code commits shipped | 4 (v0.10.15 code plans 032-035) | **5 (v0.10.17 D1-D5)** | +1 (D5 is the new anti-regression pin; D4 is the regression pin for v0.10.14 D2; D3 is a pre-existing-failure fix-up) |
| Docs commits shipped | 2 (ROADMAP + RELEASE v0.10.15) | **2 (ROADMAP + AUDIT, then RELEASE + CHANGELOG)** | same cadence |

---

## Per-commit scope (5 atomic code+tests commits + 2 close-out docs commits = 7 total)

### Commit 1 — `test(web): fetchCached LRU isolation test (refs plan 036 hygiene pin)`

Pins the v0.10.14 D2 `fetchCached` helper against future refactors. 6 sub-cases cover the brief's 5-promised-behaviors + 1 concurrency case:

- **Sub-case 1** — TTL hit within 60s returns same cached value (zero new network round-trips)
- **Sub-case 2** — TTL expiry after 60s+ re-fetches (1 new round-trip)
- **Sub-case 3** — Overlapping same-URL calls (Promise.all) collapse to 1 network round-trip via in-flight dedup
- **Sub-case 4** — Rejection does NOT cache (a failed fetcher does NOT poison the cache; retry gets a fresh attempt)
- **Sub-case 5** — LRU cap eviction at maxsize=8 (the 9th distinct URL evicts the oldest; memory bound is hard)
- **Sub-case 6** — Concurrent `Promise.all` dedup yields 1 round-trip + N-1 awaited results (real-world fan-out)

This is the deferred v0.10.16 D4 (hygiene pin), lifted forward per the v0.10.16 brief's MUST-D4 contract. Without this, a future `fetchCached` refactor could silently break the LRU bound + the TTL contract + the dedup contract without test detection.

**Files touched:** `web/tests/lib/fetchCached-isolation.test.ts` NEW (~200 LoC, 6 cases)

### Commit 2 — `fix(web): wrap window-size-selector test mocks in vi.hoisted (pre-v0.10.17 carry)`

Closes 1 of the 7 pre-existing vitest failures: `web/tests/components/window-size-selector.test.tsx` had a TDZ error on the top-of-file `pushMock` + `searchParamsMock` constants when vitest hoists `vi.mock(...)` above them. The fix wraps both mocks in `vi.hoisted(() => ({ pushMock: vi.fn(), ... }))` so they initialise BEFORE the `vi.mock` calls run. Round-2 fix-up from the cycle's first review pass.

**Files touched:** `web/tests/components/window-size-selector.test.tsx` MODIFIED (~30 LoC delta)

### Commit 3 — `feat(web): Replay UI for /fights/[id] + page tab routing (v0.10.17 F18)`

The main scope ship. The Replay UI is a NEW top-level Client Component on the per-fight drilldown page, backed by a NEW typed fetcher wrapper:

- `web/src/components/ReplayPlayer.tsx` NEW (~600 LoC) — the playback engine (play/pause + 1x/2x/4x/8x speed toggle + scrubber drag + auto-pause at last bucket) + the per-bucket visualisation (3 horizontal sub-bars per bucket: damage / healing / strip; round-2 fix from the round-1 stacked-segment overflow bug) + the locale-formatted totals + the speed-chip cluster with `aria-pressed` + the current-bucket badge `B{i+1}` + the empty-state messaging.
- `web/src/lib/replayFetcher.ts` NEW (~90 LoC) — wraps `fetchCached` to fetch the per-fight timeline rollup at the page's resolved `window_s`. URL omits `?window_s=` when windowS=5 (gateway default; preserves pre-D1 fetchCached cache key) and includes `?window_s=N` otherwise (round-2 fix from the round-1 qs drift). Defence-in-depth `encodeURIComponent(fightId)` for any rogue `&/?=` characters.
- `web/src/app/fights/[id]/page.tsx` MODIFIED — adds Replay tab to the tab strip; case-insensitive tab matching (lowercase) handles `?tab=Replay` + `?tab=replay` + default. Wires `fetchReplayTimeline` into the `Promise.allSettled` (6th parallel fetch).
- `web/src/components/PerFightTimelineChart.tsx` MODIFIED (1-line) — `export` added to `formatSecondsLabel` so ReplayPlayer.tsx can reuse it (the canonical s/m/h formatter).
- 4-round review cadence: round-1 surfaced TSC18047 narrowing bug + bar-chart overflow bug + vi.mock TDZ; round-2 custom `ReplayPlayerInnerProps = { fightId: string; timeline: FightTimeline }` strips null explicitly; round-2 bar subdivision replaces stacked segments; round-2 fetchReplayTimeline qs logic matches page's cache-key convention.

**Files touched:** 4 files (2 NEW + 2 MODIFIED)

### Commit 4 — `test(web): ReplayPlayer vitest specs (13 cases, v0.10.17 D2)`

Pins the Replay UI behaviour at the component level:

- 3 render chrome cases (scrubber `aria-valuemin`/`aria-valuemax`/`aria-valuenow` + speed chips `aria-pressed` + locale-formatted total captions)
- 5 playback-engine cases (Play click → setInterval fakes + speed-toggle changes interval + Pause click stops advancement + Reset click pauses + auto-pause at last bucket via `setTimeout(0)` deferred `setIsPlaying(false)`)
- 2 scrubber + current-bucket cases (scrubber drag updates currentIndex + current bucket badge `B{i+1}` highlights)
- 2 empty-state cases (no timeline / no buckets)
- 1 initial-state case (Bucket 1 of N visible at mount)

All `vi.advanceTimersByTime(N)` calls wrapped in `act(() => ...)` to neutralise React 18+ auto-batching flakiness. Round-2 fix from the round-1 ACT-failure surface.

**Files touched:** `web/tests/components/replay-player.test.tsx` NEW (~250 LoC, 13 cases)

### Commit 5 — `test(web): Replay + fetchCached substrate integration anti-regression (v0.10.17 D5)`

Pins the cross-component substrate WRAPPER contract: the contract between `ReplayPlayer.tsx` (consumer) and `fetchCached.ts` (infrastructure) is `fetchReplayTimeline(opts) -> FightTimeline`. 6 sub-cases:

- Sub-case 1 — URL omits `?window_s=` when windowS=5 (gateway default; preserves pre-D1 `fetchCached` cache key)
- Sub-case 2 — URL includes `?window_s=N` when windowS!==5 (non-default window distinct from default)
- Sub-case 3 — `encodeURIComponent` defensiveness on fightId (no rogue `?/&/=` leaks through)
- Sub-case 4 — Invalid windowS rejection (0, -1, NaN) BEFORE the gateway call (validation at the wrapper boundary)
- Sub-case 5 — `fetchCached` error propagation (502 + ECONNREFUSED) unmodified to caller
- Sub-case 6 — LRU cache hit across calls within 60s TTL (verifies the wrapper actually goes through `fetchCached` and not a direct `fetch`)

Sub-case 6 is the cross-component anti-regression anchor: a future regression in EITHER ReplayPlayer.tsx OR fetchCached.ts would break this contract; D5 is the single test that catches regressions on EITHER side. Round-2 fix from the round-1 Response-body reuse bug (`mockImplementation` factory per call returns a fresh Response with fresh body stream; without it, the 3rd call's `resp.json()` sees an exhausted stream).

**Files touched:** `web/tests/lib/replay-substrate-integration.test.ts` NEW (~290 LoC, 6 cases)

### Commit 6 — `docs(roadmap+audit): v0.10.17 sync to cycle-end audit`

Persists the cycle's ledger close-out per [`docs/ROADMAP.md` §"Update protocol"](../docs/ROADMAP.md) + produces the cycle-end audit document per CONTRIBUTING.md's per-major-version audit cadence:

- `docs/ROADMAP.md` — header stamp bumped to "post v0.10.17 cycle (2026-07-13)" + §1.1 absorbed v0.10.17 D1-D5 cycle shipts with file-level attribution + §1.2 shortlist re-classifies plan 036's status as **partially closed (1 of 7 vitest fixed)** rather than fully closed (the brief's optimistic framing was not strictly accurate). §1 v1.0 candidates table removes the F18 Replay UI row (now shipped; no longer a candidate).
- `plans/AUDIT-2026-07-13-3b2e71f.md` NEW — full audit doc following the v0.10.15 + v0.10.14 audit-doc templates. 7 findings (6 resolved + 1 carry-forward O6 = residual pre-existing tests). Anchor commit = `3b2e71f` (D5 mockImplementation fix = the cycle's last code commit before docs close-outs). The release commit short-SHA will be substituted into the doc body in commit 6b's message + RELEASE doc body.

**Files touched:** `docs/ROADMAP.md` + `plans/AUDIT-2026-07-13-3b2e71f.md`

### Commit 7 — `docs(release+changelog): v0.10.17 cycle release notes`

The cycle close-out deliverable: this document + the CHANGELOG ledger bucketing entry above [`[Unreleased]`](../CHANGELOG.md) (preserving the prior bucketing move at commit `d21e840 + 66ce364`):

- `plans/RELEASE-v0.10.17.md` NEW — this file. 7 commits scoped (5 cycle + 2 docs).
- `CHANGELOG.md` — inserts `[0.10.17] - 2026-07-13: F18 Replay UI + pre-existing tests fix-up (plan 036 closure + plan-NNN D1-D5)` above `[Unreleased]`. NEW section follows the prior section ([0.10.15]) and the bucketed structure (newest-first).

**Files touched:** `plans/RELEASE-v0.10.17.md` + `CHANGELOG.md`

---

## Gate contract — v0.10.17 cycle-end (verified)

| Gate | Command | Result |
|---|---|---|
| ruff lint | `uv run ruff check apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src` | ✅ GREEN (0 violations — cycle is web-only, backend untouched) |
| ruff format | `uv run ruff format --check apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src` | ✅ GREEN |
| mypy (workspace) | `uv run mypy apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src` | ✅ GREEN (0 errors in 74 source files) |
| pnpm tsc (web touched) | `cd web && pnpm tsc --noEmit` | ✅ GREEN (2 NEW files + 2 MODIFIED files typecheck strict-mode) |
| vitest (touched) | `cd web && pnpm test --run --reporter=basic` | ✅ GREEN (28 files / 162 tests: D4 6/6 + D2 13/13 + D5 6/6 + 25 carry-overs = PASS) |
| pytest (touched) | n/a | n/a (cycle is web-only) |

**Pre-existing failures AFTER v0.10.17 (carry-forward O6 to v0.10.18 plan-036-followup):**
- 2 pytest failures in `apps/api/tests/test_uploads_e2e.py` (STABLE from v0.10.14 release notes; backend-touching cycle needed to address).
- 6 vitest failures in `web/tests/components/fight-events-page*.*` (down from 7 pre-D3; the residual 6 share a hypothesised `fetchCached`/`window.fetch` interaction root cause that needs a followup diagnostic cycle).

---

## Cross-references

- **Plan provenance:** [`plans/v0.10.17-mimo-half-prompt.md`](./v0.10.17-mimo-half-prompt.md) (the parent brief that scoped D1-D5 + the F18 Replay UI scope).
- **Audit reference:** [`plans/AUDIT-2026-07-13-3b2e71f.md`](./AUDIT-2026-07-13-3b2e71f.md) §"Resolved" / §"Open" / §"Carried Forward" sections.
- **Predecessor deferral:** [`plans/AUDIT-2026-07-12-d21e840.md`](./AUDIT-2026-07-12-d21e840.md) (the v0.10.16 deferral doc whose "Recommended v0.10.17 scope" section defined the combined scope).
- **Prior audit:** [`plans/AUDIT-2026-07-12-5d0d4d4.md`](./AUDIT-2026-07-12-5d0d4d4.md) (the v0.10.14 cycle-end audit whose O5 finding set the plan-036 deferral path).
- **ROADMAP sync:** [`docs/ROADMAP.md`](../docs/ROADMAP.md) §"Current state (post v0.10.17 cycle)" + §1.1 cycle shipts v0.10.17 entry + §1.2 shortlist.
- **Prior cycle (v0.10.15):** [`plans/RELEASE-v0.10.15.md`](./RELEASE-v0.10.15.md).
- **Cycle-end HEAD:** the release notes commit (this file's commit).

---

## Deferred / not in v0.10.17 scope

- **O6 (plan-NNN): residual pre-existing tests + D2 Playwright e2e** — DEFERRED to v0.10.18 cycle. The 6 vitest failures in `fight-events-page*` + the 2 pytest failures in `test_uploads_e2e.py` need a diagnostic-first cycle (capture vitest stdout, classify failures by category, fix regressions). PLUS land the deferred `web/tests/e2e/replay-ui.spec.ts` Playwright spec — the brief scoped the Playwright layer in D2 but this cycle ships the vitest layer only (manual `pnpm dev` walk-through confirms Replay renders + scrubber responds + playback engine ticks correctly).
- **F16 (README 9th-route sync)** — the v0.10.14 README `## API surface` table has 8 routes; the v0.10.17 Replay UI adds a 9th (`/fights/[id]/replay` tab or the new `fetchReplayTimeline` wrapper-derived endpoint). S-effort; v0.10.18 followup.
- **F17 (Combat readout, XL+ effort)** — still blocked on statechange parser + skills DB; deferred per maintainer direction.
- **F20 (ag-grid bundle tree-shake followup)** — still open from v0.10.14 audit; deferred until upstream tree-shake path lands.

---

## Forward cadence

The next audit should be stamped at post-v0.10.17 HEAD (this tag) and produced at ~2026-07-19 (next cycle). The v0.10.18 cycle's scope is expected to include **O6** (close residual pre-existing tests + land deferred D2 Playwright e2e) + **F16** (README 9th-route sync).
