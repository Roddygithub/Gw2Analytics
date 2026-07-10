# Plan 001 — Add API test coverage for `routes/player_compare.py`

- **Slug:** `001-api-tests-player-compare`
- **Priority:** P1
- **Effort:** M (3–4 hours)
- **Risk:** Low
- **Confidence:** 1.0
- **Status:** open

## Why

`apps/api/src/gw2analytics_api/routes/player_compare.py` exposes the cross-account timeline endpoint (`GET /api/v1/players/compare/timeline`) shipped in v0.10.0 cycle item C (per `CHANGELOG.md` and the consumer at `web/src/app/players/compare/page.tsx`). No `apps/api/tests/test_player_compare*.py` exists — the **only** runtime coverage is the mock-server endpoint in `web/tests/e2e/mock-server.mjs`, which serves the frontend e2e but does NOT pin the backend contract.

Without pytest contract tests, the route's bounds (2–4 accounts), recency-first ordering, day-bucketing aggregation, and the `422` response on invalid IANA `tz=` are regression-fragile. A silent sort inversion or off-by-one limit would propagate straight to the comparison UI.

## Scope

**In scope:**
- `apps/api/tests/test_player_compare.py` (NEW — pytest contract tests).
- Minor edits to `apps/api/src/gw2analytics_api/routes/player_compare.py` ONLY IF a regression is found while writing tests; otherwise the file stays untouched.

**Out of scope:**
- `web/tests/` (e2e + frontend tests already exist).
- Other routes.
- Any aggregator or Pydantic model changes.

## Files to reference (exemplar)

- `apps/api/tests/test_players.py` — per-route test pattern; uses `_fixtures.make_cbtevent` + `_fixtures.post_minimal_fight` + `pytest`'s `client` + `get_sessionmaker` fixtures from `apps/api/tests/conftest.py`.
- `apps/api/tests/conftest.py` — autouse `_isolate_test_state` fixture wipes `webhook_subscriptions`, `webhook_deliveries`, `webhook_dlq`, `uploads`, `fights`, `fight_player_summaries` before each test.
- `apps/api/src/gw2analytics_api/routes/player_compare.py` — the route under test.

## Steps

1. Read `apps/api/src/gw2analytics_api/routes/player_compare.py` end-to-end. Identify the contract branches:
   - `[accounts < 2]` → 422 (out-of-range, by `Query(min_length=2)`).
   - `[accounts > 4]` → 422 (by `Query(max_length=4)`).
   - Unknown account among the 2–4 → JSON `points: []` (NOT 404).
   - Unknown IANA `tz=` + KNOWN account → 422.
   - Recency-first ordering of `points` (newest fight first).
   - `bucket=day` aggregates midnight-in-tz (UTC default).

2. Read `apps/api/tests/test_players.py` + `apps/api/tests/conftest.py` for fixture conventions: `_fixtures.make_cbtevent(seed_rgb=(base_id, base_id, base_id))`, `_fixtures.post_minimal_fight(events, suffix=_uuid.uuid4().hex[:8])` for unique-suffix isolation.

3. Write `apps/api/tests/test_player_compare.py` with 8 hermetic cases:
   - `test_player_compare_timeline_2_accounts_recency_first`
   - `test_player_compare_timeline_3_accounts_max_unique`
   - `test_player_compare_timeline_4_accounts_inclusive_max`
   - `test_player_compare_timeline_1_account_returns_422`
   - `test_player_compare_timeline_5_accounts_returns_422`
   - `test_player_compare_timeline_unknown_account_returns_empty_points`
   - `test_player_compare_timeline_unknown_tz_returns_422`
   - `test_player_compare_timeline_day_bucket_default_tz`

   Use the `test_players.py::test_player_profile_*` structure for client invocation (`response = client.get(...)` → assert `response.status_code` + `response.json()`).

4. Run pytest + ruff + mypy on the new file. Confirm no flakes.

## Done criteria

```bash
test -f apps/api/tests/test_player_compare.py                                                       # exit 0
uv run pytest --collect-only -q apps/api/tests/test_player_compare.py                              # 8 tests collected
uv run pytest apps/api/tests/test_player_compare.py                                                # PYTEST=0 (8 passed)
uv run ruff check apps/api/tests/test_player_compare.py                                            # RUFF=0
uv run mypy --no-incremental apps/api/tests/test_player_compare.py                                  # MYPY=0
git diff --name-only apps/api/tests/test_player_compare.py                                          # only the new file appears
```

## Maintenance note

If `routes/player_compare.py` adds a new query param or response field (per `CrossAccountTimelineOut` schema), this file MUST grow the matching clause. Do NOT remove the recency-first ordering or empty-on-unknown-account assertions — both are documented contract properties the frontend depends on.

## Escape hatch

If `_fixtures.make_cbtevent`/`post_minimal_fight` cannot seed 2–4 unique accounts on a single fight row out-of-the-box, STOP and add the missing helper to `apps/api/tests/_fixtures.py` first, rather than inlining raw SQLAlchemy in the test file.
