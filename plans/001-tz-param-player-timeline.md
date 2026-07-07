# Plan 001 — Add `?tz=Continent/City` query param to the player timeline

## Context

The v0.8.1 release added per-day bucketing on the player timeline:

- `?bucket=day` query param on
  `GET /api/v1/players/{account_name:path}/timeline`.
- Day-bucketed points have `started_at` set to the day's UTC midnight
  + totals are the SUM of the day's fights.

The v0.8.1 CHANGELOG entry for this work explicitly noted a known
limitation:

> The TZ assumption is documented inline: the day-bucketed point's
> `started_at` is the day's UTC midnight, NOT the analyst's local
> TZ midnight. A future v0.8.0 `?tz=Europe/Paris` query param
> will let the analyst pick a non-UTC TZ; the service-layer
> `day_bucketed_points` already groups by `started_at.date()` so
> the TZ switch is a one-line `to_user_tz(started_at).date()` swap.

The work was deferred at v0.8.1 because the broader v0.8.x cycle
was focused on per-account timelines + per-target name resolution.
The v0.8.9 cycle is the right place to close this small
technical-debt item: the `?tz=` query param is the smallest,
highest-leverage of the 3 v0.8.9 plans.

The correct `zoneinfo.ZoneInfo` is the stdlib path (Py 3.9+).
The web/ tier already follows the `bucket?: "fight" | "day"` option
pattern; the `?tz=` option follows the same shape.

## Goal

Add a `?tz=Continent/City` query param to
`GET /api/v1/players/{account_name:path}/timeline` that lets the
analyst pick a non-UTC timezone. Default is `"UTC"` (backward
compat — pre-v0.8.9 wire consumers see the same shape they saw
before). The day-bucketed point's `started_at` is the day's
midnight in the requested TZ; the `fight_id` tiebreaker is
unchanged; the per-fight bucket mode (`bucket=fight`) is
unaffected by `?tz=` (the TZ only matters for the day-mode
grouping).

## Files in scope

- `apps/api/src/gw2analytics_api/routes/players.py` — the
  timeline route gains a `tz: str = Query("UTC")` parameter
  and threads the parsed `ZoneInfo` into the
  `day_bucketed_points` helper. The route's docstring is
  extended to document the new param + the default + the
  422 contract for invalid TZ strings.
- `apps/api/src/gw2analytics_api/services.py` — the
  `day_bucketed_points` helper signature gains a
  `tz: ZoneInfo = ZoneInfo("UTC")` parameter; the
  `started_at.date()` call is replaced with
  `started_at.astimezone(tz).date()`. The day-bucketed
  point's `started_at` is set to
  `datetime(tz_year, tz_month, tz_day, tzinfo=timezone.utc)` so
  the wire surface stays in UTC (backward compat for the
  JSON consumer) but the date grouping is in the analyst's
  TZ.
- `apps/api/src/gw2analytics_api/schemas.py` — the
  `PlayerTimelineOut` schema gains an optional
  `tz: str = "UTC"` field so the consumer can see which TZ
  was applied (additive — pre-v0.8.9 wire consumers ignore it).
- `apps/api/tests/test_uploads_e2e.py` — 4 new e2e tests
  (see Test plan).
- `web/src/lib/api.ts` — the `fetchPlayerTimeline` opts
  signature gains `tz?: string`. The `PlayerTimeline` TS
  interface mirrors the new `tz` field.
- `web/src/components/PlayerTimelineSection.tsx` — the
  Client Component's state machine gains an optional
  `tz` field that flows through to the fetcher call.
  A future enhancement could add a TZ selector UI; for
  v0.8.9, the URL param is the canonical control.
- `web/tests/components/player-timeline-section.test.tsx`
  — 1 new vitest case verifying the `tz` option is
  forwarded to the fetcher.
- `web/tests/app/player-profile-page.test.tsx` — extend the
  `fetchPlayerTimeline` mock type to include the new `tz`
  field (no new test cases; the existing 4 page-level
  cases still pass).

