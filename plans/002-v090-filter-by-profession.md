# Plan 002 — Filter by profession on `/players`

## Context

The v0.7.0 cycle shipped the `PlayerProfileAggregator`
that joins per-fight data into a per-account roll-up,
and the v0.8.0 cycle shipped the `/players` list page
that displays the cross-fight player pool as an
AG Grid table. The table's columns are:

- Account name
- Number of fights
- Total damage dealt
- Total healing
- Total buff-removal
- Most-played profession (the modal profession
  across the player's fights)
- Most-played elite spec
- Last seen (UTC timestamp)

The list page currently has **no filter UI**. An analyst
looking for "all Mesmer players in our pool" has to
scan the full table + sort by profession client-side.
A server-side `?profession=` query param + a dropdown
UI on the page would be a high-leverage addition:
the API can filter in SQL (the
`OrmFightAgent.profession` field is already indexed)
and the UI can render the dropdown as a small
Client Component that updates the URL.

This is a clean M-effort feature:
- 1 new query param on the existing API route
  (`GET /api/v1/players?profession=MESMER`).
- 1 new dropdown UI on the existing page.
- 1 new TS interface in `web/src/lib/api.ts`.
- 6 new pytest cases (5 filter cases + 1
  no-results case).
- 2 new vitest cases (dropdown visibility +
  filter application).

The profession field is a Pydantic enum (the v0.6.0
Profession enum covers all 9 base professions + 9
elite specs); the FastAPI `Query` param can be typed
as the enum + the response can be filtered in the
service layer.

## Goal

A `?profession=` query param on `GET /api/v1/players`
that filters the response to only include players
whose most-played profession matches the param. A
dropdown UI on `/players` lets the user select a
profession + updates the URL via `useRouter` +
`useSearchParams`. The default (no param) is the
current behaviour (all players).

## Files in scope

- `apps/api/src/gw2analytics_api/routes/players.py`
  (extend): add `profession: Profession | None =
  Query(None, description="Filter to players whose
  most-played profession matches")` to the existing
  `GET /api/v1/players` route. The service layer
  filters the SQL query in-place; the response shape
  is unchanged.
- `apps/api/src/gw2analytics_api/services.py` (extend):
  the existing `list_players` service function gains
  an optional `profession: Profession | None` arg
  that adds a WHERE clause to the SQL query when
  present. The function signature is backward-
  compatible (the new arg is optional).
- `apps/api/src/gw2analytics_api/schemas.py` (no
  change): the existing `PlayerSummaryOut` schema
  already includes the `profession` field; no new
  fields are needed.
- `apps/api/tests/test_players.py` (NEW, 6 cases): see
  Test plan.
- `web/src/lib/api.ts` (extend): the existing
  `fetchPlayers` helper gains an optional
  `profession?: Profession` arg that maps to the
  `?profession=` query param. The `Profession` TS
  enum is re-exported from the existing
  `src/lib/api/schema.d.ts` (the codegen output
  already includes it from the FastAPI `Profession`
  enum).
- `web/src/app/players/page.tsx` (extend): a small
  Server Component reads the `searchParams.profession`
  + forwards it to `fetchPlayers`. The page renders
  a new `<ProfessionFilter>` Client Component above
  the AG Grid table.
- `web/src/components/ProfessionFilter.tsx` (NEW, ~30
  lines): a small Client Component that renders a
  `<select>` dropdown with the 9 base professions +
  9 elite specs. The dropdown's `onChange` handler
  uses `useRouter` + `useSearchParams` to update the
  URL. The current value is pre-selected from the
  URL.
- `web/src/components/ProfessionFilter.test.tsx` (NEW,
  2 vitest cases): see Test plan.
- `web/tests/e2e/players.spec.ts` (extend): the
  existing 2 tests gain a new "Profession filter"
  dropdown visibility check + a click-through
  assertion that confirms the `?profession=MESMER`
  URL filters the table to only Mesmer players.

## Files explicitly out of scope

- The player profile page (`/players/[account_name]`)
  — it already shows the player's profession + elite
  spec; no filter is needed there.
- The fight drilldown page (`/fights/[id]`) — the
  per-target trio already shows each target's
  profession + elite spec; no filter is needed.
- A future "filter by elite spec" — would be a
  separate `?elite_spec=` query param + dropdown;
  deferred to v0.9.0+ (the user can already filter
  by base profession and read the elite spec from
  the table).
- A future "filter by date range" — separate
  `?since=` + `?until=` query params; deferred to
  v0.9.0+.
- The AG Grid Enterprise upgrade (Row Grouping would
  enable a group-by-profession view, but is rejected
  by the v0.8.9 audit due to license cost).

## Steps

1. **Read the existing `GET /api/v1/players` route** to
   confirm the current shape (no filter; the response
   is the full player pool).
2. **Extend the service layer** with the
   `profession: Profession | None` arg + a WHERE
   clause when present.
3. **Extend the FastAPI route** with the
   `Query(None)` param + forward it to the service.
4. **Add 6 pytest cases** in
   `apps/api/tests/test_players.py` (see Test plan).
5. **Extend `web/src/lib/api.ts`** with the optional
   `profession` arg on `fetchPlayers`.
6. **Create the `ProfessionFilter` Client Component**
   (the dropdown + the URL update logic).
7. **Mount the filter in `/players/page.tsx`** (above
   the AG Grid table).
8. **Add 2 vitest cases** in
   `web/src/components/ProfessionFilter.test.tsx`
   (see Test plan).
9. **Extend `web/tests/e2e/players.spec.ts`** with the
   dropdown visibility + click-through checks.
10. **Run the validation gates** (see Test plan's
    "Validation" subsection).

## Test plan

- **6 new pytest cases in
  `apps/api/tests/test_players.py`** (NEW file):
  - `test_players_no_filter_returns_full_pool`:
    seed 3 players with different professions
    (Mesmer / Warrior / Necromancer); no `?profession=`
    param -> all 3 in the response.
  - `test_players_filter_by_base_profession`:
    same 3 players; `?profession=MESMER` -> only the
    Mesmer player in the response.
  - `test_players_filter_by_elite_spec`:
    seed 2 Chronomancers + 1 Mirages (all base
    profession Mesmer); `?profession=CHRONOMANCER` ->
    only the 2 Chronomancers (the elite spec field
    is what `?profession=` filters on; the base
    profession field is the discriminator).
    *Note*: this test may need adjustment based on
    the v0.6.0 Profession enum semantics. The escape
    hatch covers a simpler variant.
  - `test_players_filter_with_no_matches`:
    seed 3 players; `?profession=RANGER` -> 0
    players in the response, HTTP 200, empty
    `players: []` array.
  - `test_players_filter_invalid_profession_422`:
    `?profession=NOT_A_REAL_PROFESSION` -> HTTP
    422 (the FastAPI enum validator fires).
  - `test_players_filter_does_not_affect_other_responses`:
    `?profession=MESMER` on the player-detail route
    `GET /api/v1/players/{account_name}` is
    ignored (the detail route doesn't accept the
    filter; the player detail is returned as before).
- **2 new vitest cases in
  `web/src/components/ProfessionFilter.test.tsx`**:
  - `test_profession_filter_renders_dropdown`:
    the component renders a `<select>` with 19
    options (9 base professions + 9 elite specs +
    1 "All" placeholder) + the current value is
    pre-selected from the `?profession=` URL
    search param (or "All" if no param).
  - `test_profession_filter_updates_url_on_change`:
    selecting "Mesmer" from the dropdown updates
    the URL to `?profession=MESMER` via the
    `useRouter` hook (mocked in the test).
- **2 extended e2e tests in
  `web/tests/e2e/players.spec.ts`**: the existing
  2 tests gain a new "Profession filter" dropdown
  visibility check + a click-through assertion
  that confirms the `?profession=MESMER` URL
  filters the table to only Mesmer players.
- **No new vitest cases in
  `web/tests/app/players-page.test.tsx`**: the
  page-level test's `fetchPlayers` mock is no-op'd
  via the existing `setup.ts` global mock; the
  existing page-level cases still pass with the
  new filter added.
- **No new analytics aggregators** (this plan is
  a filter UI + API param; the existing
  `PlayerProfileAggregator` already returns the
  profession field per player).

## Validation

- `uv run ruff check libs apps`: clean (RUFF=0).
- `uv run mypy --no-incremental libs apps`: clean
  (MYPY=0; the new `profession` param on the
  service is fully typed via the existing
  `Profession` Pydantic enum).
- `uv run pytest apps/api/tests/test_players.py -v`:
  6 passed (PYTEST_API=0).
- `pnpm tsc --noEmit`: clean (TSC=0; the new
  `Profession` arg on `fetchPlayers` type-checks).
- `pnpm test:unit`: clean (VITEST=0; 2 new
  filter vitest cases + 79 pre-existing cases
  pass).
- `pnpm exec playwright test`: clean
  (PLAYWRIGHT=0; 2 existing players.spec.ts tests
  extended + 12 other pre-existing tests pass).
- The "Profession filter" dropdown is visible
  on `/players` + the selected value is preserved
  in the URL after a click-through.

## Done criteria

- `GET /api/v1/players?profession=MESMER` returns
  only Mesmer players in the response (verified
  by the 6 pytest cases).
- The "Profession filter" dropdown is visible on
  `/players` + selecting a profession updates the
  URL + filters the table to only the matching
  players.
- 6 new pytest cases + 2 new vitest cases + 2
  extended e2e tests pass; pre-existing tests
  still pass (no regression).
- The visual-regression spec still passes 8/8
  (the new dropdown doesn't change any of the
  8 tracked PNGs in a meaningful way; if it
  does, refresh the affected baselines as a
  follow-up commit before merging this plan).

## Maintenance note

- A future "filter by elite spec" can re-use
  the same `ProfessionFilter` Client Component
  with a separate `?elite_spec=` query param;
  the underlying `Profession` enum already
  covers both base + elite.
- A future "filter by date range" would be a
  separate `<DateRangeFilter>` Client Component
  + `?since=` + `?until=` query params. Out
  of scope for v0.9.0.
- The profession filter is per-navigation
  (not persisted); a future v0.9.0+ could
  store the filter in `localStorage` and apply
  it on every page load. Out of scope.

## Escape hatch

- If the `Profession` Pydantic enum doesn't
  cover both base + elite specs (the v0.6.0
  enum is the source of truth), simplify the
  filter to base professions only (9 options
  instead of 19). The elite spec test is the
  one that may need adjustment; the escape
  hatch covers a simpler variant.
- If the `WHERE` clause for the profession
  filter doesn't compose cleanly with the
  existing SQL (e.g. the `most_played_profession`
  is computed in a subquery), STOP and report
  back. The fallback is to filter in Python
  (after the SQL query returns the full pool);
  the performance hit is negligible for the
  current dataset size.
- If the `useRouter` + `useSearchParams`
  Client Component pattern doesn't work
  cleanly with the existing Server Component
  page (e.g. the dropdown is rendered above
  the table but the table doesn't re-fetch
  when the URL changes), STOP and report back.
  The fallback is to make the entire `/players`
  page a Client Component (the AG Grid is
  already client-rendered; the Server Component
  shell just provides the initial data). The
  trade-off is a slight increase in JS shipped
  to the client.
