# Plan 026 — Phase 9 condition-damage tracking (buff apply/remove distinction)

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md`.

> **Drift check (run first)**: `git diff --stat HEAD~6..HEAD -- libs/gw2_core libs/gw2_analytics libs/gw2_evtc_parser apps/api/src/gw2analytics_api/services/event_blob.py`
> If any in-scope file changed since this plan was last updated, compare the "Current state" excerpts against the live code before proceeding.

## Status

- **Priority**: P2
- **Effort**: L (Parts 1+1.5+3 ship; Parts 2-EMIT + 4 + 5 BLOCKED behind new Part 1.5-SYNC)
- **Risk**: HIGH (calibration round revealed parser struct misalignment)
- **Depends on**: plan 024 (combat-readout spike, DONE), plan 137 (buff_uptime Pydantic model, DONE), plan 138 (revision-aware parser plugins, DEFERRED).
- **Category**: analytics
- **Planned at**: commit `3c524d9`, 2026-07-11
- **Rewritten at**: 2026-07-11 (post-arcdps.h verification round, commit `aff55ae`)
- **Calibration-foundations rewrite at**: 2026-07-11 (after F1 empirical byte-distribution forensic on a real WvW dump surfaced Theory B -- the parser struct is NOT 1:1 aligned with arcdps.h)

## Why this matters

The v0.10.6 cycle landed `buff_uptime.py` + `buff_dispatch.py` in `libs/gw2_analytics`. Three gaps remain before the analyst surface is composable. The most recent gap surfaced empirically:

1. **`buff_dispatch` enum mappings are SWAPPED vs arcdps.h.** Plan 137 (v0.10.5) shipped a 3-way decoder mapping `1→REMOVE_SINGLE, 2→REMOVE_ALL` but arcdps.h `cbtbuffremove` is `0=NONE, 1=ALL, 2=SINGLE, 3=MANUAL`. The project's mapping is the reverse for `1`/`2`. Realignment shipped via commit `529cb90` (Phase 9 step 4).
2. **The parser does not produce buff-apply events.** `parse_events` reads the 64-byte cbtevent records but does not surface the arcdps `is_buffremove` byte to the discriminated-union `Event` stream. The byte has been EXPOSED (Phase 9 step 2-PARTIAL via commit `328833d`) but the EMIT branch that yields `BoonApplyEvent` records is deferred pending struct audit + real-arcdps-dump calibration.
3. **The parser's `_EVENT_STRUCT` is NOT 1:1 aligned with arcdps.h.** Confirmed by the 2026-07-11 calibration round below. The struct has 3 uint16s where arcdps has 4 (missing `dst_master_instid`) + 8 single-byte slots where arcdps has 12 (covering only `iff, buff, result, is_activation, is_buffremove, is_ninety, is_fifty, is_moving`, dropping `is_statechange, is_flanking, is_shields, is_offcycle`!) + 2 uint32 slots where arcdps has 4 pad bytes. **This is the calibrate-or-correct blocker that gates Step 2-EMIT.**

This rewrite documents (a) the struct-math proof that misalignment exists, (b) the empirical byte-distribution evidence, (c) the new Step 1.5-SYNC prerequisite that must complete BEFORE Step 2-EMIT.

## Calibration findings (2026-07-11 F1 round)

The empirical byte-distribution forensic on the smallest real arcdps dump (`/home/roddy/WvW_Analytics/uploads/5b161ec03d544b0c96eeb6689590ece4.zevtc`, 75,091 bytes, 5,883 cbtevent records, build `'20250925'`) produced this distribution across the 8 single-byte slots in our parser's struct (offsets 46-53):

| Slot idx | Current label | Our byte | Zero % | One % | Other % | arcdps.h spec byte |
|---:|---|---:|---:|---:|---:|---|
| 10 | `_is_cleanup` | 46 | 42.90 % | 0.10 % | 57.00 % | n/a (would be `dst_master_instid` low byte in 4-H scheme) |
| 11 | `is_nondamage` | 47 | 77.07 % | 0.32 % | 22.61 % | n/a (would be `dst_master_instid` high byte in 4-H scheme) |
| 12 | `is_statechange` | 48 | 77.78 % | 0.07 % | 22.15 % | per spec: `iff` (Friend/Friendly flag) |
| 13 | `_is_flanking` | 49 | 80.40 % | 0.14 % | 19.46 % | per spec: `buff` |
| 14 | `_is_shields` | 50 | 81.88 % | 0.10 % | 18.02 % | per spec: `result` |
| 15 | `_is_offcycle` | 51 | 92.13 % | 0.05 % | 7.82 % | per spec: `is_activation` |
| 16 | `is_buffremove` | 52 | 96.28 % | 0.05 % | 3.67 % | **per spec: `is_buffremove` ✓ (matches!)** |
| 17 | `is_ninety` | 53 | 97.20 % | 0.05 % | 2.75 % | per spec: `is_ninety` ✓ (matches!) |

The struct doc-comment claimed "the existing damage / heal / strip pipeline works empirically"; calibration shows this is true by ACCIDENT, not by design. The `if is_statechange != 0: continue` filter in `parse_events` (line ~341 of parser.py) is reading byte 48 of our struct -- which per the spec is arcdps's `iff` (Friend/Foe flag), NOT `is_statechange`. The filter correctly skips the wrong field (Friend records when it intends to skip statechange records) because in this WvW dump both populations happen to be ~22-23 % non-zero.

### Struct-math proof (independent of the empirical forensic)

The arcdps `cbtevent` struct (per `<GW2-ArcDPS-Mechanics-Log>/src/arcdps_datastructures.h` -- the community-port mirror of `arcdps.h`, cross-checked against arcdps's own `evtc/README.txt` at `https://www.deltaconnected.com/arcdps/evtc/README.txt`):