## Files explicitly out of scope

- The `bucket=fight` mode (the `?tz=` param is a no-op for
  the per-fight bucket — the per-fight points keep their
  raw `started_at`).
- A TZ selector UI on the timeline section (deferred to a
  future cycle; the URL param is enough for v0.8.9).
- Per-day bucketing on the **per-fight timeline** (that's
  plan 002; the per-fight timeline is a separate route
  entirely).
- The libs/gw2_analytics aggregators (no Python changes
  needed; the TZ logic lives entirely in
  `apps/api/src/gw2analytics_api/services.py`).

## Steps

1. **Read the existing `?bucket=day` implementation in
   `apps/api/src/gw2analytics_api/routes/players.py`** to
   internalise the route's signature + the helper
   invocation pattern. The route's signature is
   `async def get_player_timeline(account_name: str,
   limit: int = Query(20, ge=1, le=100),
   offset: int = Query(0, ge=0),
   bucket: Literal["fight", "day"] = Query("fight")) -> PlayerTimelineOut:`.
2. **Extend the route signature** to add
   `tz: str = Query("UTC")`. The `zoneinfo.ZoneInfo`
   constructor raises `ZoneInfoNotFoundError` on an
   invalid TZ string; wrap it in a `try/except` that
   raises `HTTPException(422, "invalid timezone: ...")`
   so the error is the canonical FastAPI 422 contract
   (matches the `limit` / `offset` 422 path).
3. **Extend the `day_bucketed_points` helper signature**
   to add `tz: ZoneInfo = ZoneInfo("UTC")`. The helper
   is in `apps/api/src/gw2analytics_api/services.py`.
   The `started_at.date()` call is replaced with
   `started_at.astimezone(tz).date()`. The
   day-bucketed point's `started_at` is set to
   `datetime(year, month, day, tzinfo=timezone.utc)` where
   `(year, month, day)` is the TZ-local date — so the
   wire surface stays in UTC (the JSON serialises as
   `"2024-01-15T00:00:00Z"`) but the date grouping is
   in the analyst's TZ.
4. **Extend the `PlayerTimelineOut` schema** to add
   `tz: str = "UTC"`. The Pydantic model gains the field
   after `bucket`; the `model_config = ConfigDict(from_attributes=True)`
   is unchanged.
5. **Add 4 new e2e tests** (see Test plan).
6. **Extend `web/src/lib/api.ts`** to add the `tz?: string`
   to the `fetchPlayerTimeline` opts + the
   `PlayerTimeline` TS interface.
7. **Extend `web/src/components/PlayerTimelineSection.tsx`**
   to thread the `tz` option through the fetcher call.
   The Client Component's state machine gains an optional
   `tz` field defaulting to `undefined` (which the
   fetcher treats as `"UTC"`).
8. **Run the validation gates** (see Test plan's
   "Validation" subsection).

## Test plan

- **4 new e2e tests in
  `apps/api/tests/test_uploads_e2e.py`**:
  - `test_player_timeline_tz_default_is_utc`: no `?tz=`
    param yields `tz="UTC"` on the response and
    day-bucketed `started_at` is UTC midnight (the
    pre-v0.8.9 behaviour is preserved — backward compat).
  - `test_player_timeline_tz_europe_paris_groups_by_paris_day`:
    2 fights on different UTC days land in different
    Paris-day buckets when `?tz=Europe/Paris&bucket=day`
    is passed (the Paris offset is +01:00 or +02:00
    depending on DST — the test seeds 2 fights at
    `2024-01-15T23:00:00Z` and `2024-01-16T01:00:00Z`
    and asserts the Paris-date grouping differs from
    the UTC-date grouping).
  - `test_player_timeline_tz_america_new_york_groups_by_ny_day`:
    symmetric test for `?tz=America/New_York&bucket=day`.
  - `test_player_timeline_422_when_tz_invalid`:
    `?tz=Mars/Olympus_Mons` returns 422 (the canonical
    FastAPI 422 contract for query-param validation
    failures, matching the `limit` / `offset` 422 path).
