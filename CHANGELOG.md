# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (Phase 7 v1 -- parser-side event-stream consumer + apps/api /events wire-up)

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
