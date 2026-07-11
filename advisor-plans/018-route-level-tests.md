# Plan 018 — Route-level tests for all aggregation endpoints + `_persist_player_summaries`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f0249ef..HEAD -- apps/api/tests/ apps/api/src/gw2analytics_api/routes/ apps/api/src/gw2analytics_api/services.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `f0249ef`, 2026-07-11

## Why this matters

The API has 353 pytest tests but **zero** direct route-level tests for the aggregation endpoints (`/fights/{id}/events`, `/fights/{id}/timeline`, `/fights/{id}/squads`, `/fights/{id}/skills`, `/players`, `/players/{name}`). Only the end-to-end happy-path (`test_uploads_e2e.py`) exercises these routes, which means wrong status codes, malformed responses, or query-param parsing bugs pass CI undetected. The `_persist_player_summaries` function (247 lines of complex logic: condi/power split, role detection, re-parse safety, NUL sanitization) has **zero** dedicated tests — only coverage is indirect through E2E.

## Current state

- `apps/api/tests/` — 29 test files, none testing route handlers directly
- `apps/api/src/gw2analytics_api/routes/fights.py:88-151` — `_load_fight_events` raises HTTPException(404) for missing fight, HTTPException(404) for missing blob, HTTPException(502) for corrupt blob, HTTPException(404) for empty events
- `apps/api/src/gw2analytics_api/routes/players.py:80-118` — `_compute_contributions` hybrid fast-path/slow-path dispatch
- `apps/api/src/gw2analytics_api/services.py:461-708` — `_persist_player_summaries` (247 lines): source_map, name/profession anchor, condi/power split, role detection, re-parse DELETE+INSERT

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `uv sync` | exit 0 |
| Tests | `uv run pytest apps/api/tests/ -x -q` | all pass |
| Lint | `uv run ruff check apps/api/` | exit 0 |
| Typecheck | `uv run mypy apps/api/src/` | exit 0 |

## Scope

**In scope**:
- `apps/api/tests/test_fights_events.py` (NEW)
- `apps/api/tests/test_fights_timeline.py` (NEW)
- `apps/api/tests/test_fights_squads.py` (NEW)
- `apps/api/tests/test_fights_skills.py` (NEW)
- `apps/api/tests/test_players_list.py` (NEW)
- `apps/api/tests/test_players_detail.py` (NEW)
- `apps/api/tests/test_persist_player_summaries.py` (NEW)

**Out of scope**:
- `test_uploads_e2e.py` (existing; leave untouched)
- Route handler logic changes (only add tests)
- Player compare route (separate test file exists)

## Steps

### Step 1: Create `test_fights_events.py`

Test `GET /api/v1/fights/{id}/events` using FastAPI `TestClient` with synthetic data that seeds the DB directly and mocks `get_events` to return known gzipped JSONL bytes.

Cases:
- `test_events_200` — valid fight_id, 10 events (mix of DamageEvent + HealingEvent), returns 200 with correct structure
- `test_events_404_fight_not_found` — unknown fight_id returns 404
- `test_events_404_no_blob` — fight exists but `events_blob_uri` is None returns 404
- `test_events_502_corrupt_blob` — blob is non-gzip bytes returns 502
- `test_events_404_empty_events` — blob is valid gzip but empty JSONL returns 404
- `test_events_window_s_param` — `?window_s=10` returns properly bucketed events

Use `app = TestClient(main.app)`. Seed the DB with SQLAlchemy inserts in a session. Mock `get_events` from `storage` to return fixture gz bytes.

**Verify**: `uv run pytest apps/api/tests/test_fights_events.py -x -v` → 6 tests pass

### Step 2: Create `test_fights_timeline.py`

Same pattern. Test `GET /api/v1/fights/{id}/timeline`.

Cases:
- `test_timeline_200_default_window` — default 5s window
- `test_timeline_200_custom_window` — `?window_s=10`
- `test_timeline_422_out_of_bounds` — `?window_s=0` returns 422, `?window_s=601` returns 422
- `test_timeline_404_no_fight` — unknown fight
- `test_timeline_404_no_blob` — no events blob

**Verify**: `uv run pytest apps/api/tests/test_fights_timeline.py -x -v` → 5 tests pass

### Step 3: Create `test_fights_squads.py` and `test_fights_skills.py`

Each with 3-4 cases covering 200, 404, and edge cases.

**Verify**: `uv run pytest apps/api/tests/test_fights_squads.py apps/api/tests/test_fights_skills.py -x -v` → all pass

### Step 4: Create `test_players_list.py`

Test `GET /api/v1/players` with pagination and filters.

Cases:
- `test_list_200` — returns correctly shaped list
- `test_list_profession_filter` — `?profession=MESMER` filters
- `test_list_offset_limit` — pagination works
- `test_list_empty` — no players returns `[]`

**Verify**: `uv run pytest apps/api/tests/test_players_list.py -x -v` → all pass

### Step 5: Create `test_players_detail.py`

Test `GET /api/v1/players/{name}`.

Cases:
- `test_detail_200` — player with fights returns profile
- `test_detail_404` — unknown player
- `test_detail_zero_magnitudes` — player with fights but zero damage/healing/strip

**Verify**: `uv run pytest apps/api/tests/test_players_detail.py -x -v` → all pass

### Step 6: Create `test_persist_player_summaries.py`

Unit-test `_persist_player_summaries` directly. Import it from `services.py`. Requires an in-memory SQLite SQLAlchemy session (use `create_engine("sqlite://")` + `sessionmaker`). Mock `detect_role_lite` to return `("DPS", [])`.

Cases:
- `test_single_player_single_damage` — 1 agent, 1 DamageEvent → 1 summary row with correct totals
- `test_multiple_players` — 2 agents → 2 summary rows, correct per-account
- `test_npc_only_fight` — 0 player agents → 0 summary rows
- `test_reparse_delete_insert` — call twice → identical totals
- `test_condi_power_split` — DamageEvent with Bleeding skill → `power_damage=0, condi_damage=event.damage`
- `test_nul_sanitization` — name with `\x00` bytes → stripped correctly
- `test_empty_account_name_guard` — player agent with empty `account_name` → 0 rows
- `test_mixed_event_types` — DamageEvent + HealingEvent + BuffRemovalEvent → all 3 magnitudes correct
- `test_role_detection_invoked` — verify `detect_role_lite` called with correct args

**Verify**: `uv run pytest apps/api/tests/test_persist_player_summaries.py -x -v` → 9 tests pass

## Test plan

All tests above. Total: ~35 new hermetic tests (FastAPI TestClient + pure unit). Follow the pattern in `test_uploads_e2e.py` for seeding fixtures and `test_player_profile.py` for the summary tests.

## Done criteria

- [ ] `uv run pytest apps/api/tests/ -x -q` exits 0 (all ~388 tests pass)
- [ ] 7 new test files exist with ~35 total test cases
- [ ] `uv run ruff check apps/api/` exits 0
- [ ] `uv run mypy apps/api/src/` exits 0
- [ ] No files outside the in-scope list are modified (`git status`)

## STOP conditions

Stop and report back if:
- The route handler signatures in `fights.py`/`players.py` don't match the excerpts above (drift).
- `TestClient` with synthetic DB requires non-trivial conftest changes.
- A test requires modifying production code (only tests should change).

## Maintenance notes

When a new aggregation endpoint is added, a corresponding test file should follow the same pattern. The `_persist_player_summaries` tests exercise the most complex 247 lines in the API; any change to condi/power split or role detection must add corresponding test cases here.
