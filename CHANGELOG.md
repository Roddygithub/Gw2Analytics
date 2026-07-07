# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

## [0.2.0] - gw2_core 0.2.0: API-data models (Phase 4 prep)

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

[Unreleased]: https://github.com/Roddygithub/Gw2Analytics/compare/a67e672...HEAD
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