- **1 new vitest case in
  `web/tests/components/player-timeline-section.test.tsx`**:
  clicking "Load more" forwards `tz: "Europe/Paris"`
  to the `fetchPlayerTimeline` call (locks the
  Client Component's forwarding contract).
- **No new vitest cases in
  `web/tests/app/player-profile-page.test.tsx`**: the
  page-level test's `fetchPlayerTimeline` mock type
  gains the new `tz` field, but the existing 4
  page-level cases (populated, empty breakdown, 404,
  502) still pass without modification.
- **No new analytics tests** (no Python changes to
  `libs/gw2_analytics`).

## Validation

- `uv run ruff check libs apps`: clean (RUFF=0).
- `uv run mypy --no-incremental libs apps`: clean
  (MYPY=0; the `zoneinfo` import is a stdlib module
  so no new dep).
- `uv run pytest apps/api/tests/test_uploads_e2e.py -k timeline`:
  the 4 new tests pass (PYTEST=0). Pre-existing 4
  v0.8.0 timeline tests still pass (the
  `?tz=` default is `"UTC"` so the pre-v0.8.9
  behaviour is preserved).
- `pnpm tsc --noEmit`: clean (TSC=0).
- `pnpm test:unit`: clean (VITEST=0; the 1 new
  vitest case passes; the existing 70+ cases still
  pass).

## Done criteria

- `?tz=Europe/Paris&bucket=day` on
  `GET /api/v1/players/{account_name:path}/timeline`
  returns fights grouped by Paris-day (2 fights on
  different UTC days that share a Paris day land in
  the same Paris-day bucket).
- `?tz=America/New_York&bucket=day` symmetric
  (grouped by New York day).
- `?tz=Mars/Olympus_Mons` (invalid) returns 422.
- Default behaviour (no `?tz=`) is unchanged
  (`tz="UTC"` on the response; day-bucketed
  `started_at` is UTC midnight; backward compat for
  pre-v0.8.9 wire consumers).
- `?tz=` is a no-op for `bucket=fight` (per-fight
  points keep their raw `started_at`).
- The web/ Client Component forwards the `tz` option
  to the fetcher (the new vitest case locks this).
- 4 new e2e tests + 1 new vitest case pass.
- Pre-existing 4 e2e timeline tests + 70+ vitest
  cases still pass (no regression).

## Maintenance note

- The `?tz=` option is forward-compatible with a
  future TZ selector UI on the timeline section. The
  v0.8.9 spec just threads the URL param through the
  fetcher; a follow-up cycle can add a dropdown
  next to the existing "Per fight" / "Per day" toggle.
- The `?tz=` option is independent of the `?bucket=`
  option. A future `?tz=&bucket=day` combo is the
  only meaningful interaction; `?tz=&bucket=fight`
  is a no-op for the TZ dimension.
- A future v0.9.0 enhancement could surface
  `tz` on `FightOut.started_at` so the per-fight
  page can also be TZ-aware. Out of scope for
  v0.8.9 (the timeline is the only day-mode endpoint).

## Escape hatch

- If the `zoneinfo.ZoneInfo` constructor is not
  available on the target Python version (3.9+),
  STOP and report back. The fallback is the
  third-party `pytz` package, but adding a runtime
  dep for a stdlib feature is a red flag — the
  project should bump the Python minimum to 3.9+ in
  `pyproject.toml` rather than reach for `pytz`.
- If the test for `Europe/Paris` DST handling is
  unstable across Python versions, simplify the test
  to use a fixed `?tz=Asia/Tokyo` (no DST) for the
  cross-day-grouping assertion. The `Europe/Paris`
  DST handling is still exercised by the manual
  QA path; the e2e test just needs to prove the
  TZ switch is wired correctly.
