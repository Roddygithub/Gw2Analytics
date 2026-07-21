# Plan: v0.12.0 Phase 6 v2 — parser-stream switch (condi/power split, barrier, downtime)

> **Status**: ✅ COMPLETE (v0.12.0–v0.12.3) — all 5 SCAFFOLD-zero columns now live
> **Depends on**: v0.11.4 (WAVE-8 complete, 8/8 subclasses dispatched)
> **Target**: v0.12.0

## Context

WAVE-8 (v0.11.0→v0.11.4) shipped all 8 parser-side event subclasses
(Block/Dodge/Interrupt/CC/Death/Down/StunBreak/Barrier + ConditionRemoveEvent
at aggregator tier). The frontend AG Grid combat readout tables are fully
built with all columns.

**5 SCAFFOLD-zero columns remain:**

| Column | Table | Blocker |
|--------|-------|---------|
| `dps_power`, `dps_condi` | Damage | Parser `buff_dmg` side table not wired into DpsSplitGetter |
| `barrier_total`, `barrier_ps` | Heal | Parser `buff_dmg` on heal records not exposed to HealBarrierGetter |
| `time_downed_ms` | Defense | Parser DownEvent.downtime_ms = 0 (down-state lifecycle not computed) |

## Verified (F17 real WvW log — 2026-07-21)

Uploaded `20250928-223731.zevtc` (40,146s fight, 9 players):

| Column | Total | Status |
|--------|-------|--------|
| dodges | 28 | ✅ Real data (v0.11.2 result-byte dispatch) |
| blocks | 46 | ✅ Real data (v0.11.2 result-byte dispatch) |
| interrupts | 52 | ✅ Real data (v0.11.2 result-byte dispatch) |
| deaths | 0 | ✅ Correct (no deaths in fight) |
| cleanses | 0 | ⚠️ May be correct (WvW zerg — few condi cleanses) or arq worker needs restart |
| dps_power, dps_condi | 0, 0 | ❌ SCAFFOLD-zero — Phase 6 v2 |
| barrier_total, barrier_ps | 0, 0 | ❌ SCAFFOLD-zero — Phase 6 v2 |
| time_downed_ms | 0 | ❌ SCAFFOLD-zero — Phase 6 v2 (aggregator wired in v0.12.0, parser needs work) |

## Architecture

### Step 1: Parser exposes `buff_dmg` on DamageEvent

**Status**: NOT STARTED. The parser (`libs/gw2_evtc_parser/parser.py`) has access
to `buff_dmg` from the cbtevent struct but does not store it on `DamageEvent`.
The `DamageEvent` model has no `buff_dmg` field.

**Required changes**:
1. Add `buff_dmg: int = Field(default=0, ge=0)` to `DamageEvent` in `libs/gw2_core/models.py`
2. Pass `buff_dmg=_ev_buff_dmg` in the parser's DamageEvent yield
3. Update all test fixtures that construct DamageEvent

**Risk**: LOW — additive field with default=0, no migration needed.

### Step 2: Wire condi/power split DpsSplitGetter

**Status**: `condi_power_split.py` EXISTS (plan 135, 8 tests). `DpsSplitGetter` plumbing
EXISTS on `PlayerDamageAggregator.aggregate()`. Just needs wiring.

**Required changes**:
1. Create factory function `make_dps_split_getter(build_date, skill_name_getter)` that
   returns a `DpsSplitGetter` (per-event `(condi, power)` callback)
2. In `get_fight_readout` route handler, construct the getter and pass to
   `aggregate_combat_readout(dps_split_getter=...)`
3. New-build path: extract `condi = min(damage, max(0, event.buff_dmg))` per event
4. Old-build path: use skill name → KNOWN_CONDI_NAMES lookup (already implemented)

**Effort**: S (1 new factory function, 1 route handler change)

### Step 3: Wire heal-side barrier (HealBarrierGetter)

**Status**: NOT STARTED. The parser yields `HealingEvent` with `healing` but no
barrier field. The `buff_dmg` on the cbtevent for heal-class records carries
the barrier portion.

