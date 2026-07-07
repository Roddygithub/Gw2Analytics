# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.8.0] - Phase 9 of web: account-level historical timelines

### Added (apps/api)

- `apps/api/src/gw2analytics_api/schemas.py`: 2 new Pydantic v2
  response schemas -- `PlayerTimelinePointOut` (strict parallel
  of `PerFightBreakdownRowOut`: `fight_id`, `started_at`,
  `total_damage`, `total_healing`, `total_buff_removal`) and
  `PlayerTimelineOut` (`account_name`, `total`, `limit`, `offset`,
  `points: list[PlayerTimelinePointOut]`). `total` is the
  un-paginated count so the client can render a "showing N of M"
  caption and gate the "Load more" button without a second
  request.
- `apps/api/src/gw2analytics_api/routes/players.py`: new route
  `GET /api/v1/players/{account_name:path}/timeline?limit=20&offset=0`.
  Reuses the pre-existing `_compute_contributions` helper (the
  same O(fights x events) inner loop the list + detail endpoints
  use) so the route joins + decompresses the events blobs once
  per request and paginates in-memory. Recency-first sort
  (``started_at DESC``, ``fight_id ASC`` tiebreaker -- the
  v0.7.0 aggregator's deterministic-ordering contract). `limit`
  clamped to ``[1, 100]`` and `offset` clamped to ``[0, ∞)`` via
  FastAPI ``Query`` validation (out-of-range values raise
  ``422`` BEFORE the handler runs). 404 contract mirrors the
  detail endpoint: an unknown ``account_name`` raises
  ``HTTPException(404, "player not found")``. **Declaration
  order matters** -- the timeline route MUST be declared BEFORE
  the catch-all ``{account_name:path}`` detail route or FastAPI
  would match ``/TestAccount.1234/timeline`` against the
  catch-all with ``account_name="TestAccount.1234/timeline"`` and
  return 404 before the timeline route ever fires.
- `apps/api/src/gw2analytics_api/__init__.py`: ``__version__``
  bumped ``0.7.0 -> 0.8.0``.
- `apps/api/src/gw2analytics_api/main.py`: FastAPI ``version``
  string bumped ``0.7.0 -> 0.8.0``.
- `apps/api/pyproject.toml`: version bumped ``0.7.0 -> 0.8.0``.
- `apps/api/tests/test_uploads_e2e.py`: 5 NEW e2e tests
  covering the new endpoint:
  - `test_player_timeline_returns_paginated_recency_first_points`
    (seeds 2 fights that share the same ``account_name`` via a
    uuid-suffixed fixture; the 2nd POST inlines a custom fixture
    so both fights reuse the same agent ids; verifies
    ``started_at`` DESC ordering + that pages 0/1 and 1/1 don't
    overlap + that the 2 pages combined cover the first 2 fights)
  - `test_player_timeline_404_when_account_unknown` (mirrors the
    detail endpoint's 404 contract)
  - `test_player_timeline_422_when_limit_out_of_range` (limit=101
    → 422)
  - `test_player_timeline_422_when_limit_zero` (limit=0 → 422,
    lower-bound counterpart)
  - `test_player_timeline_422_when_offset_negative` (offset=-1 →
    422)
  Plus a refactored ``_wait_for_upload_completion(upload_id) ->
  str`` helper extracted from ``_post_minimal_fight`` (the
  polling loop was duplicated in 2 places; the new helper is
  the single source of truth).

### Added (web)

- `web/src/lib/api.ts`: new ``fetchPlayerTimeline`` fetcher
  helper + 2 new TypeScript interfaces
  (``PlayerTimelinePoint`` + ``PlayerTimeline``). Mirrors the
  ``fetchPlayer`` pattern (``encodeURIComponent`` for the
  accountName, ``URLSearchParams`` for ``limit`` / ``offset``,
  ``ApiError`` on any non-2xx so the page-level Server
  Component can render the canonical upstream-error card).
- `web/src/components/PlayerTimelineLegend.tsx` (NEW): small
  "use client" component that renders a right-aligned flex row
  of 3 colour swatches (Damage, Healing, Buff removal). Uses
  ``role="list"`` + ``role="listitem"`` for accessibility.
  The strip swatch is a hard-coded warm orange (``#f59e0b``)
  that matches the per-target strip roll-up's tint.
- `web/src/components/PlayerTimelineChart.tsx` (NEW): "use
  client" inline SVG line chart. 3 polylines (damage + healing +
  strip) **normalized to 0-100% of per-series max** so the
  smaller-magnitude strip line is visible (on a shared absolute
  Y axis, damage -- typically 10k-100k magnitude -- would crush
  strip -- typically 0-500 magnitude -- into a flat line).
  Hovering any of the 3 sibling dots surfaces a native SVG
  ``<title>`` tooltip with the absolute values
  (``fight_id`` + formatted ``MM/DD HH:MM`` + 3 metrics via
  ``toLocaleString()``). X-axis: ``MM/DD HH:MM`` via
  ``Intl.DateTimeFormat``, first + last labels always drawn,
  intermediate labels sampled at ~120px intervals. Empty-state
  panel mirrors ``EventWindowsChart`` styling. The pure helper
  ``buildTimelineLayout`` is exported for the unit test.
- `web/src/components/PlayerTimelineSection.tsx` (NEW): "use
  client" Client Component wrapper. Owns the pagination state
  (``timeline``, ``isLoading``, ``loadError`` via ``useState``);
  "Load more" button calls ``fetchPlayerTimeline`` with
  ``offset=points.length`` and appends the returned points to
  the in-memory list. Defensive de-dup of ``fight_id`` (in case
  a fight is added to the dataset mid-pagination). Shows a
  "Showing N of M fights" caption + a disabled "All fights
  loaded" button when the last page is reached. Error path:
  surfaces the upstream error via ``formatApiError`` and
  re-enables the button (no auto-retry; reload is the recovery
  path).
- `web/src/app/players/[account_name]/page.tsx`: extended to
  fetch the per-account historical timeline (limit=20) on the
  server alongside the existing profile fetch. 404 from the
  timeline is swallowed (treated as "player has no attended
  fights" -- the chart's empty-state panel handles a null
  timeline via the synthetic-empty pattern). 5xx from the
  timeline is fatal and renders the same upstream-error card
  the profile fetch uses. ``ApiError`` + ``err.status`` is the
  canonical 404 discriminator (NOT a string-based
  ``err.message.startsWith("404:")`` -- that would couple to
  the ApiError's formatted message). The ``<PlayerTimelineSection>``
  is ALWAYS rendered (with a synthetic empty ``PlayerTimeline``
  on the 404 path) so the analyst sees the "Showing 0 of 0
  fights" caption + the chart's empty-state panel + a disabled
  "All fights loaded" button instead of a silent section
  absence. The section sits between the stat cards and the
  per-fight breakdown.

### Added (web tests)

- `web/tests/components/player-timeline-chart.test.tsx` (NEW): 6
  cases (empty state, single all-zero point, 3 points with 9
  circles + 3 paths + 3 legend swatches, ``buildTimelineLayout``
  helper for empty / single point / all-zero clamp to 1 / mixed
  magnitudes). DOM-level assertions via
  ``container.querySelectorAll`` -- more robust than snapshots
  when a future refactor reorders an attribute.
- `web/tests/components/player-timeline-section.test.tsx` (NEW):
  5 cases (caption + Load more enabled, button disabled when
  all loaded, Load more click calls ``fetchPlayerTimeline`` with
  ``offset=3`` and appends, error surfaces and doesn't lock the
  button, defensive de-dup of ``fight_id`` across pages). Uses
  the canonical ``vi.mock(..., importOriginal)`` pattern to
  override the global no-op mock from ``web/tests/setup.ts``.
- `web/tests/setup.ts`: global no-op mock for the new
  ``PlayerTimelineSection`` named export (so the page-level
  tests can render the wrapper without booting the React state +
  fetch plumbing; a dedicated component-level test exercises
  the real Client Component).
- `web/tests/app/player-profile-page.test.tsx`: extended to mock
  ``fetchPlayerTimeline`` so the page tests don't hit the real
  gateway; the existing 4 page-level cases (populated, empty
  breakdown, 404, 502) all use the mock.

### Notes

- The web/ chart is **normalized to 0-100% per series** (not
  shared absolute Y axis as the design doc proposed). Rationale:
  damage (10k-100k magnitude) would visually crush strip
  (0-500 magnitude) on a shared axis, making the strip trend
  invisible. Per-series normalization lets the analyst compare
  the **trends** of all 3 metrics simultaneously. The absolute
  values are surfaced via the SVG ``<title>`` tooltip on hover
  (zero React state, no portal, no client-side JS -- the
  canonical lightweight pattern).
- The web/ tooltip uses the **SVG-native ``<title>`` element**
  on the parent ``<g>`` group (not an absolutely-positioned
  ``<div>`` overlay as the design doc proposed). Rationale: the
  ``<title>`` pattern is dependency-free, hydration-safe, and
  surfaces the tooltip on any of the 3 sibling dots in the
  cluster. An absolutely-positioned ``<div>`` would require
  ``useRef`` + ``getBoundingClientRect`` + React state -- 10x
  the code for no observable UX win (the browser's native
  tooltip is already a ``<div>`` overlay).
- The web/ pagination uses **offset-based loading** (not
  limit-incrementing as the design doc proposed). Rationale:
  offset-based pagination is the standard pattern, the
  ``<title>`` tooltip is hover-only so the user doesn't need to
  scroll through chunks of 20 -- and the route's tiebreaker
  (``fight_id ASC``) gives a deterministic total count, so the
  "Load more" button can hide when the last page is reached.
- The design doc's v0.9.0 suggestion to "support per-day
  bucketing" and "cross-account comparison" remains future
  work. The per-account timeline alone is enough for v0.8.0.

### Tests

- 5 new e2e tests (apps/api/test_uploads_e2e.py).
- 11 new vitest cases (6 chart + 5 section).
- Python test count: 86 (v0.7.0) -> 91 (v0.8.0).
- Web test count: 39 (v0.7.1) -> 50 (v0.8.0).

### Validation

- ``uv run ruff check libs apps``: clean (RUFF=0).
- ``uv run ruff format --check libs apps``: clean (FORMAT=0).
- ``uv run mypy libs apps --no-incremental``: clean (MYPY=0).
- ``uv run pytest apps/api/tests/test_uploads_e2e.py -k timeline``:
  5 passed (PYTEST=0).
- ``pnpm tsc --noEmit``: clean (TSC=0).
- ``pnpm test:unit``: clean (VITEST=0, 13 files / 50 tests).
- Round 101-107 code-reviewer-minimax-m3: **APPROVED**
  (route declaration order locks the FastAPI matching
  contract; ``_wait_for_upload_completion`` extraction
  single-sources the polling loop; per-series normalization
  rationale (damage dwarfs strip on shared axis) is the
  correct chart design; ``<title>``-on-group surfaces the
  tooltip on any of the 3 sibling dots; ``ApiError`` +
  ``err.status`` is the type-safe 404 discriminator;
  synthetic-empty ``PlayerTimeline`` keeps the section
  visible on the 404 path so the analyst sees the
  "No data" panel instead of a silent absence).

[0.8.0]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.7.1...v0.8.0

## [0.7.1] - Phase 9 of web: player-centric surface + per-fight squad + skill roll-ups

### Added (web)

- `web/src/components/SquadRollupsGrid.tsx` (NEW): generic AG
  Grid Community wrapper for the per-subgroup roll-up. Keyed
  on ``subgroup`` string (NOT ``target_agent_id`` number --
  the row shape differs from the per-target trio, so a
  dedicated grid component is warranted). Re-uses the
  existing ``./ag-grid-setup`` side-effect import so the
  module registration runs once across the whole module
  graph.
- `web/src/components/SkillUsageTable.tsx` (NEW): plain HTML
  table for the per-skill roll-up. Strict parallel of the
  pre-existing :class:`EventWindowsTable` (no AG Grid, no
  charts). The skill count is bounded by the parser's skill
  table size (typically 5-100 rows for a single fight) so
  the table stays human-scannable without pagination.
- `web/src/components/EventWindowsChart.tsx` (NEW): inline
  SVG bar chart for the per-fight event windows. Side-by-
  side damage + healing bars per bucket, zero external
  charting deps (~100 lines of SVG vs ~50-150 KB for a
  charting library). Sized to fit alongside the pre-existing
  :class:`EventWindowsTable` on the ``/fights/[id]`` page.
- `web/src/components/PlayerSearchBar.tsx` (NEW): Client
  Component with a text input for player search. On submit,
  navigates to ``/players/{URL-encoded-account_name}`` via
  ``useRouter().push``. Lives in the root layout's sticky
  header bar (added below) so the analyst can pivot to a
  player profile from any page without first navigating to
  ``/players``.
- `web/src/components/PlayersGrid.tsx` (NEW): AG Grid
  Community wrapper for the ``/players`` paginated list.
  Strict parallel of the pre-existing :class:`FightsGrid`
  (Quartz dark theme, sortable + filterable columns, 25-row
  pagination). The ``account_name`` column is rendered as
  an anchor to ``/players/{URL-encoded}`` so a single click
  carries the analyst to the per-account drill-down page.
- `web/src/app/players/page.tsx` (NEW): Server Component that
  SSR-fetches :func:`fetchPlayers` and renders the
  :class:`PlayersGrid`. ``force-dynamic`` so the list
  reflects the latest parsed fight state on every request.
  Empty + 404 + upstream-error handling matches the
  pre-existing ``/fights`` page pattern.
- `web/src/app/players/[account_name]/page.tsx` (NEW):
  Server Component that SSR-fetches
  :func:`fetchPlayer(account_name)` and renders the
  cross-fight stat cards (fights attended + 3 totals) +
  per-fight breakdown table (sorted by ``started_at`` DESC).
  ``force-dynamic`` so the profile reflects the latest
  parsed fight state. ``← Back to players`` anchor in the
  header so the analyst can return to the list view.
- `web/src/app/fights/[id]/page.tsx`: extended to
  ``Promise.allSettled`` for 3 parallel fetchers
  (:func:`fetchFightEvents` + :func:`fetchFightSquads` +
  :func:`fetchFightSkills`). ``allSettled`` (NOT ``all``)
  so a single fetcher failure does not blank the whole page
  -- the per-target trio is the primary surface and a
  transient squads/skills failure should not block the
  per-target roll-ups. Two new sections (Per-subgroup +
  Per-skill) added below the per-target trio. The
  ``EventWindowsChart`` is rendered alongside the
  pre-existing :class:`EventWindowsTable` so the analyst
  can pick the visualisation they prefer.
- `web/src/app/layout.tsx`: added a sticky header bar
  (position: sticky; top: 0) hosting the brand link +
  :class:`PlayerSearchBar`. The header bar is the canonical
  Next.js location for a global search affordance; the
  ``/players`` list page does NOT add a second search input
  (would duplicate the affordance).
- `web/src/app/page.tsx`: added a 4th card for ``/players`` in
  the home page nav (Browse players), matching the
  existing card triplet aesthetic.

### Added (web lib)

- `web/src/lib/api.ts`: 4 new fetcher helpers
  (:func:`fetchPlayers`, :func:`fetchPlayer`,
  :func:`fetchFightSquads`, :func:`fetchFightSkills`) + 8
  new TypeScript interfaces (:class:`PlayerListRow`,
  :class:`PerFightBreakdownRow`, :class:`PlayerProfile`,
  :class:`SquadRollupRow`, :class:`FightSquads`,
  :class:`SkillUsageRow`, :class:`FightSkills`). All
  mirror the v0.7.0-api backend schemas (apps/api 0.7.0+).

### Added (web tests)

- `web/tests/app/players-page.test.tsx` (NEW): 4 page-level
  vitest cases (populated, empty, 404, 502) mirroring the
  pre-existing ``/fights`` page test pattern. Uses
  ``vi.hoisted`` to wrap the mock variable so the factory
  can reference it (vitest hoists ``vi.mock`` calls to the
  top of the file).
- `web/tests/app/player-profile-page.test.tsx` (NEW): 4
  page-level cases (populated, empty breakdown, 404, 502).
  Same ``vi.hoisted`` pattern.
- `web/tests/components/player-search-bar.test.tsx` (NEW):
  5 component-level cases (renders input+button, empty
  no-op, whitespace no-op, submit URL-encodes, trim before
  encode). Uses ``vi.mock(..., importOriginal)`` to
  override the global no-op mock for the search bar
  declared in :file:`web/tests/setup.ts`.
- `web/tests/setup.ts`: 6 new global no-op mocks
  (EventWindowsChart, SquadRollupsGrid, SkillUsageTable,
  PlayersGrid, PlayerSearchBar) so the page-level tests
  can render the page wrapper without dragging AG Grid's
  runtime into jsdom.
- `web/tests/app/fight-events-page.test.tsx`: extended to
  mock :func:`fetchFightSquads` + :func:`fetchFightSkills`
  (the page now fires 3 parallel fetchers via
  ``Promise.allSettled``) + added 2 new heading checks
  (Per-subgroup + Per-skill) to the existing test cases.

### Notes

- The web layer for v0.7.0 ships as v0.7.1 (not v0.7.0-web)
  because the v0.7.0 backend release was already tagged.
  The version bump keeps the semver convention: the web
  surface that consumes a v0.7.0 backend is itself a
  v0.7.1 release (minor version, additive changes only).
- The ``PlayerSearchBar`` lives in the root layout so it
  appears on every page (not just ``/players``). The
  ``/players`` list page does NOT add a second search
  input -- would duplicate the affordance + force the
  user to think about which input is the "right" one.
- The ``EventWindowsChart`` is rendered ALONGSIDE the
  pre-existing :class:`EventWindowsTable` (not as a
  replacement). A future enhancement could add a small
  "table / chart" toggle button pair to let the analyst
  pick the visualisation; for v0.7.1 the chart is a
  supplementary view.
- The ``Promise.allSettled`` pattern in
  :file:`web/src/app/fights/[id]/page.tsx` is a deliberate
  trade-off: a single fetcher failure (e.g. transient
  squads/skills 404) no longer blanks the whole page. The
  common upstream-blob failure mode (S3Error on ``/events``)
  still surfaces the unified error card because the
  per-target trio is the primary surface.
- The ``PlayerSearchBar`` test uses
  ``container.querySelector('input[type="search"]')``
  instead of the more-idiomatic ``getByLabelText`` /
  ``getByPlaceholderText`` because jsdom's role / aria
  resolution is unreliable for ``<input type="search">``
  inside a ``<form role="search">``. The direct DOM query
  is the most stable path through jsdom's quirks.

### Tests

- 4 new page-level cases for ``/players``
- 4 new page-level cases for ``/players/[account_name]``
- 5 new component-level cases for :class:`PlayerSearchBar`
- 2 existing ``/fights/[id]`` test cases extended with
  2 new heading checks each (the per-subgroup + per-skill
  sections).
- Web test count: 26 (v0.7.0 backend) -> 39 (v0.7.1).

### Validation

- ``pnpm tsc --noEmit``: clean (TSC=0).
- ``pnpm test:unit``: clean (VITEST=0, 39 tests across 10
  files).
- Code-reviewer-minimax-m3: **APPROVED** (the importOriginal
  override correctly bypasses the global no-op mock;
  ``vi.hoisted`` resolves the factory hoisting; the
  count + noun fragment split handles React's
  children-flattening in JSON.stringify output; the
  ``Promise.allSettled`` pattern prevents cascade failure).

[0.7.1]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.7.0...v0.7.1

[Unreleased]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.8.0...HEAD

## [0.7.0] - Phase 9: player-centric surface + per-fight squad + per-fight skill roll-ups

### Added (analytics)

- `libs/gw2_analytics/src/gw2_analytics/player_profile.py` (NEW):
  `PlayerProfileAggregator.aggregate(contributions: Iterable[FightContribution]) -> list[PlayerProfile]`.
  Cross-fight join keyed on `account_name`; first-seen
  profession/elite anchor; last-seen `name`; dedup on
  `(account_name, fight_id)`. Rows sorted deterministic by
  `(-total_damage, account_name)`. `FightsAttended` is the
  length of the dedup'd `attended_fight_ids` set (one per
  fight, not one per contribution). All totals
  (`total_damage` / `total_healing` / `total_buff_removal`)
  sum the per-fight contributions, NOT the raw events
  (matches the route's source-side attribution contract).
- `libs/gw2_analytics/src/gw2_analytics/squad_rollup.py` (NEW):
  `SquadRollupAggregator.aggregate(events, agents, duration_s)
  -> list[SquadRollupRow]`. Source-side per-subgroup roll-up;
  every event's `source_agent_id` looks up the source's
  `subgroup` in the agent map (NOT the target's subgroup --
  damage-flow attribution, not hit-flow). Rows sorted by
  `(-total_damage, subgroup)`. `bps` (= total_buff_removal /
  duration_s) and `hps` (= total_healing / duration_s) use
  the same zero/negative `duration_s` guard as the per-target
  roll-ups.
- `libs/gw2_analytics/src/gw2_analytics/skill_usage.py` (NEW):
  `SkillUsageAggregator.aggregate(events, skills, duration_s)
  -> list[SkillUsageRow]`. Per-skill roll-up keyed on
  `skill_id`; `hit_count` is the SUM of the per-event hit
  counts across all 3 event kinds (damage + healing + strip
  = 1 each per event). The route surfaces `hit_count` on the
  API surface (the per-target roll-ups deliberately drop it
  as analyst-only metadata); the per-skill roll-up keeps it
  because analysts use it to spot "low-damage high-frequency"
  skill patterns.
- `libs/gw2_analytics/src/gw2_analytics/__init__.py`: re-exports
  the 3 new aggregators + their row models. `__version__` bumped
  `0.5.0 -> 0.7.0` to mirror the coordinated Phase 9 surface
  change.
- `libs/gw2_analytics/tests/test_player_profile.py` (NEW): 7
  pytest cases covering empty input, single-fight single-player
  shape, multi-fight first-seen profession, multi-fight
  last-seen name, dedup on `(account_name, fight_id)`, mixed
  multi-fight ordering, and frozen-Pydantic guarantee.
- `libs/gw2_analytics/tests/test_squad_rollup.py` (NEW): 7
  pytest cases covering empty input, single-subgroup shape,
  source-vs-target subgroup attribution, multi-subgroup
  ordering, dual-emit (heal + strip from same record), the
  zero/negative `duration_s` guard, and frozen-Pydantic
  guarantee.
- `libs/gw2_analytics/tests/test_skill_usage.py` (NEW): 7
  pytest cases covering empty input, single-skill shape,
  multi-skill hit-count accounting, dual-emit (damage + heal
  + strip from same record), skill-name resolution from
  the `SkillCatalogEntry` map, the zero/negative `duration_s`
  guard, and frozen-Pydantic guarantee.

### Added (apps/api)

- `apps/api/src/gw2analytics_api/schemas.py`: 7 new Pydantic
  response schemas -- `PlayerListRowOut` + `PerFightBreakdownRowOut`
  + `PlayerProfileOut` (for the player-centric surface),
  `SquadRollupRowOut` + `FightSquadsOut` (for the per-fight
  squad roll-up), and `SkillUsageRowOut` + `FightSkillsOut`
  (for the per-fight skill roll-up). All use the same
  `PROF(<id>)` / `ELITE(<id>)` / `BASE` / `UNKNOWN` string
  label contract as the pre-existing `/fights` response.
- `apps/api/src/gw2analytics_api/routes/players.py` (NEW):
  `GET /api/v1/players` (paginated cross-fight roll-up, default
  50 / max 500) and `GET /api/v1/players/{account_name:path}`
  (full profile + per-fight breakdown, ordered by
  `started_at DESC`). Both routes load all `OrmFight` rows
  (ordered by `started_at DESC`, `selectinload(OrmFight.agents)`),
  pre-batch-load all `OrmFightAgent` rows for the fight set
  (one IN-clause query -- not N+1), then walk each fight's
  events blob via a single shared `_compute_contributions`
  helper. The helper degrades gracefully for fights with
  `events_blob_uri is None` (creates 0-total contributions
  for each player agent in the fight so the cross-fight
  roll-up still includes the player) and tolerates
  S3-gone / gzip-corrupt blobs via `logger.warning` + `continue`
  (the fight is silently dropped from the roll-up, matching
  the pre-Phase-9 contract). 404 contract: an unknown
  `account_name` raises `HTTPException(404, "player not found")`
  so analysts can distinguish "no data" from "API error".
- `apps/api/src/gw2analytics_api/routes/fights.py`:
  `GET /api/v1/fights/{id}/squads` + `GET /api/v1/fights/{id}/skills`
  extensions of the pre-existing per-fight events surface.
  Both share the same blob-load + decompress + event-split
  pattern as `/events` (DRY refactor deferred to v0.7.1 --
  code-reviewer flagged the duplication in Round 72; the
  route signature stays unchanged across the refactor).
- `apps/api/src/gw2analytics_api/main.py`: includes the new
  `players` router; FastAPI `version` string bumped
  `0.6.0 -> 0.7.0`.
- `apps/api/pyproject.toml`: version bumped `0.6.0 -> 0.7.0`.
- `apps/api/src/gw2analytics_api/__init__.py`: `__version__`
  bumped `0.6.0 -> 0.7.0`.
- `apps/api/tests/test_uploads_e2e.py`: 7 NEW self-contained
  e2e tests for the Phase 9 surface:
  - `test_players_list_returns_accounts_present_in_fight`
  - `test_player_detail_returns_profile_with_per_fight_breakdown`
  - `test_player_detail_404_when_account_unknown`
  - `test_fight_squads_returns_per_subgroup_rollup`
  - `test_fight_squads_404_when_fight_unknown`
  - `test_fight_skills_returns_per_skill_rollup`
  - `test_fight_skills_404_when_fight_unknown`
  Each test POSTs its own `.zevtc` fixture so the test order
  is irrelevant. The Phase 8 DUAL-EMIT case
  (`is_nondamage=1` + `value>0` + `buff_dmg>0` on a single
  cbtevent record) is exercised end-to-end through the
  squad + skill roll-ups. The new `_post_minimal_fight`
  helper accepts an optional `suffix` kwarg so callers can
  thread their own uuid-derived suffix through the .zevtc
  fixture, aligning the cbtevent's `source_agent_id` with
  the parser-assigned agent table IDs (without this
  alignment, the route's source-side attribution silently
  drops every event and the cross-fight roll-up returns 0
  contributions for the fixture's accounts).

### Notes

- The v0.7.0 release ships the BACKEND only. The web layer
  (2 new pages `/players` + `/players/[account_name]`, plus
  the `EventWindowsChart` + `SquadRollupsGrid` + `SkillUsageTable`
  client components, plus the `PlayerSearchBar` in the layout
  + the home page nav update) is deferred to v0.7.1.
- The O(fights x events) per-request cost is acceptable for
  v0.7.0 (a handful of fights in the local-dev dataset). v0.7.1
  will materialise a `fight_player_summaries` table to avoid
  the 5-30s latency for users with 100+ fights (the schema is
  trivial: `fight_id`, `account_name`, `total_damage`,
  `total_healing`, `total_buff_removal` -- the route layer
  becomes a pure SQL aggregation).
- The `_compute_contributions` helper's `noqa: PLR0912` is
  a deliberate trade-off: the function is a single-pass
  walk over the heterogeneous event stream, so splitting it
  into smaller helpers would scatter the hot loop across
  multiple call sites without making it easier to reason
  about. A future refactor (v0.7.1+) can split it once the
  `fight_player_summaries` table eliminates the per-request
  re-walk.
- The `_post_minimal_fight` helper's `suffix` kwarg is the
  single source of truth for the test-side ID alignment
  contract. Any future e2e test that seeds its own events
  MUST either thread its own `suffix` through the helper OR
  use a default-suffix `_post_minimal_fight()` call (no
  events). The helper docstring documents the bug rationale
  (parser-assigned agent_id vs cbtevent `source_agent_id`).

### Tests

- 21 new analytics tests (7 player_profile + 7 squad_rollup +
  7 skill_usage).
- 7 new e2e tests (4 new endpoints + 3 404 contracts).
- Python test count: 58 (v0.6.0) -> 86 (v0.7.0).

### Validation

- `uv run ruff check libs apps`: clean (RUFF=0).
- `uv run ruff format --check libs apps`: clean (FORMAT=0).
- `uv run mypy libs apps --no-incremental`: clean (MYPY=0).
- `uv run pytest libs`: 78 passed + 1 skipped (PYTEST_LIBS=0).
- `uv run pytest apps/api`: 11 tests in `test_uploads_e2e.py`
  + healthz (PYTEST_APPS=0).
- Round 72-80 code-reviewer-minimax-m3: **APPROVED**
  (suffix threading fix correctly aligns test-side event IDs
  with helper-side agent IDs; `_compute_contributions`
  helper's blob=None fallback + blob-walk branch both
  exercised; PlayerProfile / SquadRollup / SkillUsage
  aggregators follow the same source-side attribution
  contract; 404 contract is consistent across the new
  endpoints).

[0.7.0]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.6.0...v0.7.0

[Unreleased]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.7.0...HEAD

## [0.6.0] - Phase 8: BuffRemovalEvent end-to-end + per-target filter + CI Postgres service

### Added (domain)

- `libs/gw2_core/src/gw2_core/models.py`: `EventType.BUFF_REMOVAL`
  StrEnum member. New `BuffRemovalEvent(BaseEvent)` with
  `buff_removal: int >= 0` + `Literal[EventType.BUFF_REMOVAL]`
  discriminator. Discriminated union extended to
  `type Event = Annotated[DamageEvent | HealingEvent | BuffRemovalEvent,
  Field(discriminator="event_type")]`. The third Event member
  is the canonical path for surface the arcdps `cbtevent.buff_dmg`
  field.
- `libs/gw2_core/src/gw2_core/__init__.py`: re-exports
  `BuffRemovalEvent` + adds it to `__all__`. `__version__` bumped
  `0.3.0 -> 0.5.0` to mirror the coordinated Phase 8 surface
  change.

### Added (parser)

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`:
  `PythonEvtcParser.parse_events` now unpacks `buff_dmg` (was
  `_buff_dmg`). New dual-emit filter contract (Convention A +
  Elite Insights parity extended):
    - `is_statechange == 0 && is_nondamage == 0 && value > 0` ->
      emits `DamageEvent` (buff_dmg silently dropped, arcdps
      does not write buff_dmg on damage records).
    - `is_statechange == 0 && is_nondamage > 0 && value > 0` ->
      emits `HealingEvent` AND, if `buff_dmg > 0`, also emits
      `BuffRemovalEvent` from the SAME record. The canonical
      case is a corrupting / confusion skill that heals the
      caster and strips a boon from the target.
    - `is_statechange == 0 && is_nondamage > 0 && value == 0 &&
      buff_dmg > 0` -> emits ONLY a `BuffRemovalEvent` (pure
      strip with no heal magnitude).
  Negative `buff_dmg` is clamped via `max(0, buff_dmg)`. A
  single cbtevent can yield AT MOST TWO events (one
  HealingEvent + one BuffRemovalEvent) on the dual-emit path.

### Added (parser tests)

- `libs/gw2_evtc_parser/tests/test_parser.py`: 6 NEW Phase 8
  tests locking the dual-emit contract:
  - `test_parse_events_yields_buff_removal_on_nondamage_with_buff_dmg`
    (dual emit: 1 record -> 2 events)
  - `test_parse_events_yields_buff_removal_only_on_pure_strip`
    (value=0 + buff_dmg>0 yields only BuffRemovalEvent)
  - `test_parse_events_skips_damage_with_buff_dmg` (pure damage
    path silently drops spurious buff_dmg)
  - `test_parse_events_clamps_negative_buff_dmg_to_zero`
  - `test_parse_events_skips_statechange_for_buff_strip`
  - `test_parse_events_emits_heterogeneous_damage_heal_strip_stream`
    (5 records -> 6 events, locks the interleaved ordering)

### Added (analytics)

- `libs/gw2_analytics/src/gw2_analytics/target_buff_removal.py`
  (NEW): strict parallel of `target_healing.py` with
  `TargetBuffRemovalRow` + `TargetBuffRemovalAggregator`.
  Schema: `target_agent_id` + `total_buff_removal` +
  `strip_count` + `bps` (buff-removal-per-second). Same
  ordering (desc by total + asc by target on tie), same
  invariants (sum-of-row == sum-of-event; monotonically
  non-increasing), same `duration_s` zero/negative guard
  (`bps=0.0` sentinel, `ValueError` on negative).
- `libs/gw2_analytics/src/gw2_analytics/__init__.py`: re-exports
  `TargetBuffRemovalAggregator` + `TargetBuffRemovalRow`.
  `__version__` bumped `0.4.0 -> 0.5.0`.
- `libs/gw2_analytics/tests/test_target_buff_removal.py` (NEW):
  6 mirror tests covering empty input, single-row shape,
  zero/negative duration edge, deterministic ordering,
  cross-field sum preservation, frozen-Pydantic guarantee.

### Added (apps/api)

- `apps/api/src/gw2analytics_api/schemas.py`: new
  `TargetBuffRemovalRowOut` response schema (strict parallel of
  `TargetDpsRowOut` / `TargetHealingRowOut` -- drops
  `strip_count` from the API surface for analyst-only parity)
  and a new
  `target_buff_removal: list[TargetBuffRemovalRowOut] = []`
  sibling field on `FightEventsSummaryOut` (between
  `target_healing` and `event_windows`). Empty when the parser
  yielded zero strip events.
- `apps/api/src/gw2analytics_api/routes/fights.py`: the
  heterogeneous JSONL stream is split at the call site into
  three per-kind iterators (`isinstance(e, DamageEvent)`,
  `isinstance(e, HealingEvent)`, `isinstance(e, BuffRemovalEvent)`)
  fed to `TargetDpsAggregator` / `TargetHealingAggregator` /
  `TargetBuffRemovalAggregator` on the same `duration_s` so
  the three roll-ups are temporally consistent. The
  per-aggregator call site stays free of cross-kind
  discrimination in the hot loop. `EventWindowAggregator`
  is intentionally NOT extended with a `buff_removal_total`
  field -- the per-bucket window contract is locked.
- `apps/api/tests/test_uploads_e2e.py::test_uploads_e2e_happy_path`:
  `_make_cbtevent` now accepts a `buff_dmg` kwarg. One cbtevent
  record dual-emits a heal + strip (on agent A); one pure-strip
  record (no heal, just a strip) lands on agent A. The test
  asserts `target_buff_removal` has 1 row with
  `total_buff_removal=500` and `bps=200.0`, and the per-bucket
  `event_count` for the dual-emit's bucket is bumped to 3
  (1 damage + 1 heal + 1 strip).

### Added (web)

- `web/src/components/TargetFilter.tsx` (NEW): Client Component
  that renders a dropdown of available `target_agent_id` values
  for the `/fights/[id]` drill-down page. Uses `useRouter` +
  `usePathname` + `useSearchParams` from `next/navigation`; on
  change, emits `router.push` to the current path with a
  `?target=N` query param (or drops the param when the user
  picks "All targets"). Preserves other search params (e.g.
  `?window_s=30`) when rewriting the target param via a
  `URLSearchParams` snapshot. NAMED export to match the
  existing test-setup mock contract.
- `web/src/app/fights/[id]/page.tsx`:
  - Page signature widened to accept
    `searchParams: Promise<{ window_s?: string; target?: string }>`
    (Next.js 15+ async searchParams contract).
  - New `parseTarget()` helper clamps invalid / out-of-range /
    negative values to `null` (the "unfiltered" sentinel), so
    a URL typo never surfaces a misleading error.
  - New `BUFF_REMOVAL_COLUMNS` spec for the third roll-up.
  - New "Per-target buff removal" section rendering
    `TargetRollupsGrid` with the new columns.
  - `availableTargets` is the union of unique `target_agent_id`
    across the three roll-up arrays (so a target that only
    appears in `target_buff_removal` is still selectable).
  - Server-side filter: `filteredDps` / `filteredHealing` /
    `filteredBuffRemoval` narrowed to the active target when
    `targetFilter !== null`.
  - "filtered to target N" sub-label on the duration line when
    the filter is active.
  - Header layout now hosts `<TargetFilter />` next to
    `<WindowSizeSelector />` in a flex row.
- `web/src/lib/api.ts`: new `TargetBuffRemovalRow` interface +
  `target_buff_removal` field on `FightEventsSummaryRow`.
- `web/tests/setup.ts`: no-op mock for the new `TargetFilter`
  named export (same pattern as `WindowSizeSelector`).
- `web/tests/app/fight-events-page.test.tsx`: `POPULATED_PAYLOAD`
  + `EMPTY_PAYLOAD` gain `target_buff_removal`. 2 NEW test
  cases: target filter narrows all 3 roll-ups + "filtered to
  target N" sub-label, malformed target falls back to the
  unfiltered view. Existing tests updated to expect the
  "Per-target buff removal" heading.
- `web/tests/components/target-filter.test.tsx` (NEW): 4
  component-level tests that override the global no-op mock
  via `vi.mock(..., importOriginal)`: renders all available
  targets + "All targets" entry, marks the current target as
  selected, emits a bare URL on "All targets", emits
  `?target=N` on a target pick. `useRouter` + `usePathname` +
  `useSearchParams` are mocked to deterministic stubs.

### Changed (CI)

- `.github/workflows/ci.yml::lint-and-test`: the Postgres
  `services:` block was already in place (deferred from
  v0.3.0; this release is the first to land with the block
  live). `postgres:16-alpine` with
  `POSTGRES_USER=gw2analytics` /
  `POSTGRES_PASSWORD=gw2analytics` /
  `POSTGRES_DB=gw2analytics` + port mapping `5432:5432` +
  `pg_isready` health check, so a fresh runner can exercise
  the full POST /api/v1/uploads -> GET /api/v1/uploads/{id} ->
  GET /api/v1/fights/{id} -> GET /api/v1/fights/{id}/events
  chain against a real Postgres schema. The DATABASE_URL
  matches `[tool.pytest_env]` in the root `pyproject.toml`
  so `uv run pytest` finds a reachable DB without further
  wiring.

### Notes

- The pre-commit mypy hook (shipped in v0.4.0-tooling) was
  re-validated on the Phase 8 Python file set
  (`uv run pre-commit run mypy --all-files` = 0). No
  `--no-verify` was needed for the v0.6.0 commit.
- The TargetFilter dropdown intentionally displays raw
  `agent_id` integers rather than player names. A future
  enhancement would resolve names from the `OrmFight.agents`
  table (via a new `GET /api/v1/fights/{id}/agents`
  endpoint or by denormalising agent names into the events
  response); for now the raw ids are the smallest viable
  affordance and match the existing `target_agent_id` column
  on the roll-up rows.
- The `event_windows` contract is deliberately NOT extended
  with a `buff_removal_total` field. The per-bucket timeline
  is the "global fight picture"; the per-target roll-ups
  already give the analyst the per-target contribution
  breakdown. Adding a per-bucket strip column would force a
  re-aggregation path that the heterogeneous stream already
  handles correctly (the bucket's `event_count` includes the
  strip half of any dual-emit).
- The dual-emit ordering is documented as "HealingEvent
  first, then BuffRemovalEvent" -- the order matches the
  arcdps convention (heal column then strip column) and is
  locked by `test_parse_events_emits_heterogeneous_damage_heal_strip_stream`.

### Tests

- 6 new parser tests + 6 new analytics tests + 1 extended
  e2e test + 2 new page tests + 4 new component tests.
  Python test count: 46 (v0.5.0-web) -> 58 (v0.6.0).
  Web test count: 20 (v0.5.0-web) -> 26 (v0.6.0).

### Validation

- `uv run ruff check libs apps`: clean (RUFF=0).
- `uv run ruff format --check libs apps`: clean (FORMAT=0).
- `uv run mypy libs apps --no-incremental`: clean (MYPY=0,
  44 source files).
- `uv run pytest libs`: 57 passed + 1 skipped (PYTEST_LIBS=0).
- `uv run pytest apps/api`: 4 tests in `test_uploads_e2e.py` +
  healthz (PYTEST_APPS=0). `alembic upgrade head` runs first
  to migrate the Postgres schema to the v0.3.0
  `events_blob_uri` column.
- `pnpm tsc --noEmit`: clean (TSC=0).
- `pnpm test:unit`: clean (VITEST=0, 7 files / 26 tests).
- `uv run pre-commit run mypy --all-files`: clean
  (PRECOMMIT_MYPY=0).
- Round 68-70 code-reviewer-minimax-m3: **APPROVED**
  (dual-emit + pure-strip contracts correct; pure-damage-with-
  buff_dmg silently dropped matches arcdps; e2e bucket delta
  correct; URL + server-side filter mirrors the window-s
  pattern; CI services block matches docker-compose dev).

[0.6.0]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.5.0-web...v0.6.0

[Unreleased]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.5.0-web...HEAD

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`:
  - New `EVENT_SIZE = 64` + `_EVENT_STRUCT = struct.Struct("<QQQiiIIHHHbbbbbbbbIIbb")`
    matching the real arcdps `cbtevent` layout
    (3Q + 2i + 2I + 3H + 8b + 2I + 2b = 64 bytes total).
  - New `PythonEvtcParser.parse_events(source) -> Iterator[DamageEvent]`
    reads the cbtevent block at the post-skill-block offset;
    emits `DamageEvent` only when `is_statechange == 0` AND
    `is_nondamage == 0` AND `value > 0` (clamped via `max(0, value)`).
    Truncated trailing bytes are leniently dropped.
  - New `_compute_post_skills_offset(data) -> int` helper mirrors
    `_iter_skills` cursor logic so `parse_events` can advance past
    the skill table deterministically without re-yielding `Skill`
    records.

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/interface.py`: `EvtcParser`
  Protocol gained an optional-sense `parse_events(source) ->
  Iterator[DamageEvent]` member. Existing implementations stay
  source-compatible -- callers that only enforce `parse(source)` are
  not broken.

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/__init__.py`: re-exports
  `EVENT_SIZE` + `PythonEvtcParser` (the existing parser, now with
  the new `parse_events` method). `__version__` bumped `0.2.0 -> 0.4.0`.

- `libs/gw2_evtc_parser/tests/test_parser.py`: 5 new event-parser tests:
  empty stream, single damage event shape, truncation tolerance (lenient
  drop), `is_statechange == 1` filter (skipped), `is_nondamage == 1`
  filter (skipped). All 5 use a synthetic 25-byte header + 96-byte
  agent record + zero skills + 64-byte cbtevent records built via
  `struct.pack` against the same `_EVENT_STRUCT` layout. The
  pre-existing real-fixture integration test (`test_real_evtc_binary
  _parses_with_realistic_agent_count`) is unchanged.

- `libs/gw2_evtc_parser/tests/test_interface.py`: protocol conformance
  test extended to cover `parse_events` round-trip (also via the
  synthetic 64-byte fixture).

- `apps/api/alembic/versions/0004_fight_events_blob_uri.py` (NEW):
  adds `events_blob_uri VARCHAR(255) NULL` to the `fights` table.
  Historical fights (uploaded before Phase 7 v1) keep the column
  as `NULL`; the `/fights/{id}/events` route surfaces `404 Not
  Found` for these rows so consumers can distinguish "parser ran
  but yielded no damage" from "data unavailable".

- `apps/api/src/gw2analytics_api/models.py::OrmFight`: gains
  `events_blob_uri: Mapped[str | None] = mapped_column(String(255),
  nullable=True)`. Purely additive; no backfill.

- `apps/api/src/gw2analytics_api/storage.py`:
  - Extracted `_ensure_bucket()` helper from `put_zevtc()`; both
    `put_zevtc` and the new `put_events` use it.
  - New `put_events(fight_id, gz_data) -> str`: uploads to
    `events/{fight_id}.jsonl.gz` with `content_type="application/gzip"`.
  - New `get_events(key) -> bytes`: fetches + releases the MinIO
    connection. `S3Error` propagates so the route can map
    `NoSuchKey` to `404 Not Found`.

- `apps/api/src/gw2analytics_api/services.py`:
  - New `_persist_event_blob(db, upload, evtc_bytes, fight_id)`
    helper called from `process_parse` after `_save_fight` and
    before `upload.status = UPLOAD_STATUS_COMPLETED`. Calls
    `PythonEvtcParser.parse_events(evtc_bytes)`, serialises the
    events as JSONL (one `DamageEvent.model_dump_json()` per line),
    gzip-compresses with `gzip.compress(jsonl)`, uploads via
    `put_events`, and writes the storage key back to
    `OrmFight.events_blob_uri`. Degrades gracefully to
    `events_blob_uri = NULL` when the parser yields zero events OR
    when the blob upload fails (the fight-row + agents + skills
    stay valid; operators can re-parse the upload to retry).

- `apps/api/src/gw2analytics_api/schemas.py`: new
  `TargetDpsRowOut` (drops `attack_count` from the API surface so
  the JSON stays client-broad) + `FightEventsSummaryOut`
  (`fight_id`, `duration_s`, `target_dps`,
  `event_windows`). The pre-existing `EventBucketOut` is now part
  of the live response shape rather than a future-proofing stub.

- `apps/api/src/gw2analytics_api/routes/fights.py`:
  `GET /api/v1/fights/{fight_id}/events` route now returns a real
  `FightEventsSummaryOut` rather than the Phase 6 v1 `[EventBucketOut]`
  stub. New `window_s: int = Query(5, ge=1, le=600)` query param
  drives the time-bucket roll-up. Response codes:
  - `404 Not Found`: unknown fight OR `events_blob_uri is None`
    OR the MinIO read raises `S3Error` (blanket 404 so a missing
    blob never masquerades as a zero-damage fight).
  - `422 Unprocessable Entity`: `window_s` outside `[1, 600]`
    (handled by FastAPI before this handler runs).
  - `502 Bad Gateway`: events blob is present but corrupt
    (`gzip.decompress` failed).
  `duration_s` is computed natively as
  `max(events.time_ms) / 1000.0` (the V1.3 EVTC header does not
  carry a wall-clock duration scalar).

- `apps/api/pyproject.toml`: gained `gw2_analytics` as a runtime
  dependency (the route now imports
  `gw2_analytics.event_window.EventWindowAggregator` +
  `gw2_analytics.target_dps.TargetDpsAggregator`).

- `apps/api/tests/test_uploads_e2e.py`:
  - Extended `_make_minimal_zevtc()` to accept an optional
    `events=` list of pre-packed 64-byte cbtevent records appended
    after the skill block.
  - New `_make_cbtevent()` helper packs one cbtevent record with
    the same layout as the parser's `_EVENT_STRUCT`. Field padding
    (`pad61`..`pad66`, `translocated`, `is_offcycle`) is set to
    zero -- the parser never reads them.
  - Extended `test_uploads_e2e_happy_path` with two damage cbtevent
    records (`time_ms=1500`, `time_ms=2500`, both targeting agent
    B with skill A/B), then asserts
    `GET /fights/{id}/events?window_s=1` returns
    `duration_s == 2.5`, a single `target_dps` row summing both
    hits, and 3 contiguous 1-second buckets with counts `[0, 1, 1]`.
  - New `test_fight_events_404_when_unknown_fight` covers the
    404 contract for missing fight id.
  - New `test_fight_events_422_when_window_s_too_small` covers
    the Pydantic Query `ge=1` validator rejecting `window_s=0`.

### Changed

- `apps/api/src/gw2analytics_api/schemas.py::EventBucketOut`
  docstring: `Phase 6 v2 future-proofing` references removed; the
  schema is now wired into the live response.
- `apps/api/src/gw2analytics_api/services.py` module docstring:
  extended with Phase 7 v1 scope (`parse_events` drain +
  gzip JSONL + `events_blob_uri` write-back).

### Notes

- `DamageEvent` (in `libs/gw2_core`) already had `source_agent_id`,
  `target_agent_id`, `skill_id` via the broader `BaseEvent` model
  introduced in Phase 6 v1 -- the parser consumer reads those
  fields directly from the cbtevent record without a wrapper type.
- The `is_statechange == 0` / `is_nondamage == 0` filter passes
  only damage events in Phase 7 v1; `HealingEvent` extraction
  (cbtevent records with the conditioning/damage-with-negation
  pattern) is a Phase 7 v2 follow-up. The JSONL includes
  `event_type` so a v2 reader can discriminate without a
  schema migration on the storage side.
- `EventWindowAggregator`'s continuous-fill semantics fills the
  empty `[0, 1000ms)` leading bucket when `window_ms=1000` and the
  first event lands at `time_ms=1500`. The happy-path test
  asserts this directly (`counts == [0, 1, 1]`).
- 404-on-NULL-blob is the canonical contract: returning
  `200 OK` with empty arrays would conflate "parser ran, no
  damage" with "data unavailable", and consumers would have
  no signal to re-upload.

## [0.5.0-web] - Phase 7 v2 of web: window-s selector on /fights/[id]

### Added (web)

- `web/src/components/WindowSizeSelector.tsx` (NEW): Client
  Component that renders a dropdown of preset time-bucket sizes
  (``[1, 5, 30, 60, 300]`` seconds) for the ``/fights/[id]``
  drill-down page. Uses ``useRouter`` + ``usePathname`` from
  ``next/navigation``; on change, emits a ``router.push`` to the
  current path with a ``?window_s=N`` query param (or a bare path
  when the user picks the gateway default 5s, so the URL stays
  canonical). The default is referenced via
  ``String(WINDOW_S_PRESETS[1])`` (not the literal "5") so a
  future preset-list reorder only needs to change the constant,
  not two call sites. NAMED export to match the existing
  test-setup mock contract.

- `web/src/app/fights/[id]/page.tsx`: page signature widened to
  accept ``searchParams: Promise<{ window_s?: string }>`` (the
  Next.js 15+ async searchParams contract). The page awaits
  searchParams, parses the raw string via the new
  ``parseWindowS()`` helper, and passes ``{ windowS: parsed }`` to
  ``fetchFightEvents`` so the URL drives the time-bucket size.
  ``parseWindowS()`` clamps out-of-range / non-integer / negative
  values to the gateway default (5s) so a URL typo never surfaces
  a misleading 422 from the gateway -- the analyst lands on the
  canonical 5s view instead. The page header is now a flex row
  (display:flex + alignItems:baseline + justifyContent:space-
  between + flexWrap:wrap) so the new
  ``<WindowSizeSelector />`` sits to the right of the fight_id +
  duration sub-header (wraps below on mobile).

- `web/tests/setup.ts`: added a no-op mock for the new
  ``WindowSizeSelector`` named export (same pattern as the
  existing ``TargetRollupsGrid`` + ``EventWindowsTable`` mocks
  so the page-level Server Component test focuses on the page's
  own render contract).

- `web/tests/app/fight-events-page.test.tsx`: all 3 existing test
  cases updated to pass ``searchParams: Promise.resolve({})``.
  Two new test cases:
    - ``window_s=30`` is forwarded to ``fetchFightEvents`` with
      ``{ windowS: 30 }`` (locks down the URL -> fetch wiring).
    - ``window_s=9999`` (out of the gateway's ``[1, 600]``
      range) is clamped to the default 5 (locks down the
      ``parseWindowS`` clamping behaviour; the gateway never
      sees a bogus value).

- `web/tests/components/window-size-selector.test.tsx` (NEW): 3
  component-level tests that override the global no-op mock via
  ``vi.mock("@/components/WindowSizeSelector", async
  (importOriginal) => { return await importOriginal<...>(); })``:
    - renders all 5 preset options + marks the ``current`` prop
      as selected.
    - picking the default (5) emits a bare URL (no query param).
    - picking a non-default value emits a ``?window_s=N`` URL.
  The selector's dependencies (``useRouter`` + ``usePathname``)
  are mocked to deterministic stubs so each test asserts on the
  emitted URL without booting the real Next.js router.

### Notes

- The dropdown is intentionally a fixed preset list (1, 5, 30,
  60, 300) rather than a free-form number input. The gateway
  rejects out-of-range values with 422; a free-form input would
  require either client-side validation or a 422 error card.
  Presets cover the common analyst use cases (per-second, default,
  per-encounter, per-minute, per-5-min) without the validation
  overhead. A future "Custom..." option could open a number
  input if analysts request it.
- ``router.push`` (not ``router.replace``) is used so the
  analyst can back-button through the bucket sizes they tried.
  The page is ``force-dynamic`` + ``cache: "no-store"`` so the
  per-rollup re-render is cheap.
- The ``usePathname() ?? `/fights/${fightId}`` fallback in the
  selector is defense-in-depth: ``usePathname`` is a Client hook
  and always returns a non-null string after hydration, so the
  fallback is dead code in practice. Kept for robustness.

### Tests

- 5 page-level cases (was 3): populated, 404, empty, window_s=30
  wired, window_s=9999 clamped.
- 3 component-level cases (new file).
- Total: 8 cases for the window-s surface (5 page + 3 component).

### Validation

- ``pnpm tsc --noEmit``: clean (TSC=0).
- ``pnpm test:unit``: clean (VITEST=0, 6 files / 20 tests).
- Round 66-67 code-reviewer-minimax-m3: **APPROVED** (URL query
  param is the canonical Next.js 15+ pattern; searchParams
  Promise wiring is correct; parseWindowS clamping prevents
  spurious 422s; WINDOW_S_PRESETS[1] reference keeps onChange
  in lockstep with the preset list; importOriginal override
  matches the partial-mock pattern used elsewhere in the
  test suite).

[0.5.0-web]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.4.0-tooling...v0.5.0-web

## [0.5.0-parser] - Phase 7 v2 cbtevent heal extraction + Event discriminated union

### Added (parser)

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`: ``PythonEvtcParser.parse_events``
  signature broadened from ``-> Iterator[DamageEvent]``` to
  ``-> Iterator[Event]```. New filter contract (Convention A +
  Elite Insights parity):
    - ``is_statechange == 0 && is_nondamage == 0 && value > 0`` -> emits DamageEvent
    - ``is_statechange == 0 && is_nondamage >  0 && value > 0`` -> emits HealingEvent
    - Records with ``is_statechange != 0`` still skip (Phase 8 candidate).
  Each cbtevent record yields AT MOST ONE event. The ``buff_dmg```
  field is NOT also emitted as a HealingEvent from the same record
  (deferred to Phase 8 -- avoids double-counting the buff-removal
  path).

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/interface.py`: ``EvtcParser```
  Protocol's ``parse_events``` member returns the same
  ``Iterator[Event]```.

### Added (domain)

- `libs/gw2_core/src/gw2_core/models.py`: ``Event``` is now a PEP 695
  ``type``` declaration with a Pydantic v2
  ``Field(discriminator="event_type")``` discriminator so JSONL
  round-trip auto-dispatches on the ``event_type``` literal payload.

### Changed (apps/api)

- `apps/api/src/gw2analytics_api/routes/fights.py`: module-level
  ``_EVENT_TYPE_ADAPTER: TypeAdapter[Event]``` (built once at import
  time) replaced the previous per-line ``DamageEvent.model_validate_json```
  loop so the heterogeneous JSONL stream materialises damage + healing
  without manual isinstance dispatch. ``TargetDpsAggregator.aggregate```
  call site filters via
  ``[e for e in events if isinstance(e, DamageEvent)]``` so the
  aggregator signature stays narrow on ``DamageEvent``` (its
  sum-invariant validates sum-of-row-damage == sum-of-event-damage).

### Test delta

- `libs/gw2_evtc_parser/tests/test_parser.py`: 7 NEW Phase 7 v2 tests
  locking down the Convention A contract:
    - test_parse_events_yields_healing_event_on_nondamage
    - test_parse_events_clamps_negative_healing_to_zero
    - test_parse_events_emits_one_event_per_cbtevent_for_damage_plus_heal
      (the Phase 7 v1 contract test was renamed + repurposed to
      lock down the value-filter branch for the HEALING path)
    - test_parse_events_skips_statechange_for_healing
    - test_parse_events_skips_statechange_for_damage
    - test_parse_events_emits_heterogeneous_stream_signed_by_event_type
    - test_parse_events_yield_type_is_event_union

### Validation

- ruff check + format: clean (libs + apps)
- mypy libs apps --no-incremental: clean
- pytest libs/gw2_evtc_parser libs/gw2_analytics: 103 passed + 1 skipped
  (the skipped test is the real-EVTC-fixture integration test gated
  on /tmp/inner_20251002-213519 availability)
- Round 51-58 code-reviewer: APPROVED (with minor cleanup notes)

### Migration

The Python surface is fully backward-compatible. ``parse_events```
now yields the union type so callers that explicitly typed the
return as ``list[DamageEvent]``` need to widen to
``list[Event]```. The apps/api ``GET /fights/{id}/events```
route already handles the union via
``TypeAdapter(Event).validate_json(line)```; pre-Phase-7-v2 records
(those with NULL events_blob_uri) continue to surface 404.

[0.5.0-parser]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.4.0-parser...v0.5.0-parser

[Unreleased]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.4.0-parser...HEAD
## [0.4.0-web] - Phase 7 v1 of web: /fights/[id] drill-down page (per-target damage + healing + event windows)

### Added (web)

- `web/src/app/fights/[id]/page.tsx` (NEW): dynamic Server Component
  that SSR-fetches the v0.3.0-api per-fight events payload via
  `fetchFightEvents(fightId)` and renders the per-target damage
  roll-up + per-target healing roll-up + time-bucketed event
  windows on a single page. `params: Promise<{ id: string }>` is
  awaited per Next.js 15+ async route params convention; the page
  is `force-dynamic` + `cache: "no-store"` so the roll-up
  reflects the latest parsed fight state. Empty roll-ups render
  the canonical "no rows" panel via the per-component empty
  state; `ApiError` (404, 5xx, etc.) renders the canonical
  upstream-error card with the gateway's error body. The page is
  a single Server Component that hands the data to three small
  client-rendered sub-views (no waterfall round-trips for the
  same underlying JSONL blob).

- `web/src/components/TargetRollupsGrid.tsx` (NEW): reusable
  generic AG Grid Community wrapper for the per-target damage +
  healing roll-up tables. A single Client Component covers both
  roll-up kinds via a `TargetRollupColumn<TRow>[]` column spec
  (page-level builds the spec for each kind). Renders a styled
  "no rows" panel on empty input so the page-level error path
  is reserved for true upstream errors (404, 5xx).

- `web/src/components/EventWindowsTable.tsx` (NEW): plain HTML
  table (no AG Grid) for the per-bucket roll-up. The bucket
  count is bounded by `duration_s / window_s` so the table stays
  human-scannable without pagination; the natural sort order is
  by `start_ms` (which is monotonic in the response). The
  `healing_total` column is tinted with the `var(--accent)`
  colour to keep the read-out visually cohesive with the AG Grid
  dark theme on the two roll-up grids above it.

- `web/src/components/ag-grid-setup.ts` (NEW): side-effect-only
  module that calls `ModuleRegistry.registerModules([AllCommunityModule])`
  exactly once across the whole module graph. AG Grid Community
  33+ ships in tree-shaken mode and requires the explicit
  registration; centralising it here removes the ordering
  hazard of a user navigating directly to a fight-detail page
  (and never visiting `/fights`) seeing an unstyled grid.

- `web/src/lib/api.ts`: new `fetchFightEvents(fightId, opts?: { windowS?: number }): Promise<FightEventsSummaryRow>`
  helper (mirrors `GET /api/v1/fights/{fight_id}/events` in
  apps/api 0.3.0+; `windowS` defaults to 5, the gateway
  default). Throws the existing `ApiError` on any non-2xx so
  the Server Component can render the canonical upstream-error
  card.

- `web/src/lib/api.ts`: 4 new TypeScript interfaces
  (`TargetDpsRow`, `TargetHealingRow`, `EventBucket`,
  `FightEventsSummaryRow`) hand-written alongside the existing
  `FightRow` / `AccountEnrichedRow` / `UploadCreatedRow` types
  (consistent with the lib's no-codegen policy for response
  types; the OpenAPI `schema.d.ts` is the codegen path for
  future-generated types, not these hand-written shapes).

### Changed

- `web/src/components/FightsGrid.tsx`: the `id` column is now
  rendered as an anchor (`<a href="/fights/{id}">{id}</a>`) so a
  single click on the row carries the analyst to the new
  drill-down page. The cellRenderer is intentionally a plain
  `<a>` (not `next/link`) -- AG Grid renders the cell out of the
  React tree, so the client-side router prefetch is not
  available, and a full-page navigation is acceptable for the
  `force-dynamic` + `cache: "no-store"` drill-down target.
  The grid's `ModuleRegistry.registerModules` call is replaced
  by a side-effect import of `./ag-grid-setup` (single
  registration across the whole module graph).

- `web/tests/setup.ts`: global mocks for the new components
  (`TargetRollupsGrid`, `EventWindowsTable`) added alongside
  the existing `FightsGrid` mock so the page-level Server
  Component tests can transitively import the new page +
  components without dragging `ag-grid-react` into the vitest
  runtime.

- `web/src/app/fights/[id]/page.tsx` (new) + `web/package.json`
  (no change; the page is rendered via the existing Next.js 16
  app-router conventions) + `web/pnpm-lock.yaml` (no change;
  no new dependencies).

### Notes

- The two roll-up grids are independent: a damage-only fight
  yields an empty heal grid, a heal-only fight yields an empty
  damage grid, and a mixed fight yields one row per target
  across both. The page's per-component empty-state handles
  each case gracefully -- no error path is taken on
  legitimately-empty roll-ups.
- `EventWindowsTable` is a plain `<table>` rather than an AG
  Grid because the bucket roll-up is a TIMELINE visualisation
  (chronological order, no sort/filter needs) and the bucket
  count is bounded by `duration_s / window_s` so pagination
  is unnecessary. AG Grid's affordances would be wasted on
  this view.
- The new page is a forward-compat drop: any new `Event`
  subclass added in the future (e.g. a Phase 8
  `BuffRemovalEvent`) will surface here as a new sibling
  roll-up section + a new column on the per-bucket
  `event_windows` table. `TargetRollupsGrid` is generic so
  the page only needs to add a new column spec; no new
  Client Component required.

### Tests

- `web/tests/app/fight-events-page.test.tsx` (NEW): 3 vitest
  cases mirroring the existing `fights-page.test.tsx` CI-smoke
  pattern -- the Server Component is invoked as a plain async
  function, not inside Next.js's RSC runtime. Cases:
  - happy path: populated payload (1 target_dps row + 1
    target_healing row + 3 event_windows) renders the header
    (fight_id + duration_s) + all 3 section headings.
  - upstream 404: `fetchFightEvents` rejects with
    `new ApiError(404, "fight not found")`; the page renders
    the upstream-error card.
  - empty roll-ups: `fetchFightEvents` returns a payload with
    empty target_dps + target_healing + event_windows; the
    page renders the header + the 3 section headings (the
    per-component empty-state is asserted at the component
    level, not here).

### Validation

- `pnpm tsc --noEmit` clean (Next.js 16 + React 19 + AG Grid
  Community 34 type surface).
- `pnpm test:unit` clean (3 new fight-events-page tests + the
  existing 11 vitest tests across the app: 14 total).
- Code-reviewer: APPROVED.

[0.4.0-web]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.3.0-web...v0.4.0-web

## [0.4.0-tooling] - workspace-aware pre-commit mypy hook (uv run)

### Fixed

- `.pre-commit-config.yaml`: the pre-commit ``mypy`` hook (formerly
  ``mirrors-mypy`` v1.13.0) built a separate hook venv that did NOT
  include the workspace members (``gw2_core``,
  ``gw2_evtc_parser``, ``gw2_analytics``, ``gw2_api_client``).
  The hook fired ``import-not-found`` errors for ``from gw2_core
  import ...`` on every commit touching ``apps/`` or ``libs/``
  Python files, requiring ``--no-verify`` to bypass. The
  v0.4.0-analytics and v0.4.0-web releases both worked around
  this with ``git commit --no-verify``.

  Replaced the ``mirrors-mypy`` block with a single ``repo: local``
  hook that runs ``uv run mypy --no-incremental`` from the repo
  root. The local hook uses ``language: system`` so pre-commit
  does NOT create a new venv; it reuses the project's own ``uv``
  venv where the editable workspace members resolve correctly.
  ``--disable-error-code=misc`` was dropped (the "Untyped
  decorator" + "Class cannot subclass X" noise categories were
  artifacts of the missing-stubs hook venv; the full workspace
  venv resolves them properly). ``require_serial: true`` is set
  so multiple mypy processes do not step on each other's
  ``.mypy_cache``.

### Notes

- Prereq: the developer must have ``uv`` on ``$PATH`` when
  running ``git commit``. This is already the project's standard
  toolchain (the README, CI, and developer workflow all assume
  ``uv sync`` + ``uv run`` are available), so no new install
  step is needed.
- The local hook keeps ``pass_filenames: true`` (the pre-commit
  default) so it only type-checks the staged files for fast
  feedback; CI continues to run the full ``uv run mypy libs apps
  --no-incremental`` re-check on every push + PR.
- Validated by running ``uv run pre-commit run mypy --all-files``
  against the current ``main``: hook fires + passes on every
  Python file in ``libs/`` + ``apps/`` (46 staged + 91 unstaged
  files = 137 files type-checked clean).

### Validation

- ``uv run pre-commit run mypy --all-files``: clean
  (``PRECOMMIT_MYPY=0``).
- ``uv run ruff check libs apps``: clean (``RUFF=0``).
- ``uv run ruff format --check libs apps``: clean (``FORMAT=0``).
- ``uv run mypy libs apps --no-incremental``: clean (``MYPY=0``,
  42 source files).
- ``uv run pytest libs``: 46 passed + 1 skipped
  (``PYTEST_LIBS=0``; the skipped test is the real-EVTC-fixture
  integration test gated on the fixture's availability).
- Round 65 code-reviewer-minimax-m3: **APPROVED**.

[0.4.0-tooling]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.4.0-web...v0.4.0-tooling

## [0.3.0-api] - Phase 7 v1 of apps/api: per-target healing roll-up

### Added (apps/api)

- `apps/api/src/gw2analytics_api/schemas.py`: new
  `TargetHealingRowOut` response schema (strict parallel of
  `TargetDpsRowOut` -- drops `heal_count` from the API surface
  for analyst-only parity) and a new
  `target_healing: list[TargetHealingRowOut] = []` sibling field
  on `FightEventsSummaryOut` (between `target_dps` and
  `event_windows`). Empty when the parser yielded zero healing
  events; mixed damage + healing fights produce independent
  roll-ups on the same `duration_s`.
- `apps/api/src/gw2analytics_api/routes/fights.py`: the
  heterogeneous JSONL stream is now split at the call site --
  `TargetDpsAggregator` receives
  `[e for e in events if isinstance(e, DamageEvent)]` and
  `TargetHealingAggregator` receives
  `[e for e in events if isinstance(e, HealingEvent)]`; both
  are invoked on the same `duration_s` so the two roll-ups are
  temporally consistent. The route's per-aggregator call site
  stays free of cross-kind discrimination in the hot loop. The
  handler docstring is extended to document the new field and
  the call-site isinstance filter pattern.
- `apps/api/tests/test_uploads_e2e.py::test_uploads_e2e_happy_path`:
  now packs 2 healing cbtevent records (Phase 7 v2
  `is_nondamage=1` + `value>0` filter) alongside the 2 existing
  damage records. Damage flows A->B; healing flows B->A so the
  two roll-ups land on DIFFERENT targets, exercising the
  damage-only / heal-only / mixed-fight cases. The response
  assertions cover the new `target_healing` field + the
  per-bucket `healing_total` accounting + the doubled
  `event_count` per non-empty bucket.

### Changed

- `apps/api/src/gw2analytics_api/__init__.py`: `__version__`
  bumped `"0.2.0" -> "0.3.0"`.
- `apps/api/src/gw2analytics_api/main.py`: FastAPI `version`
  string bumped `"0.2.0" -> "0.3.0"`.
- `apps/api/pyproject.toml`: version bumped
  `"0.2.0" -> "0.3.0"`.

### Notes

- The v2 `Event` discriminated union (`DamageEvent | HealingEvent`)
  is now consumed end-to-end on the HTTP surface -- a single
  `GET /api/v1/fights/{fight_id}/events` round-trip returns a
  per-target damage roll-up AND a per-target healing roll-up.
  `EventWindowAggregator` was already a damage+healing dual
  consumer (Phase 6 v1); the per-target view completes the
  coverage.
- Forward-compat: any new `Event` subclass added in the future
  (e.g. a Phase 8 `BuffRemovalEvent`) requires a matching
  per-target aggregator + a new sibling field on
  `FightEventsSummaryOut`; the discriminated-union dispatch +
  per-aggregator call-site filter pattern extends cleanly
  without breaking the existing contract.

### Validation

- ruff + ruff format + mypy clean across `libs` + `apps`
  (`uv run`).
- pytest `libs`: 46 passed (40 existing + 6 new heal-roll-up).
- pytest `apps/api`: 4 tests in `test_uploads_e2e.py` (1 happy
  path + 3 edge cases) + 1 test in `test_healthz.py` -- the
  e2e Postgres-dependent test is conditionally run when
  `DATABASE_URL` is reachable.
- Code-reviewer: APPROVED.

[0.3.0-api]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.2.0-api...v0.3.0-api

## [0.3.0] - web upload UI + event aggregations

### Added

- `CHANGELOG.md`: this file. Captures the V1.4 stability cycle and the
  P1 parser closure that landed in the same push window.
- `.github/workflows/ci.yml`: a single `lint-and-test` GitHub Actions
  job (Python 3.12 on `ubuntu-latest`) running `uv run ruff check`
  + `uv run ruff format --check` + `uv run mypy libs apps
  --no-incremental` + `uv run pytest --tb=line -q` on every push and
  pull request to `main`. Uses `astral-sh/setup-uv@v3` with
  `enable-cache: true` keyed on `uv.lock`. No GitHub repository
  secrets are required because `pytest-env` (see Changed) injects
  the docker-compose dev credentials at pytest session startup,
  and the Postgres-dependent `test_uploads_e2e.py` self-skips via
  the `db_reachable` fixture when no docker-compose Postgres is
  reachable on the runner.
- `README.md`: a CI status badge under the H1 title pointing at the
  new workflow.
- `libs/gw2_evtc_parser/tests/test_parser.py`: new synthetic unit
  test `test_player_with_empty_char_name_but_valid_account_and_subgroup`
  locking down the WvW arcdps edge case where a player record has an
  empty ``char_name`` but a valid ``account_name`` + ``subgroup``
  (previously only covered by the real-fixture integration test).

### Changed

- `pyproject.toml`: added `pytest-env>=1.6.0` to the dev dependency
  group. `pytest-env` reads the new `[tool.pytest_env]` table and
  injects `DATABASE_URL` + `S3_*` docker-compose dev credentials
  into `os.environ` at pytest session startup, so the test suite
  no longer depends on a hand-rolled `.env` file.
- `apps/api/src/gw2analytics_api/config.py`: credentials are now
  **fully environment-driven** (no hardcoded sentinel defaults).
  Each `minio_*` Python field is mapped to the matching `S3_*` env
  var via `Field(validation_alias="...")`; `database_url` maps to
  `DATABASE_URL`. **Operators must `cp .env.example .env`** before
  running `uv run uvicorn` (or `uv run fastapi dev`); tests are
  insulated by `pytest-env`.
- `pyproject.toml`: removed the now-unnecessary
  `apps/**/config.py = ["S105"]` per-file ruff ignore plus its
  belt-and-suspenders cross-reference comments. `config.py` is
  sentinel-free, so bandit will catch any future regression at PR
  time.
- `pyproject.toml`: bug fix in `[tool.ruff.lint] select`: the
  `"S"` (flake8-bandit) entry was previously collapsed onto the
  `"UP"` comment line and silently dropped from the array. Now
  restored on its own line; `select` is `["E","F","I","B","UP",
  "S","RUF"]` (verified via `tomllib`).
- `apps/api/src/gw2analytics_api/main.py`: added an inline `# type:
  ignore[import-untyped]` on the `fastapi_mcp` import (the
  `[[tool.mypy.overrides]]` block was not always honoured).
- `.pre-commit-config.yaml`: bumped the `ruff-pre-commit` hook from
  `v0.7.0` to `v0.15.2` to match the workspace `ruff>=0.7` resolved
  by `uv` to `ruff 0.15.20`. The eight-minor version gap previously
  caused the `ruff-format` hook to repeatedly re-format files that
  newer ruff had already formatted correctly ("1 file reformatted"
  on every pre-commit run).
- `libs/gw2_evtc_parser/tests/test_parser.py`: previously hoisted a
  parser import from inside a function body to module top
  (`ruff PLC0415`).
- `README.md`: Quickstart step 5 is now `cp .env.example .env`
  (required for the env-driven credentials); subsequent steps
  renumbered.

### Fixed

- See "Changed" above: the `select` array regression, the
  `ruff-pre-commit` version mismatch, the `fastapi_mcp` import
  ignoring the mypy override, and the `config.py` S105 sentinel
  workaround (replaced with an honest env-only contract).

### Security

- No hardcoded credentials remain anywhere in the source tree.
- CORS is no longer hardcoded to ``allow_origins=["*"]``. A new
  optional ``Settings.cors_allowed_origins`` field reads the
  comma-separated ``CORS_ALLOWED_ORIGINS`` env var (defaults to
  ``["*"]`` for local dev); ``apps/api/.../main.py`` reads it once
  on app init. Operators tighten the gateway for public deploy
  by setting the env var to the real domains. The pre-existing
  inline warning comment is updated to reflect that the override
  is now wired (no longer future work).

### Fixed

- `web/src/app/page.tsx`: the hero footer was rendering the literal
  string ``process.env.API_BASE_URL`` because the JSX expression
  was wrapped in quotes (`<code>{"process.env.API_BASE_URL"}</code>`).
  Removed the quotes and replaced with a shared
  ``displayedApiBaseUrl`` helper imported from
  ``web/src/lib/api.ts`` so the SSR'd landing cannot drift from the
  trimmed URL the gateway fetcher uses.
- `README.md` + `CHANGELOG.md`: post-release drift corrections
  (test counts, the v0.2.0-api tag status flipping from `pending`
  to `shipped`, the test-file count updating to 8, the openapi
  codegen mechanism description corrected to reflect
  `web/scripts/dump_openapi.py`).
- `apps/api/tests/test_uploads_e2e.py`: dropped the runtime
  ``db_reachable`` fixture + the conditional ``pytest.skip`` block.
  The test now runs unconditionally against any environment that has
  a Postgres reachable at ``DATABASE_URL`` (the suite auto-loads the
  docker-compose dev credentials via ``pytest-env``). The module
  docstring reframes the requirement as positive
  ("``docker compose up -d gw2a-postgres`` first") instead of a skip
  hint. CI on a fresh runner must bring up the Postgres service
  before ``pytest`` runs (deferred to a followup -- add a
  ``services:`` block to ``.github/workflows/ci.yml::lint-and-test``).
  Orphaned ``from sqlalchemy import create_engine, text`` import
  cleaned up.

### Added (Phase 4 -- web/ frontend scaffold)

- `web/package.json`: AG Grid Community, AG Grid React, and
  `openapi-typescript` joined the dev dependency group. Two new
  scripts: `pnpm typecheck` runs `tsc --noEmit`; `pnpm generate:api`
  writes `src/lib/api/schema.d.ts` from `web/scripts/dump_openapi.py`
  (in-process `app.openapi()` JSON piped through `openapi-typescript`;
  no running gateway required).
- `web/src/app/layout.tsx`: renamed the page <title> from
  "Create Next App" to "GW2Analytics" and tightened the metadata
  description around the WvW framing.
- `web/src/app/page.tsx`, `page.module.css`, `globals.css`:
  replaced the `create-next-app` boilerplate with a WvW-themed
  landing page (brand badge + hero + two CTAs: `/fights` and
  `/account`). DWvW dark theme (slate background + gold accent)
  with `prefers-color-scheme: light` opt-out.
- `web/src/app/fights/page.tsx`: Server Component that
  SSR-fetches `GET /api/v1/fights` via the lib helper. Marked
  `dynamic = "force-dynamic"` so the grid never serves stale.
- `web/src/components/FightsGrid.tsx`: Client Component wrapping
  AG Grid Community, registering `AllCommunityModule` once at
  module load (v33+ tree-shaken build), dark Quartz theme,
  sortable + filterable columns, 25-row pagination.
- `web/src/app/account/page.tsx`: Client Component with a
  password input that submits the GW2 API key as
  `Authorization: Bearer <key>` to `/api/v1/account` and renders
  the resolved ``(world_id, world_name, world_population)`` triple
  (or surfaces the upstream error).
- `web/src/lib/api.ts`: env-driven fetcher helpers for RSC +
  Client Components; honours `API_BASE_URL` (defaults to
  `http://localhost:8000`). Declares `FightRow` and
  `AccountEnrichedRow` local types.
- `web/.env.example`: declares `API_BASE_URL`.
- `web/README.md`: replaces the `create-next-app` README with a
  concise frontend description (routes, scripts, codegen, auth
  caveats).
- `.github/workflows/ci.yml`: appended two steps to
  `lint-and-test` -- `pnpm/action-setup@v4` + Node 20 setup,
  `pnpm install --frozen-lockfile`, and `pnpm exec tsc --noEmit`.
  The web/ type surface is now part of the merge gate.

### Added (Phase 5 -- apps/api `GET /api/v1/account`)

- `apps/api/pyproject.toml`: depends on `gw2_api_client>=0.1.0`.
  `dev` group gains `respx>=0.21` and `httpx>=0.27` (no longer
  reaches the TestClient via the top-level root dev extras).
  Version bumped `0.1.0 -> 0.2.0`.
- `apps/api/src/gw2analytics_api/schemas.py`: new response
  schema `AccountEnrichedOut` (``world_id``, ``world_name``,
  ``world_population``). ``world_population`` is a plain string
  so future v2 Population buckets don't break the round-trip -- if
  the upstream grows a new value, ``WorldInfo`` validation raises
  and the route surfaces 502 rather than silently coercing.
- `apps/api/src/gw2analytics_api/routes/account.py` (NEW): GET
  `/api/v1/account` -- a thin endpoint that composes
  ``AsyncGuildWars2Client.account_get`` + ``worlds_get([world_id])``
  to return a single deterministic world triple. Auth via
  `HTTPBearer(auto_error=False)`. Error mapping: missing/empty
  bearer -> 401 (with `WWW-Authenticate: Bearer`), upstream 401
  -> 401 (key was rejected), upstream 429 retry exhaustion -> 503,
  upstream 5xx / network -> 502, generic -> 502. Pure GET, no
  persistent state effects.
- `apps/api/src/gw2analytics_api/main.py`: includes the new
  `account` router; FastAPI `version` string bumped
  `0.1.0 -> 0.2.0`.
- `apps/api/tests/test_account.py` (NEW): 11 respx-mocked tests
  covering happy path, missing bearer, empty bearer,
  whitespace-only bearer, lowercase Bearer scheme (some proxies
  normalise the scheme to lowercase and the route must still
  accept it), upstream 401 -> 401, upstream 5xx -> 502, upstream
  429 -> 503 after 3 retries, 1x 429 + 200 succeeds on retry 2,
  `httpx.ConnectTimeout` transport -> 502, and empty `worlds_get`
  -> 502.

### Changed

- `uv.lock`: bumped to reflect `gw2_api_client` becoming a
  workspace member consumed by apps/api (apps/api 0.2.0).
- `web/pnpm-lock.yaml`: bumped to reflect AG Grid Community,
  AG Grid React, and `openapi-typescript` resolutions.

### Added (Phase 4 followup -- web/ unit-test scaffolding)

- `web/vitest.config.ts` (NEW): vitest 2.x config for the
  Next.js 16 frontend -- `environment: "jsdom"`,
  `setupFiles: ["./tests/setup.ts"]`, `css: false` (Next.js
  owns styleable output), alias `@/*` -> `src/*` mirroring the
  tsconfig root. Pattern-matches `tests/**/*.test.{ts,tsx}`
  (so accidental `.spec.ts`-style files are ignored) and
  `clearMocks: true` (so tests don't leak `vi.fn()` state
  between cases).
- `web/tests/setup.ts` (NEW): global `vi.mock` shims for
  `next/link` (anchor), `next/font/google` (inert CSS-variable
  shim), and `@/lib/env` (`http://test/api`); also extends
  `expect` via `@testing-library/jest-dom/vitest`.
- `web/tests/app/layout.test.tsx` (NEW): asserts `RootLayout`
  exports metadata with title `GW2Analytics` + wraps children
  in `<html lang=en>` with both Geist font variable classes
  set.
- `web/tests/app/page.test.tsx` (NEW): renders `<Home />` and
  asserts the hero heading + tagline + both `next/link` cards
  (`/fights`, `/account`) + the mocked `displayedApiBaseUrl`
  in the footer.
- `web/tests/app/fights-page.test.tsx` (NEW): CI smoke only --
  the `await FightsPage()` call simulates a Server Component
  invocation without booting the Next.js RSC runtime (see the
  file header for the `headers()` / `cookies()` migration
  path). Two cases: `fetchFights -> []` renders the
  empty-state counter; `fetchFights throws` renders the
  upstream-error card.
- `web/package.json`: dev dependency group gains `vitest ^2.1.9`,
  `jsdom ^25.0.1`, `@testing-library/react ^16.3.2`,
  `@testing-library/jest-dom ^6.9.1`. Two new scripts --
  `pnpm test` (vitest watch) and `pnpm test:unit` (vitest
  run once in CI).
- `web/pnpm-lock.yaml`: bumped to reflect the new dev deps.

### Changed

- `web/.npmrc`: bumped build-script allowlist from `[sharp]` to
  `[sharp, esbuild]` (`esbuild` is vitest + Vite + Next.js
  bundler native binary loader; `sharp` continues to be the
  Next.js Image pipeline binary loader). pnpm 11 deprecated
  the `pnpm.onlyBuiltDependencies` package.json field -- the
  authoritative home is .npmrc.
- `web/pnpm-workspace.yaml`: cleaned the leftover
  `allowBuilds:` placeholder block from an earlier interactive
  `pnpm approve-builds` call (whose values were literally
  "set this to true or false"); pointed the docstring at
  `web/.npmrc` for the postinstall allowlist; kept
  `verify-deps-before-run: false`.

### Added (CI followup)

- `.github/workflows/ci.yml::lint-and-test`: new `Web unit
  tests (vitest)` step after `Type-check web`, running
  `pnpm exec vitest run --reporter=verbose` with
  `working-directory: web`. The vitest runner is now part of
  the PR merge gate.

### Added (Phase 5 followup -- web upload UI)

- `web/src/app/upload/page.tsx` (NEW): Client Component that
  posts a `.zevtc` combat log as `multipart/form-data` to
  `POST /api/v1/uploads`. Renders the lightweight envelope
  (``id`` + ``sha256`` + ``status``) returned synchronously +
  points the user at `/fights` for the parsed encounter once
  the background parser finishes. Intentionally does NOT
  poll upload status here -- the gating concern is the parsed
  fight surfacing on `/fights` (already `force-dynamic` +
  `cache: "no-store"`), so the upload page stays a thin
  envelope renderer. Client-side rejects non-`.zevtc` files
  with a `role="alert"` error message **before** any network
  call (cheap; avoids polluting the network tab on bad input).
- `web/src/app/upload/page.module.css` (NEW): CSS module for
  the upload page mirroring the landing aesthetic (gradient
  title, dashed file-picker chip with `color-mix` accent
  overlay on hover, pending-status badge tinted with the
  accent variable). Uses `var(--accent)` / `var(--surface)` /
  `var(--border)` / `var(--font-geist-mono)` -- no hardcoded
  colours.
- `web/src/lib/api.ts`: new `uploadLog(file: File)` async
  helper + `UploadCreatedRow` interface (``id`` + ``sha256``
  + ``status``). Sends FormData + fetch POST; intentionally
  does NOT set ``Content-Type`` so the browser computes the
  multipart boundary from the FormData body.
- `web/src/app/page.tsx`: landing page nav gains a third
  card `/upload` alongside `/fights` and `/account`, with
  copy matching the existing card triplet aesthetic (sans
  serif title + monospace `<code>` snippet + arrow CTA).
- `web/tests/app/upload-page.test.tsx` (NEW): 5 vitest + RTL
  tests covering (a) empty state (heading + "No file
  selected" chip + disabled submit), (b) client-side
  `.zevtc` extension rejection before any network call,
  (c) happy-path upload + result card render with a real
  `UploadCreatedRow`, (d) `ApiError` formatting ("Upstream
  error: 502: ..."), and (e) bare-`Error` network-failure
  pass-through. The whole `@/lib/api` module is mocked so
  the page is testable in isolation without booting a real
  RSC.
- `web/tests/setup.ts`: no change required; the existing
  global mock shim for `next/link` already covers the
  anchors in the upload page.

### Added (Phase 6 -- event-driven aggregations)

- `libs/gw2_core/src/gw2_core/models.py`: new event-stream
  data types. `EventType` (`StrEnum`: DAMAGE, HEALING) +
  `BaseEvent` (`time_ms` + `source_agent_id` +
  `target_agent_id` + `skill_id`, all ``frozen=True`` +
  ``extra="forbid"``) + two leaf subclasses
  (`DamageEvent.damage: int >= 0`,
  `HealingEvent.healing: int >= 0`). Discriminated via
  ``event_type: Literal[EventType.X]`` + an `Event` type alias
  (``Union[DamageEvent, HealingEvent]``) for forward-compat
  consumers that accept "any event". Phase 6 v1 is synthetic
  (no parser integration yet) -- Phase 6 v2 will swap the
  synthetic `Iterable[Event]` input for a parser-sourced stream
  once the V1.3 event block is consumed.
- `libs/gw2_core/src/gw2_core/__init__.py`: re-exports the new
  event types. Version bumped ``0.2.0 -> 0.3.0``.
- `libs/gw2_core/pyproject.toml`: version bumped
  ``0.2.0 -> 0.3.0``.
- `libs/gw2_analytics/src/gw2_analytics/target_dps.py` (NEW):
  `TargetDpsAggregator.aggregate(events: Iterable[DamageEvent],
  duration_s: float) -> list[TargetDpsRow]`. Rows sorted
  deterministic by ``(-total_damage, target_agent_id)``.
  Cross-field invariants: sum of ``row.total_damage`` == sum
  of ``event.damage`` (no event dropped, no double-count);
  rows monotonically non-increasing by ``total_damage``
  with ascending agent id on tie; each row has
  ``attack_count >= 1``. Negative ``duration_s`` raises
  ``ValueError``; zero ``duration_s`` collapses to
  ``dps=0.0`` (sentinel -- dimensionless DPS is meaningless
  and the caller's fight-duration is the canonical input).
  Stateless (instantiate once, reuse).
- `libs/gw2_analytics/src/gw2_analytics/event_window.py` (NEW):
  `EventWindowAggregator.aggregate(events: Iterable[Event],
  window_s: int) -> list[EventBucket]`. Windows are half-open
  ``[start_ms, end_ms)`` so consecutive buckets tile the
  timeline without overlap and gaps are zero-filled so the
  visualisation has no holes. ``window_s < 1`` raises
  ``ValueError``. Damage vs healing is dispatched via
  ``isinstance`` against the ``Event`` union; future event
  types accumulate in ``event_count`` but not in
  ``damage_total`` / ``healing_total`` (forward-compat).
- `libs/gw2_analytics/src/gw2_analytics/__init__.py`:
  re-exports `EventBucket`, `EventWindowAggregator`,
  `TargetDpsAggregator`, `TargetDpsRow`. Version bumped
  ``0.2.0 -> 0.3.0``.
- `libs/gw2_analytics/pyproject.toml`: version bumped
  ``0.2.0 -> 0.3.0``.
- `libs/gw2_analytics/tests/test_target_dps.py` (NEW): 6
  pytest cases covering empty input, single-row shape,
  zero/negative duration edge case, deterministic ordering
  (desc + tie-breaker), cross-field sum preservation, frozen
  Pydantic schema guarantee.
- `libs/gw2_analytics/tests/test_event_window.py` (NEW): 6
  pytest cases covering empty input, invalid window guard,
  single-event bucket shape, gap zero-fill, contiguous
  adjacency invariant, frozen-Pydantic guarantee.
- `apps/api/src/gw2analytics_api/routes/fights.py`: new
  `GET /api/v1/fights/{fight_id}/events` route. Phase 6 v1
  STUB: returns ``[]`` after the 404 check (response_model is
  live as ``list[dict[str, object]]`` so the route shape is
  stable for Phase 6 v2). Phase 6 v2 will replace the empty
  list with the parser-sourced event stream.

### Notes

- Phase 6 deliberately does NOT modify `gw2_evtc_parser`. The
  parser doesn't surface events yet -- Phase 6 v1 ships the
  analytics-surface for synthetic events so the contract is
  locked, then Phase 6 v2 retrofits the parser.
- Forward-compat hooks: `EventType` (StrEnum) admits new
  kinds without API breakage; aggregators gate on
  ``isinstance`` against the matching subclass so unknown
  kinds fall through to ``event_count`` (no silent skipping
  of damage / healing accounting).

### Added

- `libs/gw2_core/src/gw2_core/models.py`: three new pydantic
  models for the Guild Wars 2 v2 REST API surface, exposed so the
  `gw2_api_client` (this commit) and a future `gw2_analytics`
  enrichment consumer can share an authoritative contract without
  the analytics layer having to import the HTTP client.

  - `Population` (`StrEnum`): the five bucket values (`Low`,
    `Medium`, `High`, `VeryHigh`, `Full`) -- capitalised exactly as
    the v2 API emits them so round-tripping through
    `WorldInfo.model_validate(...)` round-trips losslessly.
  - `AccountInfo`: the authenticated account returned by
    `GET /v2/account`. `extra="ignore"` (rather than
    `extra="forbid"`) so the v2 API can grow new fields without
    breaking the library; the wire-format `world` field is renamed
    `world_id` via Pydantic `alias="world"` so the analyst-friendly
    foreign key survives the rename at validation time.
  - `WorldInfo`: one row from `GET /v2/worlds[?ids=...]`
    (id + name + Population). Id is a strict `>= 1` positive int
    foreign key.

- `libs/gw2_core/src/gw2_core/__init__.py`: re-exports
  `AccountInfo`, `WorldInfo`, `Population`. `__version__` bumped
  to `0.2.0`.

- `libs/gw2_core/pyproject.toml`: version bumped `0.0.1 -> 0.2.0`.

## [0.1.0] - gw2_api_client 0.1.0: typed async v2 wrapper (Phase 4)

### Added

- `libs/gw2_api_client/pyproject.toml`: hatchling backend, depends
  on `gw2_core>=0.2.0` + `httpx>=0.27`. Declared
  `gw2_api_client = ["S101"]` in `[tool.ruff.lint.per-file-ignores]`
  (the `assert` in tests).

- `libs/gw2_api_client/src/gw2_api_client/exceptions.py`: a typed
  exception hierarchy rooted at `GuildWars2ClientError`. The
  hierarchy deliberately does NOT inherit from `httpx`'s
  exceptions so a future transport swap (aiohttp / urllib3) does
  not bleed into the public surface.

  - `MissingApiKeyError` -- raised by `from_env()` when the
    configured env var is unset / empty.
  - `GuildWars2HttpError` -- any non-2xx that is not 429 (401, 403,
    404, 5xx); also wraps transport errors (`httpx.HTTPError`
    subclasses) so callers see a transport-agnostic surface.
  - `GuildWars2RateLimitError` -- 429 retry budget exhausted
    (after `_MAX_RATE_LIMIT_RETRIES = 3` attempts).

- `libs/gw2_api_client/src/gw2_api_client/client.py`: the v2 REST
  API wrapper. Two public surfaces:

  - `GuildWars2Client` -- a `typing.Protocol` with three members
    (`supported_endpoints()`, `account_get()`,
    `worlds_get(ids)`). Future sync / cached / batched
    implementations can satisfy this Protocol without test
    rewrites.
  - `AsyncGuildWars2Client` -- the only implementation shipped
    today. Stateless from the caller's perspective; owns one
    `httpx.AsyncClient` connection pool; always use as an
    `async with` so the pool closes deterministically on exit.

  Rate-limit policy: 3 attempts total with exponential backoff
  (0.5s, 1.0s, 2.0s) before `GuildWars2RateLimitError` is raised.
  `worlds_get([])` short-circuits client-side (no HTTP round-trip
  -- the v2 API rejects empty `ids=` with a 400). `account_get()`
  has 401 specifically mapped to `GuildWars2HttpError` (auth
  required). `from_env()` reads `GW2_API_KEY` (or an override env
  var) and raises `MissingApiKeyError` on absence.

- `libs/gw2_api_client/src/gw2_api_client/__init__.py`: re-exports
  the Protocol, the async implementation, the four exception
  classes. `__version__ = "0.1.0"`.

- `libs/gw2_api_client/tests/test_client.py`: 12-test unit suite
  using `respx` to mock `httpx` end-to-end (no real network
  calls). Covers:

  - `account_get` happy path (alias rename `world` -> `world_id`
    survives), 401 -> `GuildWars2HttpError`, transport error
    -> `GuildWars2HttpError`, 3x 429 -> `GuildWars2RateLimitError`
    after 3 attempts, 2x 429 then 200 -> success on attempt 2.
  - `worlds_get([])` short-circuits without HTTP, happy path
    round-trips `Population.HIGH` and `Population.MEDIUM`.
  - `from_env` with / without `GW2_API_KEY` (missing -> the
    typed error).
  - `supported_endpoints()` returns the (`account`, `worlds`)
    tuple.
  - async context manager enters + exits cleanly.

### Changed

- `pyproject.toml`: dev dependency group gained
  `pytest-asyncio>=0.24` + `respx>=0.21`. `[tool.pytest.ini_options]`
  sets `asyncio_mode = "strict"` so async tests require an
  explicit `@pytest.mark.asyncio` (the test suite uses strict
  mode markers throughout).

- `uv.lock`: bumped to reflect the new gw2_core 0.2.0 +
  gw2_api_client 0.1.0 versions and the new dev deps.

### Notes

- Only the V1 minimum API surface (`/v2/account` + `/v2/worlds`)
  is exposed. A future `/v2/commerce` / `/v2/account/achievements`
  endpoint just needs a new method on the Protocol + a row in
  `supported_endpoints()`.
- The Protocol is deliberately not `@runtime_checkable`
  (async methods break the runtime check); tests duck-type against
  it instead.
- Library ships one `NullHandler` no-op by convention so
  downstream apps that haven't configured logging don't see
  `logger.warning(...)` calls propagate up to the root logger.

## [0.4.0] - Phase 1 parser landed

### Added

- `libs/gw2_evtc_parser`: a Python `EvtcParser` PartialImpl that
  reads the V1.3 EVTC binary layout: 25-byte header + 96-byte
  agent records + variable-size skill records. The parser is
  strict on agent record boundaries (`EvtcParseError` on
  truncation) and lenient on the skill table (stops early + logs
  a warning when `header.skill_count` exceeds the actual record
  count -- a known arcdps quirk).
- `libs/gw2_evtc_parser/tests/test_parser.py`: 545-line test
  suite covering synthetic minimal fights, header + agent +
  skill edge cases, real-fixture integration, and `.zevtc` zip
  wrapping/unwrapping.
- `libs/gw2_evtc_parser/tests/test_parser.py::test_real_evtc_binary_parses_with_realistic_agent_count`:
  end-to-end real-fixture integration test against
  `/tmp/inner_20251002-213519` (skipped if the fixture is absent).

## [0.5.0-web] - Phase 7 v2 of web: window-s selector on /fights/[id]

### Added (web)

- `web/src/components/WindowSizeSelector.tsx` (NEW): Client
  Component that renders a dropdown of preset time-bucket sizes
  (``[1, 5, 30, 60, 300]`` seconds) for the ``/fights/[id]``
  drill-down page. Uses ``useRouter`` + ``usePathname`` from
  ``next/navigation``; on change, emits a ``router.push`` to the
  current path with a ``?window_s=N`` query param (or a bare path
  when the user picks the gateway default 5s, so the URL stays
  canonical). The default is referenced via
  ``String(WINDOW_S_PRESETS[1])`` (not the literal "5") so a
  future preset-list reorder only needs to change the constant,
  not two call sites. NAMED export to match the existing
  test-setup mock contract.

- `web/src/app/fights/[id]/page.tsx`: page signature widened to
  accept ``searchParams: Promise<{ window_s?: string }>`` (the
  Next.js 15+ async searchParams contract). The page awaits
  searchParams, parses the raw string via the new
  ``parseWindowS()`` helper, and passes ``{ windowS: parsed }`` to
  ``fetchFightEvents`` so the URL drives the time-bucket size.
  ``parseWindowS()`` clamps out-of-range / non-integer / negative
  values to the gateway default (5s) so a URL typo never surfaces
  a misleading 422 from the gateway -- the analyst lands on the
  canonical 5s view instead. The page header is now a flex row
  (display:flex + alignItems:baseline + justifyContent:space-
  between + flexWrap:wrap) so the new
  ``<WindowSizeSelector />`` sits to the right of the fight_id +
  duration sub-header (wraps below on mobile).

- `web/tests/setup.ts`: added a no-op mock for the new
  ``WindowSizeSelector`` named export (same pattern as the
  existing ``TargetRollupsGrid`` + ``EventWindowsTable`` mocks
  so the page-level Server Component test focuses on the page's
  own render contract).

- `web/tests/app/fight-events-page.test.tsx`: all 3 existing test
  cases updated to pass ``searchParams: Promise.resolve({})``.
  Two new test cases:
    - ``window_s=30`` is forwarded to ``fetchFightEvents`` with
      ``{ windowS: 30 }`` (locks down the URL -> fetch wiring).
    - ``window_s=9999`` (out of the gateway's ``[1, 600]``
      range) is clamped to the default 5 (locks down the
      ``parseWindowS`` clamping behaviour; the gateway never
      sees a bogus value).

- `web/tests/components/window-size-selector.test.tsx` (NEW): 3
  component-level tests that override the global no-op mock via
  ``vi.mock("@/components/WindowSizeSelector", async
  (importOriginal) => { return await importOriginal<...>(); })``:
    - renders all 5 preset options + marks the ``current`` prop
      as selected.
    - picking the default (5) emits a bare URL (no query param).
    - picking a non-default value emits a ``?window_s=N`` URL.
  The selector's dependencies (``useRouter`` + ``usePathname``)
  are mocked to deterministic stubs so each test asserts on the
  emitted URL without booting the real Next.js router.

### Notes

- The dropdown is intentionally a fixed preset list (1, 5, 30,
  60, 300) rather than a free-form number input. The gateway
  rejects out-of-range values with 422; a free-form input would
  require either client-side validation or a 422 error card.
  Presets cover the common analyst use cases (per-second, default,
  per-encounter, per-minute, per-5-min) without the validation
  overhead. A future "Custom..." option could open a number
  input if analysts request it.
- ``router.push`` (not ``router.replace``) is used so the
  analyst can back-button through the bucket sizes they tried.
  The page is ``force-dynamic`` + ``cache: "no-store"`` so the
  per-rollup re-render is cheap.
- The ``usePathname() ?? `/fights/${fightId}`` fallback in the
  selector is defense-in-depth: ``usePathname`` is a Client hook
  and always returns a non-null string after hydration, so the
  fallback is dead code in practice. Kept for robustness.

### Tests

- 5 page-level cases (was 3): populated, 404, empty, window_s=30
  wired, window_s=9999 clamped.
- 3 component-level cases (new file).
- Total: 8 cases for the window-s surface (5 page + 3 component).

### Validation

- ``pnpm tsc --noEmit``: clean (TSC=0).
- ``pnpm test:unit``: clean (VITEST=0, 6 files / 20 tests).
- Round 66-67 code-reviewer-minimax-m3: **APPROVED** (URL query
  param is the canonical Next.js 15+ pattern; searchParams
  Promise wiring is correct; parseWindowS clamping prevents
  spurious 422s; WINDOW_S_PRESETS[1] reference keeps onChange
  in lockstep with the preset list; importOriginal override
  matches the partial-mock pattern used elsewhere in the
  test suite).

[0.5.0-web]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.4.0-tooling...v0.5.0-web

## [0.5.0-parser] - Phase 7 v2 cbtevent heal extraction + Event discriminated union

### Added (parser)

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`: ``PythonEvtcParser.parse_events``
  signature broadened from ``-> Iterator[DamageEvent]``` to
  ``-> Iterator[Event]```. New filter contract (Convention A +
  Elite Insights parity):
    - ``is_statechange == 0 && is_nondamage == 0 && value > 0`` -> emits DamageEvent
    - ``is_statechange == 0 && is_nondamage >  0 && value > 0`` -> emits HealingEvent
    - Records with ``is_statechange != 0`` still skip (Phase 8 candidate).
  Each cbtevent record yields AT MOST ONE event. The ``buff_dmg```
  field is NOT also emitted as a HealingEvent from the same record
  (deferred to Phase 8 -- avoids double-counting the buff-removal
  path).

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/interface.py`: ``EvtcParser```
  Protocol's ``parse_events``` member returns the same
  ``Iterator[Event]```.

### Added (domain)

- `libs/gw2_core/src/gw2_core/models.py`: ``Event``` is now a PEP 695
  ``type``` declaration with a Pydantic v2
  ``Field(discriminator="event_type")``` discriminator so JSONL
  round-trip auto-dispatches on the ``event_type``` literal payload.

### Changed (apps/api)

- `apps/api/src/gw2analytics_api/routes/fights.py`: module-level
  ``_EVENT_TYPE_ADAPTER: TypeAdapter[Event]``` (built once at import
  time) replaced the previous per-line ``DamageEvent.model_validate_json```
  loop so the heterogeneous JSONL stream materialises damage + healing
  without manual isinstance dispatch. ``TargetDpsAggregator.aggregate```
  call site filters via
  ``[e for e in events if isinstance(e, DamageEvent)]``` so the
  aggregator signature stays narrow on ``DamageEvent``` (its
  sum-invariant validates sum-of-row-damage == sum-of-event-damage).

### Test delta

- `libs/gw2_evtc_parser/tests/test_parser.py`: 7 NEW Phase 7 v2 tests
  locking down the Convention A contract:
    - test_parse_events_yields_healing_event_on_nondamage
    - test_parse_events_clamps_negative_healing_to_zero
    - test_parse_events_emits_one_event_per_cbtevent_for_damage_plus_heal
      (the Phase 7 v1 contract test was renamed + repurposed to
      lock down the value-filter branch for the HEALING path)
    - test_parse_events_skips_statechange_for_healing
    - test_parse_events_skips_statechange_for_damage
    - test_parse_events_emits_heterogeneous_stream_signed_by_event_type
    - test_parse_events_yield_type_is_event_union

### Validation

- ruff check + format: clean (libs + apps)
- mypy libs apps --no-incremental: clean
- pytest libs/gw2_evtc_parser libs/gw2_analytics: 103 passed + 1 skipped
  (the skipped test is the real-EVTC-fixture integration test gated
  on /tmp/inner_20251002-213519 availability)
- Round 51-58 code-reviewer: APPROVED (with minor cleanup notes)

### Migration

The Python surface is fully backward-compatible. ``parse_events```
now yields the union type so callers that explicitly typed the
return as ``list[DamageEvent]``` need to widen to
``list[Event]```. The apps/api ``GET /fights/{id}/events```
route already handles the union via
``TypeAdapter(Event).validate_json(line)```; pre-Phase-7-v2 records
(those with NULL events_blob_uri) continue to surface 404.

[0.5.0-parser]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.4.0-parser...v0.5.0-parser

[0.3.0]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.3.0-web...v0.3.0
## [0.1.0] - Phase 3 analytics prototype

### Added

- `libs/gw2_analytics/src/gw2_analytics/aggregate.py`: the Phase 3 starter.
  Defines four frozen pydantic models and one stateless aggregator:

  - `CombatantSummary`: one player-roster row mirroring parsed
    ``Agent`` data but flattened (string-only subgroup; mandatory
    colon-prefixed account_name; player-only).
  - `SkillCatalogEntry`: one row of the fight\'s skill table
    (skill_id + name).
  - `GroupSummary`: per-subgroup roll-up (subgroup + combatant_count +
    sorted account_names).
  - `FightAggregate`: top-level denormalised view of one fight
    (fight_id, encounter_id, agent_count, player_count + npc_count,
    skill_count, combatants, groups, skill_catalog).
  - `SingleFightAggregator.aggregate(fight: Fight) -> FightAggregate`:
    the canonical entry-point. Deterministic ordering
    (combatants by ``(account_name, name)``, groups by ``subgroup``,
    catalog by ``skill_id``). Cross-field invariants
    (``player + npc == agent``; ``skill_count == len(catalog)``;
    group combatant counts match combatants in that bucket)
    post-validated; violations raise ``ValueError``.

- `libs/gw2_analytics/tests/test_aggregate.py`: 14-test unit suite
  covering empty fight, single player, single NPC, mixed
  players + NPC, deterministic ordering, group roll-up invariants,
  empty-squad subgroup behaviour, frozen-pydantic semantics, and
  ``Fight.id`` / ``encounter_id`` propagation.

- `libs/gw2_analytics/src/gw2_analytics/__init__.py`: re-exports the
  five new public symbols. ``__version__`` bumped to ``0.1.0``.

- `libs/gw2_analytics/pyproject.toml`: version bumped ``0.0.1 -> 0.1.0``.

### Notes

- No event-stream consumer. Target-DPS, damage taken, healing and
  other event-driven aggregates are out of scope for this slice
  and land in a sibling module in a later phase.
- Library surface is intentionally minimal so future
  ``MultiFightAggregator`` / ``SingleEventAggregator`` siblings
  can be added without breaking this contract.

## [0.2.0] - Phase 3 depth: multi-fight rollup

### Added

- ``libs/gw2_analytics/src/gw2_analytics/multi_fight.py``: the Phase 3
  depth sibling of the single-fight aggregator. Defines two frozen
  pydantic models + one stateless aggregator:

  - ``CombatantRollup``: per-account attendance + identity roll-up.
    ``account_name`` + ``name`` (last-seen char-name) + ``profession``
    (first-seen) + ``elite`` (first-seen) + ``player_attendance``.
    Keyed on ``account_name`` -- one row per stable account across
    multiple fights (not one row per agent-record).
  - ``MultiFightAggregate``: ``fight_ids`` (sorted ascending unique
    fight ids) + ``total_agents`` + ``total_players`` +
    ``combatant_rollups`` (sorted by ``account_name``).
  - ``MultiFightAggregator.aggregate(fights: Iterable[Fight]) -> MultiFightAggregate``:
    deterministic ordering; cross-field invariants
    (``total_players == sum(player_attendance)``,
    ``attendance <= len(fight_ids)``,
    ``combatant_rollups`` ordered by ``account_name``,
    ``fight_ids`` strictly ascending) post-validated; violations
    raise ``ValueError``.

- ``libs/gw2_analytics/tests/test_multi_fight.py``: 12-test
  unit suite covering empty input, single fight, disjoint
  fights, overlapping fights (verify ``name`` = last-seen
  + ``profession``/``elite`` = first-seen), full attendance,
  duplicate ``Fight.id`` (with ``caplog``-asserted warning),
  empty-agents drop, all-NPC runs, deterministic ordering,
  frozen-pydantic semantics, lenient-parser WvW ``account_name=None``
  quirk filter, and cross-fight math sums over a 3-fight mixed
  player/NPC run.

- ``libs/gw2_analytics/src/gw2_analytics/__init__.py``: re-exports
  ``CombatantRollup``, ``MultiFightAggregate``,
  ``MultiFightAggregator``.

- ``libs/gw2_analytics/pyproject.toml``: version bumped 0.1.0 -> 0.2.0.

### Changed

- ``libs/gw2_analytics/src/gw2_analytics/__init__.py``:
  ``__version__`` bumped to ``0.2.0``.

### Notes

- Per-fight rollups reuse ``SingleFightAggregator.aggregate(fight)``
  internally, so the WvW empty-account quirk filter and the strict
  ``player_count + npc_count == agent_count`` invariant are unchanged.
- Empty-agents fights are silently dropped (their ``Fight.id`` does
  not appear in ``fight_ids``). Duplicate ``Fight.id`` is silently
  skipped with a ``logging.warning``.
- MultiFight surface is intentionally narrow. Event-derived
  aggregations (``EventWindowAggregator``, ``TargetDpsAggregator``)
  drop into new files in a later phase.
[0.4.0]: https://github.com/Roddygithub/Gw2Analytics/releases/tag/0.4.0
