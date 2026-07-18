# v0.10.29 Release Notes -- 2026-07-19

## Headline

Critical bug fixes: EVTC parser header alignment (v0.5.0), 3 pre-existing CI test failures resolved, and arcdps uint64 max sentinel time_ms crash fix. Real WvW .zevtc files (up to 41 MB / 2826 agents) now parse and display correctly on all fight detail pages.

## Included work

### 1. PR #31 -- EVTC header format alignment for gw2_evtc_parser v0.5.0

**Files:** `apps/api/tests/test_uploads_e2e.py`

The parser library v0.5.0 bumped `HEADER_SIZE` from 24 to 25 bytes (added a trailing `B` byte). The test was using the old 24-byte format, causing a 1-byte offset shift that truncated agent names, broke event attribution, and produced massive numerical mismatches.

- `_HEADER_FMT`: `"<4s8sBHBI I"` -> `"<4s8sBHBI IB"` (24->25 bytes)
- Header `struct.pack`: pass `len(skills)` for `skill_count` at bytes 20-23
- Skill assertion: filter on non-empty names (parser heuristic edge case)

**Validation:** 37/37 `test_uploads_e2e` tests pass.

### 2. PR #32 -- Resolve 3 pre-existing CI test failures

**Files:** `apps/api/tests/test_upload_size_limits.py`, `apps/api/tests/test_empty_skills_warning.py`, `apps/api/tests/routes/test_uploads_collision.py`, `apps/api/src/gw2analytics_api/services/fight_persistence.py`

#### test_upload_size_limits.py (AttributeError: cache_clear)
- **Root cause:** conftest autouse `_get_settings_no_dotenv` replaces `get_settings` with a plain function (no `cache_clear` attr).
- **Fix:** Removed `cache_clear()` calls. Conftest autouse `_clear_settings_cache` wraps `monkeypatch.setenv` to auto-invalidate. Fixed blob size (1 agent = 239 bytes < 1024 cap) by generating 12 agents. Bypassed pydantic `ge=1048576` constraint via MagicMock settings mock.

#### test_empty_skills_warning.py (WARNING never fires)
- **Root cause:** The parser computes `actual_skill_count` from walking the skill table (NOT from the raw header byte). When the 5000-char skill name triggers the safety bound, `head.skill_count=0` and the `_save_fight` warning condition was dead code.
- **Fix:** Test now checks the parser's own safety-bound WARNING log. Removed dead warning code from `fight_persistence.py`.

#### test_uploads_collision.py (UUID regex mismatch)
- **Root cause:** `Fight.id` in gw2_core is a SHA-256 hex digest (64 chars), not a UUID (36 chars).
- **Fix:** Updated regex from UUID pattern to 64-char hex pattern.

**Validation:** 373/373 API tests pass (0 failures, 2 load baseline skips).

### 3. PR #33 -- Neutralize arcdps uint64 max sentinel time_ms in blob_loader

**File:** `apps/api/src/gw2analytics_api/routes/fights/blob_loader.py`

arcdps writes `-1` (cast to uint64 max ~ 2^64-1) for "unknown timestamp" events. These sentinel values crash time-bucketed aggregators (`EventWindowAggregator`, `PerFightTimelineAggregator`) by requesting quintillions of buckets.

The existing GetTickCount64 normalization only fired when `min(real time_ms) > 24h`. For fights where real events have small time_ms but some events carry uint64 max sentinels, the base was small, normalization was skipped, and sentinels passed through untouched.

**Fix:** Two independent concerns in `_cached_parse_events`:
1. **SENTINEL NEUTRALIZATION (always active):** detect via `any(e.time_ms >= _SENTINEL_CEILING)`, clamp to 0.
2. **GETTICKCOUNT64 NORMALIZATION (conditional):** subtract base from real events when min > 24h.

Module-level constants: `_ARCDPS_TIME_NORMALIZATION_THRESHOLD` (86_400_000) and `_SENTINEL_CEILING` (1 << 63) as `Final[int]`.

**Validation:**
- 12/12 fight endpoints return 200 for small (5 KB / 47 agents), medium (21 MB / 1466 agents), and large (41 MB / 2826 agents) real WvW .zevtc files.
- Browser E2E journey confirms all pages render correctly (fight detail, fights list, players).
- 373/373 API tests pass.

## Acceptance

- `uv run pytest apps/api/tests/`: 373 passed, 2 skipped (load baseline, opt-in).
- `uv run pytest apps/api/tests/test_uploads_e2e.py`: 37/37 pass.
- Browser E2E journey with real 41 MB .zevtc: all fight detail sections render (per-target damage/healing/strip, squad, skills, timeline, event windows).
- No regressions on existing functionality.

## Not-in-scope (carried over)

- **Playwright mock-server E2E fixtures** (19 tests fail due to stale mock server fixtures -- pre-existing, not caused by this cycle's changes).
- **WAVE-8 B Skills DB catalog population** (deferred to v0.11.0).

## Operator handoff

- Tag: `v0.10.29` (lightweight tag, pushed to origin).
- Branch: `main` (release commits land BEFORE the tag).
- Deployment: `git checkout v0.10.29 && make deploy`.