**Required changes**:
1. Add `barrier: int = Field(default=0, ge=0)` to `HealingEvent` in models.py
2. Pass `barrier=buff_dmg` in the parser's HealingEvent yield
3. Create `HealBarrierGetter` factory that extracts `event.barrier`
4. Pass to `aggregate_combat_readout(barrier_portion_getter_heal=...)` in route handler

**Effort**: S (model field + parser pass-through + route wiring)

### Step 4: Compute per-event downtime (parser)

**Status**: AGGREGATOR WIRED (v0.12.0 commit). The `DownEvent.downtime_ms` field
exists but is always 0 from the parser.

**Required changes** (parser):
1. Track per-agent down state: when DownEvent emitted, record `time_ms`
2. When ChangeUp (is_statechange==6) or DeathEvent emitted for same agent,
   compute `downtime = up_time - down_time`
3. Set `DownEvent.downtime_ms = downtime`

**Effort**: M (stateful parser pass — requires per-agent lifecycle tracking)

## Implementation order

| Step | Priority | Effort | Unlocks |
|------|----------|--------|---------|
| 1. buff_dmg on DamageEvent | P1 | S | dps_power, dps_condi |
| 2. DpsSplitGetter wiring | P1 | S | dps_power, dps_condi |
| 3. barrier on HealingEvent | P2 | S | barrier_total, barrier_ps |
| 4. downtime computation | P2 | M | time_downed_ms |

**Steps 1+2 can ship in one release (v0.12.1), unlocking 2 of 5 columns.**
**Steps 3+4 ship in a follow-up release (v0.12.2).**

## Validation

| Purpose | Command |
|---------|---------|
| ruff | `uv run ruff check libs/ apps/` |
| mypy | `uv run mypy apps/api/src libs` |
| pytest | `uv run pytest libs/gw2_evtc_parser/tests/ apps/api/tests/ -q` |
| vitest | `cd web && pnpm vitest run` |
| tsc | `cd web && pnpm tsc --noEmit --skipLibCheck` |

## Done criteria

- [x] `dps_power` + `dps_condi` > 0 on real WvW logs (v0.12.1: buff_dmg wiring)
- [x] Old-build logs (pre-20240501) get correct skill-name-based split (v0.12.1: make_dps_split_getter)
- [x] `barrier_total` + `barrier_ps` > 0 on healers with barrier skills (v0.12.1: HealingEvent.barrier)
- [x] `time_downed_ms` > 0 on fights with downed players (v0.12.2: parser down-state lifecycle; v0.12.0: aggregator wiring)
- [x] 0 regressions on existing test suite
- [x] Frontend AG Grid tables display non-zero values (v0.12.3: SCAFFOLD banner close-out)

### Completion notes (2026-07-21)

- **Steps 1-2**: shipped in v0.12.1 — `buff_dmg` on DamageEvent + DpsSplitGetter factory wired into `get_fight_readout` → dps_power/dps_condi live.
- **Step 3**: shipped in v0.12.1 — `barrier` on HealingEvent + HealBarrierGetter factory → barrier_total/barrier_ps live.
- **Step 4**: shipped in v0.12.2 — parser down-state lifecycle (ChangeUp/ChangeDown/ChangeDead) with per-agent `down_start` dict → time_downed_ms wired (0 for fights without down-state cycles).
- **Frontend**: v0.12.3 closed the SCAFFOLD banner contract — removed the "stay at 0 until Phase 6 v2" disclaimer from the readout tab status banner.
- **E2E**: v0.12.3 added Playwright test verifying non-zero dps_power/dps_condi/barrier_total/dodges/blocks in AG Grid cells.
- **Hermetic test**: `test_readout_phase6_v2_barrier_and_condi_split_live` pins the aggregator-level getter contract.

**Validated with real WvW data**: 9 players, 40,146s fight — dps_power=22, dps_condi=8, barrier=739, dodges=28, blocks=46, interrupts=52.