```
bytes  0-23: 3 × uint64  (time, src_agent, dst_agent)
bytes 24-31: 2 × int32   (value, buff_dmg)
bytes 32-39: 2 × uint32  (overstack_value, skillid)
bytes 40-47: 4 × uint16  (src_instid, dst_instid, src_master_instid, dst_master_instid)
bytes 48-59: 12 × uint8  (iff, buff, result, is_activation, is_buffremove,
                           is_ninety, is_fifty, is_moving, is_statechange,
                           is_flanking, is_shields, is_offcycle)
bytes 60-63: 4 × pad     (pad61, pad62, pad63, pad64)
```

Our parser's `_EVENT_STRUCT = struct.Struct("<QQQiiIIHHHbbbbbbbbIIbb")` decodes as:

- 3 × uint64 (0-23) ✓
- 2 × int32 (24-31) ✓
- 2 × uint32 (32-39) ✓
- 3 × uint16 (40-45) ← MISSING `dst_master_instid` (46-47 offset) -- arcdps has 4 H's, we have 3
- 8 × uint8 (46-53) ← covers arcdps's `dst_master_instid` (low+high bytes) + `iff, buff, result, is_activation, is_buffremove, is_ninety` -- we DROP `is_fifty, is_moving, is_statechange, is_flanking, is_shields, is_offcycle` (6 fields)
- 2 × uint32 (54-61) ← covers arcdps's `is_fifty + is_moving + is_statechange + is_flanking + is_shields + is_offcycle` (6 single-byte fields) AS ONE 8-byte word -- we read garbage as `_pad63, _pad64`
- 2 × uint8 (62-63) ← covers arcdps's `pad63 + pad64` -- correct

The net effect: 6 arcdps.h single-byte fields are swallowed into our 2 uint32 slot and never read. The `is_statechange` flag (which gates the damage / heal / strip / buff-emit branches) is at arcdps.h byte 56 -- in our shifted struct, this byte falls inside `_pad63` (upper half of the first uint32).

### Concrete consequences for the existing pipeline

The parser's `parse_events` loop reads:

```python
_is_cleanup,            # byte 46 (our label: dst_master_instid low per arcdps)
is_nondamage,           # byte 47 (our label: dst_master_instid high per arcdps)
is_statechange,         # byte 48 (our label: iff per arcdps)  ← WRONG FIELD
_is_flanking,           # byte 49 (our label: buff per arcdps)
_is_shields,            # byte 50 (our label: result per arcdps)
_is_offcycle,           # byte 51 (our label: is_activation per arcdps)
is_buffremove,          # byte 52 (our label: is_buffremove per arcdps) ✓
is_ninety,              # byte 53 (our label: is_ninety per arcdps) ✓
```

