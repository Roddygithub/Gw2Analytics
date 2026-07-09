# v0.10.0 plan 032 — cross-account comparison timeline

> **Cycle:** v0.10.0 (per `plans/010-v100-roadmap.md`)
> **M effort** (the maintainer's most-requested feature in the incident log; closes
> the "squad-comparison" use case from `docs/ROADMAP.md` §1).
> **Shipped:** 1 commit, 9 new + 7 modified files.

## Why

The v0.8.0 per-account timeline chart shows 3 metrics (damage / healing /
strip) for ONE account. The maintainer's #1 feature request (logged in
`docs/ROADMAP.md` §1) is the squad-comparison use case: overlay 2-4 accounts
on the same chart so an analyst can spot "how does my healer's damage
absorbed compare to my DPS's damage output across the same fight window?"

The v0.7.0 `PlayerProfile` aggregator already emitted per-account roll-ups
that the per-account timeline could read. Plan 032 wires a NEW
`CrossAccountTimelineAggregator` + a NEW
`GET /api/v1/players/compare/timeline` route + a NEW web stack
(`/players/compare` page + `CrossAccountTimelineChart` SVG + the
`CrossAccountCompareSection` Client Component).

## Design

### Backend

| Layer | Change |
| --- | --- |
| `libs/gw2_analytics/src/gw2_analytics/cross_account_timeline.py` | NEW: stateless aggregator. Pydantic `CrossAccountTimelinePoint` + `CrossAccountTimelineSeries` + `CrossAccountTimelineAggregator.aggregate(per_account_contributions, fight_id_to_started, bucket, tz)`. Same recency-first sort + day-bucketing as the per-account timeline. 7 hermetic tests in `libs/gw2_analytics/tests/test_cross_account_timeline.py`. |
| `apps/api/src/gw2_analytics_api/routes/player_compare.py` | NEW: `GET /api/v1/players/compare/timeline` with a repeatable `?accounts=` query param (`[2, 4]` unique accounts). Reuses the per-account route's `_compute_contributions` helper. Echoes the `bucket` + `tz` semantics. Returns one `CrossAccountTimelineSeries` per requested account (an unknown account gets `points: []`, NOT 404). |
| `apps/api/src/gw2analytics_api/main.py` | Wired the new router. **Declaration order matters** — the catch-all `{account_name:path}` route on `players` would greedily match `/players/compare/timeline` with `account_name="compare/timeline"` if the cross-account route were declared second. |
| `libs/gw2_analytics/src/gw2_analytics/__init__.py` | Re-exports `CrossAccountTimelineAggregator` + `CrossAccountTimelineSeries` so consumers don't reach into the sub-module. |

### Web

| Layer | Change |
| --- | --- |
| `web/src/lib/api.ts` | NEW: `fetchPlayerCompareTimeline(accounts, opts)` + `CrossAccountTimelinePoint` + `CrossAccountTimelineSeries` types. |
| `web/src/components/CrossAccountTimelineChart.tsx` | NEW: purpose-built SVG chart (NOT a wrapper around the existing `TimelineChart` because the cross-account use case is 1 metric × N accounts, the inverse of the per-account chart's N metrics × 1 account). N polylines (one per account, 4-color palette) on a shared absolute Y axis (log scale default). Broken-line segments for missing dates (an account with no fight on date D renders no line segment through D). |
| `web/src/components/CrossAccountCompareSection.tsx` | NEW: Client Component. Owns the metric / scale / bucket / tz toggles + re-fetches the timeline when bucket / tz change. The metric + scale are pure client state. Account chips show each selected account with a remove button (the remove is a v0.10.X followup — the current cycle renders the URL the user would land on). |
| `web/src/app/players/compare/page.tsx` | NEW: Server Component. Reads `?accounts=` from the URL search params, validates `2 ≤ unique_accounts ≤ 4`, fetches the initial compare timeline on the server, renders the section. Empty-state copy for `< 2` accounts; upstream-error card for `> 4` or 422 from the gateway. |
| `web/src/app/layout.tsx` | Added a "Compare" secondary nav link between the brand and the search bar so the analyst can pivot to the compare view from any page. |
| `web/src/app/players/page.tsx` | Added a "Compare the first 2 players" CTA that pre-fills the URL with the first 2 rows' `account_name`. |

### E2E

| Layer | Change |
| --- | --- |
| `web/tests/e2e/fixtures/cross-account-timeline.json` | NEW: 2-account fixture with overlapping but distinct fight sets (2026-07-07 + 2026-07-08 for TestAccount.1234, 2026-07-07 + 2026-07-09 for TestAccount.5678). Exercises the broken-line + legend + X-axis date-union paths. |
| `web/tests/e2e/mock-server.mjs` | Added the `/api/v1/players/compare/timeline` endpoint. Validates that every `?accounts=` value is in the `TestAccount.1234` / `TestAccount.5678` set (422 otherwise). |
| `web/tests/e2e/players-compare.spec.ts` | NEW: 3 cases — initial render, metric radio toggles, 0-accounts empty state. |
| `web/tests/components/cross-account-timeline-chart.test.tsx` | NEW: 5 vitest cases — empty state, multi-account polylines, default Damage caption, metric switch, log scale Y-axis labels. |
| `web/tests/components/cross-account-compare-section.test.tsx` | NEW: 2 vitest cases — initial render + radio click. |
| `web/tests/app/players-compare-page.test.tsx` | NEW: 3 vitest cases — empty state, too-many, valid render. |

### Tests

- **Backend:** 7 hermetic pytest cases (`libs/gw2_analytics/tests/test_cross_account_timeline.py`).
- **Web:** 5 chart vitest + 2 section vitest + 3 page vitest + 3 playwright = 13 new cases.

## Non-goals (deferred to v0.10.X followups)

- Add/remove accounts from the compare view in-place (the current cycle's chip remove button surfaces the URL the user would navigate to; the full in-page add/remove UI is ~50 LoC and is a v0.10.X followup).
- Visual regression test on `/players/compare` (the route is dynamic; the fixture + spec cover the e2e path; a visual baseline is a v0.10.X followup when the page settles).
- Aggregator-side per-account-vs-cross-account rate columns for fair comparison (a per-second rate field on `CrossAccountTimelinePoint` is a v0.10.X followup; the v0.10.0 wire surface is the totals-only contract).
- Pagination of the cross-account timeline (the per-account route's offset/limit is not relevant here because the compare view shows all fights simultaneously; the chart's point count is bounded by the per-fight total in the dataset, typically < 200).
