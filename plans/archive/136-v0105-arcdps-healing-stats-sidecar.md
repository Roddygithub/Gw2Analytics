# Plan 136: arcdps_healing_stats sidecar JSON loader (additive)

> **Executor instructions**: This is a future-sprint plan. Captures
> the multi-format probing pattern from the arcdps_healing_stats
> addon for the v0.10.5 cycle. Re-implement with our targeted-
exceptions convention (no blanket `except Exception: pass`).
> — re-implement with our targeted-exceptions convention (no
> blanket `except Exception: pass`).

> **Drift check (run first)**: `git diff --stat HEAD~1..HEAD -- apps/api/src/gw2analytics_api/services.py libs/gw2_analytics/src/gw2_analytics/`
> If any in-scope file changed, compare against the live code before proceeding.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plan 137 (buff_uptime Pydantic model — same merge target)
- **Category**: feature / analytics accuracy
- **Planned at**: commit `c935acb`, 2026-07-10 (documentation only)

## Why this matters

The `arcdps_healing_stats` addon
(https://github.com/Krappa322/arcdps_healing_stats) emits a sibling
JSON next to the `.zevtc` containing per-skill heal/barrier breakdowns
NOT carried in the binary event stream. Without the sidecar, our
post-v0.10.5 per-skill healing breakdown is incomplete (CBTR_HEAL on
arcdps 2023+ carries skillid=0 for everything that wasn't a hot tick;
the sidecar fills in the actual skill buckets).

a public GW2 community reference implementation's calibration 2025-12 documents the EXTENSION vs
native CBTR_HEAL double-count trap: 140/316 DH (pure-DPS spec) rows
logged impossible 1.7M HP / 83s before the `seen_native_heal` gate
was added. The gate suppresses the EXTENSION path once a native
`CBTR_HEAL` or `CBTR_BUFFHEAL` event is seen in the same fight.

## Source calibration (do not copy code)

a public GW2 community reference implementation `_load_healing_sidecar()` probes three sources in
priority order:

1. **Inline JSON inside the .zevtc archive** — some logging tools
   bundle the sidecar inside the zip. Probe every entry whose name
   ends in `.json` or `.healing.json`.
2. **Sibling file alongside the .zevtc/.evtc** — basename-strip
   then probe the suffixes `.healing.json`, `_healing.json`, `.json`
   against the parent directory.
3. **None** — return None cleanly. A missing sidecar is NOT a
   failure (the addon is opt-in).

The merge contract is **sidecar updates `acc.healing_by_skill[sid]`
only — it does NOT touch `acc.healing` totals**. The native
`CBTR_HEAL`/`CBTR_BUFFHEAL` events are the canonical heal totals;
the sidecar addon derives from the same EXTENSION stream and would
double-count. The merge is gated behind the `seen_native_heal` flag
in a public GW2 community reference implementation's calibration.

## Current state

Our project has `apps/api/parsers` only (the route handlers and
services that drive the parser output). The sidecar JSON is not
currently loaded. A future v0.10.5 ingest could extract the sidecar
in `services.py::_persist_event_blob` and merge it into the same
`OrmFightPlayerSummary` write path.

The current schema `OrmFightPlayerSummary` has:
`total_damage / total_healing / total_buff_removal / detected_role / detected_tags`.

A future additive migration would add `healing_by_skill JSONB NULLABLE`
+ `barrier_by_skill JSONB NULLABLE` for the sidecar's per-skill
buckets. Pydantic v2 Pydantic-style: nullable for back-compat.

## Repo conventions

- Sidecar loader in `libs/gw2_analytics/` (NOT in the parser), per
  the project's parse/aggregate separation convention.
- Targeted exceptions only. No `except Exception: pass`. Use
  `(json.JSONDecodeError, ValueError, OSError)`.
- Modelled on existing `app/parsers/role_detection.py` style: stateful
  counters as module-level singletons with `get_*`/`reset_*` accessors.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `uv run ruff check libs/gw2_analytics/src/gw2_analytics/sidecar.py` | exit 0 |
| Typecheck | `uv run mypy --no-incremental libs/gw2_analytics/src/gw2_analytics/sidecar.py` | exit 0 |
| Tests | `uv run pytest libs/gw2_analytics/tests/test_arcdps_sidecar.py -v` | all pass |

## Scope

**In scope** (when executed):
- `libs/gw2_analytics/src/gw2_analytics/sidecar.py` — multi-format probe + merge contract
- `libs/gw2_analytics/tests/test_arcdps_sidecar.py` — hermetic tests with a temp .zevtc fixture
- Optional additive schema migration: `healing_by_skill JSONB` + `barrier_by_skill JSONB` on `fight_player_summaries`

**Out of scope**:
- `libs/gw2_evtc_parser/` — sidecar is downstream of the parser's struct decode
- Anything related to copying a public GW2 community reference implementation code wholesale — re-implement with our conventions

## Steps (for future executor)

### Step 1: `sidecar.py` — multi-format probe

Three-suffix probe (`.healing.json`, `_healing.json`, `.json`),
matching the addon variants documented by a public GW2 community reference implementation's
`SIDECAR_BASENAME_SUFFIXES` constant. Targeted exception handling
per suffix — never blanket `except Exception`.

### Step 2: Merge contract

Pure function `merge_sidecar_into_summary(summary, sidecar)` that
updates `summary.healing_by_skill[sid] += amount` for each entry in
`sidecar["players"].healingBySkill`. Does NOT touch `summary.healing`
totals (see calibration 2025-12).

### Step 3: Calibration telemetry counters (calibration patterns)

Three module-level counters with `get_*`/`reset_*` accessors:
- `sidecar_load_attempts` / `sidecar_load_failures` — quantifies how
  many real-world uploads ship the sidecar.
- `dropped_position_samples` — only if position heatmap (plan differs).
- `skipped_unresolvable_heals` — EXTENSION handler increment.

These are "diagnostic counters" used by future calibration runs to
quantify source-side coverage. Documented in plan 137.

### Step 4: Wire into ingestion

In `services.py::_persist_event_blob`, after the bulk INSERT of the
per-fight summary rows:
1. Probe the sidecar via `libs/gw2_analytics.sidecar.probe(zevtc_path)`.
2. For each summary row, call `merge_sidecar_into_summary` with the
   per-row entries matched by `account_name` (case-insensitive).
3. `db.commit()` once at the end. If the sidecar probe fails with a
   targeted exception, log + continue (graceful degradation).

## Test plan

- 3 NEW hermetic tests:
  1. Inline sidecar inside .zevtc archive — probe finds it on first attempt.
  2. Sibling `.healing.json` file — probe finds it as fallback.
  3. No sidecar anywhere — returns None cleanly. No swallowed exceptions.
- 1 integration test (live DB) — fight + sidecar file → summary rows have non-empty `healing_by_skill` map.

## Done criteria

- [ ] `uv run ruff check libs/gw2_analytics/src/gw2_analytics/sidecar.py` exits 0
- [ ] `uv run mypy --no-incremental libs/gw2_analytics/src/gw2_analytics/sidecar.py` exits 0
- [ ] `uv run pytest libs/gw2_analytics/tests/test_arcdps_sidecar.py -v` — 3 NEW tests pass
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- If the addon URL `arcdps_healing_stats` home moves or its JSON
  schema changes, the test fixtures need to be regenerated. Verify
  against the addon repo before implementing.
- If `OrmFightPlayerSummary` model signature changes (relationship
  cascade rename, etc.), the merge contract wiring is invalidated.

## Maintenance notes

- The probe order (inline → sibling → None) matches what the
  addon-side bundlers emit in practice. Reverse the order only with
  fresh calibration data.
- We do NOT run a live network call to validate the sidecar
  (a public GW2 community reference implementation's `_fetch_profession_name` is a known antipattern
  we explicitly avoid).
- The `seen_native_heal` gate suppresses EXTENSION-path double-counting
  on arcdps 2023+ logs. Without the gate, DH (a pure-DPS spec) reports
  95k+ outgoing heals on logs that lack the sidecar (a side-effect of
  the EXTENSION channel misattribution to the logger's PoV).
- The merge is OPTIONAL: arcdps_healing_stats is an opt-in addon. The
  sidecar probe returns None cleanly when absent.