The **filter** `if is_statechange != 0: continue` (line ~341) is actually filtering on arcdps's `iff` byte (Friend/Foe flag; `iff=0` is friend, `iff=1` is enemy). The filter KEEPS records where `iff=0` (friend-target damage) and SKIPS records where `iff≠0` (enemy-target damage). **The damage-rollup `target_dps` is therefore biased toward FRIEND-target damage; enemy-target damage is dropped.** This is the OPPOSITE of what WvW semantics produce — most damage in a WvW raid is dealt TO enemies, so enemy-target damage is the bulk of the real signal. Pre-SYNC `target_dps` significantly undercounts for enemy agents. *(Corrected after 2026-07-11 reviewer feedback: the original draft stated "yields FRIEND AND skips FRIEND" which was self-contradictory.)*

The **damage vs heal branching** on `is_nondamage` (byte 47 = arcdps's `dst_master_instid` high byte) reads the high byte of the target's instance ID. Instance IDs in arcdps are typically small integers (often < 256 for active agents, 0 for no-master) so the high byte is mostly 0 — which the parser interprets as `is_nondamage == 0` (i.e., the damage path). **This is WHY the damage-vs-heal split LUCKILY works**: small instance IDs → high byte is 0 → the bulk of records are classified as damage (~85 % of events in WvW fixtures are damage records per the post-SYNC run). The pipeline is correct BY COINCIDENCE on this filter — a future arcdps revision that uses large instance IDs would break the split. *(Corrected: the original draft hypothesised the high byte was random and would classify ~99 % as heals, which is empirically wrong since small instids keep the high byte at zero.)*

The **`is_buffremove` byte** (slot 16, byte 52) IS correctly positioned by structural coincidence -- the missing `dst_master_instid` uint16 collapses the single-byte region start by 2, and the missing 4 uint8s at the tail collapse the end by 4, with net zero offset for byte 52 specifically. So the `buff_dispatch` decoder (Phase 9 step 4, commit `529cb90`) reads the right byte.

## Real arcdps fixtures available (PRIOR calibration-blocker resolved)

12 real `.zevtc` fixtures exist on this system, including WvW dumps from the in-product ingestion pipeline:

- `/home/roddy/Downloads/20260604-230254.zevtc` (synthesized or downloaded)
- `/home/roddy/WvW_Analytics/uploads/{5b6c..., 97bb..., c505..., 6021..., eeae..., 9240..., 3a28..., d1c3..., 2da5..., ef66...} × 10` (production user uploads, 75 KB to ~12 MB)

Sizes: smallest is 75 KB (5,883 events, probed in the 2026-07-11 calibration), largest is ~12 MB (~600K events). Boon density (Quickness, Might, Stability) varies per encounter; the calibration round can iterate over all 12 with the same diagnostic script. Fixture handling stays out-of-repo (`/home/roddy/WvW_Analytics/` is the live upload sink; the parser fixtures _directory_ in the repo only holds SIZED-DOWN synthetic blobs).

## Current state (after 2026-07-11 calibration round)

### `libs/gw2_core/src/gw2_core/models.py` (Phase 9 step 1, SHIPPED)
- `BoonApplyEvent` Pydantic subclass with `event_type: Literal["boon_apply"]` + `skill_id` + `duration_ms` + `stacks` + `kind: Literal["apply", "remove_single", "remove_all"] = "apply"`
- `Event` discriminated union extended to 5 members
- 13 round-trip tests in `libs/gw2_core/tests/test_event_union.py`

### `libs/gw2_analytics/src/gw2_analytics/buff_uptime.py` (Phase 9 step 3, SHIPPED via `7cee0b7`)
- `accumulate_buff_events(events, fight_end_ms, fight_start_ms=0) -> dict[int, BuffState]` aggregator
- 8 unit tests in `libs/gw2_analytics/tests/test_buff_uptime.py`

### `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` (Phase 9 step 2-PARTIAL, SHIPPED via `328833d`)
- `_EVENT_STRUCT` exposes byte 52 as `is_buffremove` + byte 53 as `is_ninety`
- 22-tuple unpack target list's slot 6 + slot 7 renamed to mirror arcdps.h
- Damage / heal / strip pipeline reads the right bytes for `is_buffremove` by struct coincidence; the `is_statechange` filter reads the wrong field (`iff`) -- see Calibration findings above

### `libs/gw2_analytics/src/gw2_analytics/buff_dispatch.py` (Phase 9 step 4, SHIPPED via `529cb90`)
- Realigned to arcdps.h `cbtbuffremove`: `0→APPLY, 1→REMOVE_ALL, 2→REMOVE_SINGLE, 3→REMOVE_SINGLE` (the last being CBTB_MANUAL collapse per arcdps "use for in/out volume" guidance)
- 6 tests in `libs/gw2_analytics/tests/test_buff_dispatch.py` (5 plan-spec + 1 CBTB_MANUAL)
- Cross-references: BoonApplyEvent kind doc + test_event_union.py docstrings

### `libs/gw2_analytics/src/gw2_analytics/buff_dispatch.py` module docstring (Phase 9 F3, SHIPPED via `e3a401f`)
- Now cites TWO independent sources for the cbtbuffremove enum: arcdps.com `evtc/README.txt` + the MarsEdge community fork
- Calibration caveat blockquote updated with the empirical-fixture-availability note (no longer blocked on no-real-dump-in-CI)

## New scope (this rewrite)

### Steps shipped
1. ✅ Step 1 (`5fefdae`): `BoonApplyEvent` + 5-member Event union round-trip tests
2. ✅ Step 1.5 (`5fefdae` followup): Expanded `test_event_union.py` with `_validate_subclass[T: Event]` PEP 695 helper
3. ✅ Step 2-PARTIAL (`328833d`): Parser struct rename `is_buffremove` + `is_ninety` + 5 hermetic byte-alignment tests
4. ✅ Step 3 (`7cee0b7`): `accumulate_buff_events` aggregator + 8 unit tests
5. ✅ Step 4 (`529cb90`): `decode_buff_change` realignment + 6 unit tests
6. ✅ Step F3 (`e3a401f`): Doc cross-ref to arcdps.com README + MarsEdge fork

### New prerequisite step (NOT YET SHIPPED -- gates Step 2-EMIT-BRANCH)
🚧 **Step 1.5-SYNC** -- fix the parser struct to match arcdps.h byte-for-byte, then RECALIBRATE the damage / heal / strip pipeline against the corrected byte positions. Sub-steps:

1. Update `_EVENT_STRUCT` literal from `"<QQQiiIIHHHbbbbbbbbIIbb"` to `"<QQQiiIIHHHHbbbbbbbbbbbbxxxx"`. The format includes:
   - 4 uint16 (4 × 2 = 8 bytes, offsets 40-47)
   - 12 uint8 (12 bytes, offsets 48-59)
   - 4 padding bytes (`xxxx`, offsets 60-63)
2. Update the unpack tuple to bind all 27 fields: `time_ms, src_agent, dst_agent, value, buff_dmg, overstack_value, skill_id, src_instid, dst_instid, src_master_instid, dst_master_instid, iff, buff, result, is_activation, is_buffremove, is_ninety, is_fifty, is_moving, is_statechange, is_flanking, is_shields, is_offcycle, _pad1, _pad2, _pad3, _pad4`.
3. Replace the existing `if is_statechange != 0: continue` with the corrected `is_statechange` field binding (now reading the right byte 56).
4. Recalibrate the damage pipeline against real `.zevtc` fixtures in `/home/roddy/WvW_Analytics/uploads/`. Specifically:
   - Open the 75 KB smallest fixture + the 12 MB largest fixture
   - Compute damage_total + healing_total + buff_strip_total BEFORE vs AFTER the struct sync, comparing against the prior pipeline
   - Acceptable deviation: ≤ 5 % per target agent (rounding + re-aggregation noise); > 5 % triggers a STOP condition
5. Update `test_parser_byte_alignment.py` to assert the corrected 1:1 struct alignment. Replace the 5 current tests with an expanded suite of ~12 tests covering the field renaming + the missing-field introduction (4 H slots + 12 b slots + 4 pad bytes = 20 fixed slots + 7 already-bound integer fields = 27 total).
6. Re-run the full libs + apps/api suites; ALL must remain green, including:
   - 19 buff_dispatch + event_union tests
   - 301 libs regression
   - 277 apps/api regression (per pre-F3 baseline)

### Steps now gated behind Step 1.5-SYNC

🚧 **Step 2-EMIT-BRANCH** -- parser yields `BoonApplyEvent` records from non-statechange cbtevent records carrying `is_buffremove != 0`. The exact predicate (which flags trigger emit) is not documented in arcdps.h; requires real-arcdps-dump calibration AFTER the struct sync to verify the field meanings. Cannot ship on the current struct.

🚧 **Step 2-INTEGRATION** -- wire `accumulate_buff_events` to the parser's emit branch. Once Step 2-EMIT ships, this is a 5-line change. Same blocking.

🚧 **Step 5** -- per-buff-uptime schema + route + frontend card. Same blocking.

### Step 1.5-SYNC commit-organization (post-thinker-review clarification)

The Step 1.5-SYNC sub-steps MUST ship as a SINGLE atomic commit, not as a series of incremental commits:

1. Forward compatibility check: `git diff --stat` confirms zero in-flight structs that bind differently.
2. Single atomic commit includes: (a) `_EVENT_STRUCT` literal rewrite to `"<QQQiiIIHHHHbbbbbbbbbbbbxxxx"`, (b) the 27-tuple unpack-target binding, (c) the `parse_events()` filter rewire to use the corrected `is_statechange` field, (d) the expanded `test_parser_byte_alignment.py` test suite (~12 tests covering all 27 fields).
3. The empirical 12-fixture calibration (sub-step d above) runs on the SAME branch BEFORE the commit lands, so the commit message can quote the actual damage-pipeline reattribution numbers from the calibration.

Splitting into "struct update" + "test update" + "pipeline rewire" as separate commits WILL break the build — the test suite's strict-arity destructuring will surface `struct.error` immediately on the struct update alone, and the `is_statechange` filter rewiring will surface `AttributeError` on the old tuple index.

### Step 1.5-SYNC done-criteria (post-thinker-review correction)

The original draft of this plan proposed "≤ 5 % deviation per target agent" as the calibration pass criterion. **This criterion is invalid.** The pre-SYNC damage pipeline is empirically biased toward friend targets (the iff bug), so the post-SYNC pipeline will reattribute a MASSIVE volume of damage records -- easily 50-80 % of per-target totals for any enemy-heavy fight. A "≤ 5 % deviation" check would FAIL even on a perfectly-corrected parser.

**Corrected pass criterion** (one of the following, ordered by preference):

1. **EliteInsights reference comparison**: Run the same 12 fixtures through EliteInsights (the canonical arcdps-data analytical tool) and compare against our post-SYNC output. Pass criterion: per-target agent deltas match EliteInsights within 5 %, AND per-bucket target_dps matches within 5 %. EliteInsights is the de facto reference for arcdps data attribution.
2. **Direct arcdps source dump**: arcdps's own GUI logs the canonical damage / heal / strip numbers to a separate file during live play. Replay a known fight with the arcdps GUI active + our parser + compare totals. Pass criterion: per-agent totals match the arcdps GUI logs within 1 %.
3. **Heroic consistency check**: Run the calibration on ALL 12 fixtures and confirm the post-SYNC pipeline produces CONSISTENT damage / heal / strip ratios across fixtures (low fixture-to-fixture variance). Pass criterion: per-fixture ratio (damage/heal, strip/heal) stays within a 10×-bounded band. Weaker than (1) or (2) but useful if neither is available.
4. **Documentation-only fix**: If neither reference is available, ship Step 1.5-SYNC as a doc-only-tracked bugfix. Note the existing pre-SYNC target_dps values are biased, and that future analysis should re-run fights through the post-SYNC parser.

**Realistic recommendation**: Combination of (3) for in-process calibration + (1) if the maintainer has access to EliteInsights binaries. (2) is impractical without a GW2 live-play environment.

### Plan 138 sequencing decision (post-thinker-review clarification)

The original draft deferred the plan 138 ordering question to "should coordinate with plan 138". The clarified decision criterion:

- **If** arcdps has historically changed `sizeof` or byte-placement of the `cbtevent` fields across EVTC file revisions (different build years ship different struct shapes), **then** plan 138 must ship FIRST so the revision-aware dispatch layer can absorb the Step 1.5-SYNC byte alignment without breaking older logs.
- **If** arcdps has kept `cbtevent` bytes 0-63 static for the entire `EVTC.2023+` era, **then** Step 1.5-SYNC can safely ship first; plan 138's plugin layer can land later without coupling risk.

**Empirical check for this decision**: run the 12-fixture calibration across the FULL size range (75 KB to 12 MB). If ALL 12 fixtures parse cleanly under the post-SYNC struct AND produce consistent per-fixture damage/heal/strip ratios (≤ 10× variance), the "static struct" hypothesis holds and Step 1.5-SYNC can ship independently.

If even one fixture fails to parse cleanly under post-SYNC (a `struct.error` or `ValueError` mid-stream), the "revision-aware" hypothesis holds and plan 138 lands FIRST.

### Out of scope (unchanged)
- Skill-database work (Phase 10+; buff names come from `OrmFightSkill` for now)
- Cross-fight buff uptime aggregation (Phase 10+)
- Damage/source attribution by buff (Phase 10)

## Test plan (delta vs prior draft)

### Pre-existing tests preserved (5/5 + 13 + 8 + 6 unchanged)
- `libs/gw2_core/tests/test_event_union.py` -- 13 tests for the 5-member Event union
- `libs/gw2_analytics/tests/test_buff_uptime.py` -- 8 tests for `accumulate_buff_events`
- `libs/gw2_analytics/tests/test_buff_dispatch.py` -- 6 tests for the realigned `decode_buff_change`
- `libs/gw2_evtc_parser/tests/test_parser_byte_alignment.py` -- 5 tests for byte alignment (will be UPDATED in Step 1.5-SYNC)
- `apps/api/tests/test_*` -- unchanged

### NEW tests (Step 1.5-SYNC)
- ~12 expanded struct-alignment tests in `test_parser_byte_alignment.py` covering:
  - Each of the 27 fields binds to its expected byte offset
  - The 4 missing uint16 + 12 single-byte + 4 padding fields now bind correctly
  - Round-trip: synthetic cbtevent record with known field values parses back to expected values across all 27 fields
- `test_parser_emit_buff.py` -- DEFERRED to Step 2-EMIT (uses the corrected struct + real-fixture event signatures)

### NEW tests (Step 2-EMIT)
- Hermetic tests for the emit predicate using synthetic cbtevent records (parsed via the corrected struct)
- Round-trip tests for BoonApplyEvent emission across all 3 `kind` values
- Integration test that hooks `accumulate_buff_events` to the parser's emit branch + a known-boon synthetic cbtevent

## Empirical comparison -- Expected damage pipeline behavior delta

The post-SYNC pipeline will YIELD DIFFERENT damage rolls vs the pre-SYNC pipeline. The expected shifts:

| Metric | Pre-SYNC (`iff` filter) | Post-SYNC (`is_statechange` filter) | Net effect |
|---|---|---|---|
| Damage records kept | Records with friend TARGETS (per arcdps `iff` semantics) -- biased toward friendly fire | Records that are NOT state-change events (the domain-correct filter) | The "friend fire" bias disappears; pure damage events stay |
| Healing records kept | Records where `dst_master_instid` high byte ≈ 0 (read as the "non-damage" path) | Records with `is_nondamage > 0` (the domain-correct filter) | Heals are now correctly classified; pre-SYNC may have included some damage records that happened to have dst_master_instid high byte = 0 |
| Buff-strip records | Same damage records (extra strip from same `is_nondamage` filter) | Records with `buff_dmg > 0` regardless of `is_nondamage` (matches Phase 8 contract) | Cleaner separation |

The full 12-fixture calibration will be run during Step 1.5-SYNC; the comparison will be committed to `plans/026-phase-9-conditions.md` as a sub-section with the actual numbers.

## Stop conditions

Stop and report if:
- The struct sync introduces a regression in the damage pipeline (> 5 % deviation per target agent averaged over the 12 calibration fixtures).
- A real `.zevtc` (after struct sync) produces a cbtevent record with `is_buffremove > 3` (would indicate a future arcdps cbtbuffremove variant; verified via the unknown-byte fallback in `decode_buff_change`).
- The BuffState stack count exceeds 25 (GW2's hard cap on most boons), requiring a separate `stacks_capped_at_25` invariant.
- A skill-id appears in 2+ events with conflicting duration_ms values (the parser change might need a "last-seen wins" tiebreaker).

## Done criteria (cumulative, this plan revision)

- [x] `BoonApplyEvent` round-trips through the Event discriminated union (5fefdae)
- [x] Parser struct exposes `is_buffremove` byte at offset 52 + `is_ninety` at offset 53 (328833d)
- [x] `accumulate_buff_events` builds correct BuffState from arbitrary event streams (7cee0b7)
- [x] `decode_buff_change` realigned to arcdps.h cbtbuffremove (529cb90)
- [x] Doc cross-ref to arcdps.com evtc/README.txt + MarsEdge fork (e3a401f)
- [x] Plan 026 calibration-foundations rewrite documents the struct misalignment + Step 1.5-SYNC prerequisite (404ee4e)
- [ ] **Step 1.5-SYNC**: `_EVENT_STRUCT` matches arcdps.h 1:1; damage / heal / strip pipeline recalibrated; pass criterion = EliteInsights reference comparison (preferred) OR heroic-consistency on 12 fixtures; FULL libs + apps/api suites green
- [ ] **Step 2-EMIT-BRANCH**: Parser `parse_events` surfaces `BoonApplyEvent(kind=...)` records when `is_buffremove > 0` AND struct-locked for byte positions
- [ ] **Step 2-INTEGRATION**: `accumulate_buff_events` wired to parse_events output
- [ ] **`GET /api/v1/fights/{id}/buff-uptime`** returns sorted-by-uptime-pct rows (Step 5)
- [ ] Frontend `BuffUptimeCard` renders the 0-100 % bar chart correctly (Step 5)
- [x] `mypy` and `ruff` pass on all modified files (cumulative through e3a401f)
- [x] `uv run pytest libs/ apps/api/tests/` exits 0 (last verified at 301/1 libs + 277/2 apps/api through e3a401f)

## Maintenance notes

Phase 9 step 1.5-SYNC is now the load-bearing prerequisite for Step 2-EMIT-BRANCH. The damage / heal / strip pipeline is currently filtering on the wrong field by accident; the struct sync corrects this AND opens the path for buff-emit. Truck-factor: any maintainer unfamiliar with the calibration finding can be misled by the pre-SYNC doc-comment claims -- the calibration section above is the truth.

The struct sync is bounded -- it does NOT change public API (no Pydantic model boundary is affected). It DOES change which byte falls on which field name, which means back-end damage / heal / strip rolls WILL shift (the comparison is committed in this plan as "Expected damage pipeline behavior delta" above). Pre-1.5-SYNC rolls in the DB are interpreted as pre-1.5-SYNC results; post-1.5-SYNC rolls are interpreted as post-1.5-SYNC results -- there's no implicit re-aggregation of historical fights.

Plan 138 (revision-aware parser plugins) becomes even more relevant post-1.5-SYNC: if arcdps introduces a future struct variant, plan 138's `rev.py` becomes the dispatch layer for choosing the struct format per arcdps build year. Step 1.5-SYNC should be coordinated with plan 138 to land the SAME struct-decision abstraction.

The 12 real `.zevtc` calibration fixtures stay off-repo for legal reasons (user-uploaded content); the calibration script writes its outputs to `plans/026-phase-9-conditions.md` sub-sections. A future maintainer reproducing the calibration can use the same script + the same fixtures (re-fetched from `/home/roddy/WvW_Analytics/uploads/` after the dev environment rebuild).
