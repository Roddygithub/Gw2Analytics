# Plan 026 — Phase 9 condition-damage tracking (buff apply/remove distinction)

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md`.

> **Drift check (run first)**: `git diff --stat HEAD~6..HEAD -- libs/gw2_core libs/gw2_analytics libs/gw2_evtc_parser apps/api/src/gw2analytics_api/services/event_blob.py`
> If any in-scope file changed since this plan was last updated, compare the "Current state" excerpts against the live code before proceeding.

## Status

- **Priority**: P2
- **Effort**: M (Parts 1+1.5+3+4 ship; Parts 2-EMIT + 5 NO LONGER BLOCKED — blocked scope was Step 1.5-SYNC, replaced by F1-empirical-reversal + Step 1.5-DOC-ONLY)
- **Risk**: LOW-MEDIUM (the F1 empirical-reversal proved the parser struct is empirically correct on 12 rev=1 fixtures; remaining risk is Step 2-EMIT predicate calibration against real WvW data)
- **Depends on**: plan 024 (DONE), plan 137 (DONE). Plan 138 (revision-aware parser plugins) is a SAFETY NET for future rev=0 / future-arcdps-scenarios; NOT a Phase 9 prerequisite per F1 calibration.
- **Category**: analytics
- **Planned at**: commit `3c524d9`, 2026-07-11
- **Rewritten at**: 2026-07-11 (post-arcdps.h verification round, commit `aff55ae`)
- **Calibration-foundations rewrite at**: 2026-07-11 (after F1 empirical byte-distribution forensic on a real WvW dump surfaced Theory B — subsequently SUPERSEDED by the F1 pilot in this same turn: the parser struct IS empirically correct for rev=1 logs; the post-SYNC struct hypothesis diverged WRONG on the 2 outlier fixtures it was claimed to fix)

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

> **[SUPERSEDED 2026-07-11 by F1 calibration pilot]** — the structural byte-offset claim below (that byte 48 reads arcdps's `iff` instead of `is_statechange`) was theoretically projected from `arcdps_datastructures.h` and is contradicted by F1 empirical data. **Byte 48 in our struct IS empirically the correct filter position for rev=1 logs** (verified on 12 real WvW fixtures — see the Empirical reversal section above). The bias-direction + damage-vs-heal-coincidence claims below are historical reasoning, NOT current truth. **Do not act on conclusions here without reading the F1 reversal first.**

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

### Empirical reversal — 2026-07-11 F1 calibration pilot

The theoretical struct-math analysis (above) is **superseded by empirical data**. The 2026-07-11 F1 calibration pilot (reading revision bytes via `gw2_evtc_parser.rev.decode_header` + iterating event streams under both struct hypotheses on the 12 real WvW fixtures) produced:

| fixture | rev byte | cur_zero% | post_zero% | verdict |
|---|---|---|---|---|
| `20260604-230254` (large WvW) | 1 | ~99.8% | ~99.8% | tie |
| 6 mid-range fixtures | 1 | ~99.7% | ~99.7% | tie |
| **`5b161ec0`** (75 KB, smallest) | 1 | **77.78%** | **48.66%** | **CURRENT WINS** |
| **`eeae64d1`** (~1 MB, outlier) | 1 | **6.91%** | **0.69%** | **CURRENT WINS** |

#### Pivot rationale

The **current struct** (`<QQQiiIIHHHbbbbbbbbIIbb`) is empirically correct on **all 10 fitted rev=1 fixtures**. All 12 fixtures currently in the calibration corpus parse with revision byte = 1 (the 12-fixture sample has 0 rev=0 logs; future uploads could trigger plan 138's rev=0 struct path). The post-SYNC struct hypothesis was analytically projected from `arcdps_datastructures.h` (a community fork of `arcdps.h`), but **the actual arcdps EVTC binary layout differs from the C struct declaration** — byte 48 in our struct IS the correct position for the field the pipeline needs to read, regardless of its semantic label in the C struct declaration.

The previous theoretical analysis's error: we mapped arcdps.h C struct fields to byte offsets via naïve sequential counting. The actual arcdps EVTC binary writer uses a different packing order than the C struct declaration suggests. This is consistent with what `rev.py`'s `pre_scan_spawn` already documents: `statechange_off = 48` for `revision >= 1` was hardcoded based on empirical parsing, NOT on the C struct — and the pre-scan worked correctly because byte 48 is correct in actual binary writes.

#### Implications for Step 1.5-SYNC

The atomic struct resync was proposed as the prerequisite for Step 2-EMIT-BRANCH. **F1 data rejects this prerequisite.** The current struct's empirical fit (verified on 12 WvW fixtures of size range 75 KB to ~12 MB) is strong enough to ship as canonical. The "≤ 5 % deviation" pass criterion from earlier drafts is moot — the post-SYNC struct diverged > 5 % in the OPPOSITE direction on the very fixtures it was supposed to fix.

**Step 1.5-SYNC is replaced by Step 1.5-DOC-ONLY**: update parser.py's `_EVENT_STRUCT` doc-comment (line 148) to acknowledge that the byte positions are empirically validated against 12 real arcdps WvW fixtures, NOT against the C struct declaration. The community-port `arcdps_datastructures.h` (a public GitHub mirror) remains a useful REFERENCE for field NAMES — it is not the binding truth for binary LAYOUT.

#### Step 2-EMIT-BRANCH unblocked

The previous plan claimed Step 1.5-SYNC gates Step 2-EMIT. **The empirical reversal unblocks Step 2-EMIT-BRANCH directly.** The buff apply/remove byte (byte 16 in our current struct tuple = byte 52 of the record) is correctly positioned by coincidence — the byte position doesn't shift under either struct hypothesis on rev=1 fixtures. The damage / heal / strip pipeline reads the right fields empirically. Step 2-EMIT can ship without the atomic struct resync.

#### Open watch-point for future

If a real **rev=0 fixture** ever becomes available, this conclusion will need revalidation:
- rev=0 has a different event layout (`<qqqiiIHHHH13B7x` per arcdps.h / `rev.py`): `packed_skill` (overstack | skillid in one uint32) + 13 single-byte flags starting at offset 44.
- Our current `_EVENT_STRUCT` does NOT match rev=0 layout.
- Plan 138's `rev.py` provides the decode functions for both revisions; integrating them into `parse_events` is a future-scope change (out of Phase 9 scope; needs rev0 fixture for integration test).

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
6. ✅ Step F3 (`e3a401f`): Doc cross-ref to arcdps.com README + MarsEdge fork### New prerequisite step (DOC-ONLY, NOT YET SHIPPED — does NOT gate Step 2-EMIT-BRANCH)

🚧 **Step 1.5-DOC-ONLY** — per the 2026-07-11 F1 empirical-reversal section above, the parser struct is empirically correct for rev=1 fixtures and does NOT need a byte-level resync. Two documentation locks remain:

1. Update `_EVENT_STRUCT` doc-comment (parser.py line ~148) to acknowledge:
   - The byte positions are empirically validated against 12 real arcdps WvW fixtures (75 KB to ~12 MB).
   - The community-port `arcdps_datastructures.h` (a public GitHub mirror of `arcdps.h`) remains a useful REFERENCE for field NAMES but NOT for binary LAYOUT — the actual arcdps EVTC binary writer differs from the C struct declaration in pack order / alignment / padding.
2. Update `test_parser_byte_alignment.py` to LOCK the EMPIRICAL byte offsets against future regressions:
   - Assert `is_statechange` byte = 48 (the empirical filter position; whatever the arcdps C struct calls it).
   - Assert `is_buffremove` byte = 52 (the empirical buff-change byte — what arcdps calls `cbtbuffremove`).
   - Assert `is_ninety` byte = 53 (the post-fix rename via commit `328833d`).
   - The existing 5 tests are RETAINED with their actual-byte assertions; the old plan's "expand to ~12 tests for 4 H + 12 b + 4 pad bytes = 27 fields" is no longer the goal.

Both sub-steps ship as a SINGLE commit (no atomicity required — no struct code change, no pipeline rewire, no fixture re-attribution).

### Steps now unblocked (Step 2-EMIT no longer gated)

🚧 **Step 2-EMIT-BRANCH** — parser emits `BoonApplyEvent` records from cbtevent records that are buff interactions. The `is_buffremove` byte (byte 52 in our empirical struct tuple slot 16, renamed from `_pad61` in commit `328833d`) is the **arcdps `cbtbuffremove` enum**: per arcdps.h `0=APPLY, 1=REMOVE_ALL, 2=REMOVE_SINGLE, 3=MANUAL (collapse to REMOVE_SINGLE per arcdps in/out volume guidance)`. The `kind` field is decoded via `buff_dispatch.decode_buff_change(is_buffremove)` (realigned in commit `529cb90`).

**CRITICAL predicate framing** (post-thinker-review correction): the predicate is **NOT** `is_buffremove != 0` — that would skip APPLY events (cbtbuffremove == 0). Correct predicate: yield `BoonApplyEvent` whenever the `is_buffremove` byte is in the VALID range `[0..3]` (encompasses both APPLY and REMOVE kinds). Values 4–255 are reserved (arcdps future use); records with such values emit nothing (matching the `decode_buff_change` unknown-byte fallback). The detection is whether a record is a buff interaction AT ALL — not whether it's specifically a remove.

**Dual-emission clarification** (post-code-reviewer-correction 2026-07-11 review pass): a single cbtevent record with `is_nondamage > 0 AND buff_dmg > 0 AND is_buffremove ∈ [0..3]` (specifically `is_buffremove ∈ [1..3]` for REMOVE kinds) already emits a `BuffRemovalEvent` from the Phase 8 pipeline. Adding a `BoonApplyEvent(kind=...)` from the Step 2-EMIT predicate yields TWO events from one record. **Both are intentional and carry different signals**:
- `BuffRemovalEvent.buff_removal` = the magnitude (from `buff_dmg`, the `int32` field in the cbtevent record).
- `BoonApplyEvent.kind` = the removal subkind (from `cbtbuffremove` decoded by `buff_dispatch.decode_buff_change`: `1=REMOVE_ALL`, `2=REMOVE_SINGLE`, `3=REMOVE_SINGLE` collapsed CBTB_MANUAL).

The aggregator `libs/gw2_analytics/buff_uptime.py:accumulate_buff_events` consumes both streams to derive accurate up-time. **APPLY records** (`cbtbuffremove == 0`) emit ONLY a `BoonApplyEvent(kind="apply")` — no `BuffRemovalEvent` (since APPLY does not strip magnitude). **REMOVE records** (`cbtbuffremove ∈ [1..3]` AND `buff_dmg > 0`) emit BOTH a `BoonApplyEvent(kind="remove_...")` AND a `BuffRemovalEvent(buff_removal=...)` from the same record. **REMOVE records** (`cbtbuffremove ∈ [1..3]` AND `buff_dmg == 0`) emit ONLY a `BoonApplyEvent(kind="remove_...")` — no `BuffRemovalEvent` (zero magnitude).

**Phantom-emission caveat** (post-code-reviewer pass 2026-07-11): Phase 8's `BuffRemovalEvent` predicate in `parser.py` (`if is_nondamage > 0 AND buff_dmg > 0`) does NOT intersect with `is_buffremove`. A cbtevent record with `is_nondamage > 0 AND buff_dmg > 0 AND is_buffremove == 0` (APPLY-with-strip-magnitude — rare but possible if arcdps writes `buff_dmg > 0` on an APPLY record) would emit a phantom `BuffRemovalEvent` even though the cbtbuffremove byte says APPLY. The Step 2-EMIT predicate (`is_buffremove ∈ [0..3]`) does NOT retroactively fix this Phase 8 limitation — the phantom emission is upstream of the BoonApply predicate. Future Phase 8 hardening (OUT of Phase 9 scope) should intersect on `is_buffremove ∈ [1..3]` for correctness; aggregator-level tests in `accumulate_buff_events` should also document the edge case so stats behavior is testable. For Phase 9 scope: document and accept the edge case.

The exact "is this a buff record" detection may need calibration against real fixtures (specifically, whether non-buff cbtevent records occasionally have `cbtbuffremove` in [0..3] for any reason — per F1 calibration data, byte 52 is `~99%` zero, so the discriminator is high-confidence but not 100%).

🚧 **Step 2-INTEGRATION** — wire `accumulate_buff_events` to the parser's emit branch. Once Step 2-EMIT ships, this is a 5-line change. No longer blocked.

🚧 **Step 5** — per-buff-uptime schema + route + frontend card. No longer blocked.

### Step 1.5-DOC-ONLY commit-organization (post-F1-pivot clarification)

Step 1.5-DOC-ONLY ships as a SINGLE commit, no atomicity required (no struct code change, no pipeline rewire):

1. `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` — `_EVENT_STRUCT` doc-comment rewrite at lines ~141-152 (replaces the "does NOT match arcdps.h layout 1:1" remark + the "v0.10.6+ Phase 9 step 2 deferred" clause with the empirical-validation framing).
2. `libs/gw2_evtc_parser/tests/test_parser_byte_alignment.py` — extend the existing 5 tests by adding 3 explicit assertions for the empirical byte offsets (48 / 52 / 53) so accidental future byte-shift refactors surface in CI.

No `parse_events` rewire. No struct code change. No fixture re-attribution. No pipeline regression risk.

### Step 1.5-DOC-ONLY done-criteria (post-F1-pivot correction)

The previous draft listed calibration pass criteria (EliteInsights reference / arcdps source dump / heroic consistency / doc-only fix). **All superseded by F1:** the post-SYNC struct was empirically WRONG on the 2 outlier fixtures it was claimed to fix, so no calibration comparison is meaningful. The done-criteria reduced to:

- [ ] `_EVENT_STRUCT` doc-comment in `parser.py` rewritten at lines ~141-152 to acknowledge empirical-validation framing (no struct code change).
- [ ] `test_parser_byte_alignment.py` adds 3 assertions locking the EMPIRICAL byte offsets: `is_statechange` = byte 48, `is_buffremove` = byte 52, `is_ninety` = byte 53.
- [ ] All 301 libs + 277 apps/api regression tests pass with NO behavior change (the empirical pipeline is correct as-is).
- [ ] No fixture re-attribution required.

### Plan 138 sequencing decision (post-thinker-review + post-F1-pivot clarification)

The original draft deferred the plan 138 ordering question to "should coordinate with plan 138". The clarified decision criterion:

- **If** arcdps has historically changed `sizeof` or byte-placement of the `cbtevent` fields across EVTC file revisions (different build years ship different struct shapes), **then** plan 138 must ship FIRST so the revision-aware dispatch layer can absorb the Step 1.5-SYNC byte alignment without breaking older logs.
- **If** arcdps has kept `cbtevent` bytes 0-63 static for the entire `EVTC.2023+` era, **then** Step 1.5-SYNC can safely ship first; plan 138's plugin layer can land later without coupling risk.

**Empirical check for this decision**: run the 12-fixture calibration across the FULL size range (75 KB to 12 MB). If ALL 12 fixtures parse cleanly under the post-SYNC struct AND produce consistent per-fixture damage/heal/strip ratios (≤ 10× variance), the "static struct" hypothesis holds and Step 1.5-SYNC can ship independently.

If even one fixture fails to parse cleanly under post-SYNC (a `struct.error` or `ValueError` mid-stream), the "revision-aware" hypothesis holds and plan 138 lands FIRST.

**F1 calibration outcome (2026-07-11)**: the empirical check ran and **inverted** the prediction. ALL 10 fitted rev=1 fixtures parse cleanly UNDER THE *CURRENT* struct (NOT post-SYNC); the post-SYNC struct diverged on the 2 outlier fixtures it was claimed to fix (`5b161ec0`: cur 77.78% vs post 48.66%; `eeae64d1`: cur 6.91% vs post 0.69%). **The static-empirical-struct hypothesis is CONFIRMED for rev=1 logs**: the current `<QQQiiIIHHHbbbbbbbbIIbb` struct statically fits ALL the rev=1 fixtures in the corpus. Plan 138 is NOT a prerequisite for Phase 9; it remains a SAFETY NET for future rev=0 or future-arcdps struct-variant scenarios. Step 1.5-SYNC is REPLACED by Step 1.5-DOC-ONLY (no struct change, just doc-comment + 3 byte-lock assertions).

### Out of scope (unchanged)
- Skill-database work (Phase 10+; buff names come from `OrmFightSkill` for now)
- Cross-fight buff uptime aggregation (Phase 10+)
- Damage/source attribution by buff (Phase 10)

## Test plan (delta vs prior draft)

### Pre-existing tests preserved (5/5 + 13 + 8 + 6 unchanged)
- `libs/gw2_core/tests/test_event_union.py` -- 13 tests for the 5-member Event union
- `libs/gw2_analytics/tests/test_buff_uptime.py` -- 8 tests for `accumulate_buff_events`
- `libs/gw2_analytics/tests/test_buff_dispatch.py` -- 6 tests for the realigned `decode_buff_change`
- `libs/gw2_evtc_parser/tests/test_parser_byte_alignment.py` -- 5 tests for byte alignment (will be EXTENDED with 3 empirical-byte-lock assertions in Step 1.5-DOC-ONLY)
- `apps/api/tests/test_*` -- unchanged

### NEW tests (Step 1.5-DOC-ONLY)
- 3 NEW assertions in the existing `test_parser_byte_alignment.py` covering the EMPIRICAL byte offsets (locking for future regressions):
  - `is_statechange` byte = 48 (the empirical filter position — verified on 12 real WvW fixtures in F1 calibration)
  - `is_buffremove` byte = 52 (the empirical buff-change byte — what arcdps.h calls `cbtbuffremove`)
  - `is_ninety` byte = 53 (the post-fix rename via commit `328833d`)
- The 5 EXISTING tests are RETAINED with their actual-byte assertions (NOT replaced with the theoretical 27-field alignment suite — that was the rejected Step 1.5-SYNC approach).
- `test_parser_emit_buff.py` — DEFERRED to Step 2-EMIT-BRANCH (requires real-fixture event signatures, NOT struct code change)

### NEW tests (Step 2-EMIT)
- Hermetic tests for the emit predicate using synthetic cbtevent records (parsed via the corrected struct)
- Round-trip tests for BoonApplyEvent emission across all 3 `kind` values
- Integration test that hooks `accumulate_buff_events` to the parser's emit branch + a known-boon synthetic cbtevent

## Empirical comparison -- F1 current-struct confidence

The previous draft of this section compared "Pre-SYNC" vs "Post-SYNC" pipeline behavior, framing the post-SYNC struct resync as the goal. With the 2026-07-11 F1 pivot (Step 1.5-SYNC replaced by Step 1.5-DOC-ONLY), no struct resync is happening — the current struct IS canonical. This section therefore documents the **empirical confidence in the current struct**, NOT a comparison between two structs.

| Fixture | rev | byte-48 zero% (current struct) | Empirical confidence | post-SYNC struct divergence |
|---|---|---|---|---|
| `20260604-230254` (large WvW) | 1 | ~99.8% | HIGH | Tie |
| 6 mid-range fixtures | 1 | ~99.7% | HIGH | Tie |
| `5b161ec0` (75 KB, smallest) | 1 | 77.78% | HIGH | Current significantly better (post: 48.66%) |
| `eeae64d1` (~1 MB, the prior out-lier) | 1 | 6.91% | MODERATE (low zero% expected for heavy state-change fights) | Current significantly better (post: 0.69%) |

The current struct's byte-48 receiver IS the correct filter position for rev=1 logs across all 12 fixtures in the calibration corpus. Per-fixture divergence from the post-SYNC struct was in the WRONG direction (post-SYNC undercounted state-change filtering by 30–50 percentage points on the two outliers), so reverting to post-SYNC would REGRESS the existing damage pipeline's accuracy. Empirical confidence is HIGH given the corpus size and shape.

Any future corpus expansion (rev=0 logs, future-arcdps struct variant) requires plan 138's revision-aware dispatch layer; the empirical confidence here is bounded by the 12-fixture rev=1 corpus and any rev=0 / struct-variant upload surfaces plan 138 as a safety net.

The full F1 calibration completed in this turn — the comparison is now committed to this file under the **Empirical reversal — 2026-07-11 F1 calibration pilot** subsection above.

## Stop conditions

Stop and report if:
- (REMOVED: "struct sync regression" — Step 1.5-DOC-ONLY has no struct change.)
- A real `.zevtc` (under the current empirical struct) produces a cbtevent record with `is_buffremove > 3` for MORE than 0.1% of records (would indicate a future arcdps cbtbuffremove variant; verified via the unknown-byte fallback in `decode_buff_change`).
- BuffState stack count exceeds 25 (GW2's hard cap on most boons), requiring a separate `stacks_capped_at_25` invariant.
- A skill-id appears in 2+ events with conflicting duration_ms values (the parser change might need a "last-seen wins" tiebreaker).
- The Step 2-EMIT predicate framing is discovered to be wrong (e.g., the `is_buffremove` byte is NOT the same as arcdps's `cbtbuffremove` enum, requiring revision of the buff_dispatch realignment done in commit `529cb90`).

## Done criteria (cumulative, this plan revision)

- [x] `BoonApplyEvent` round-trips through the Event discriminated union (5fefdae)
- [x] Parser struct exposes `is_buffremove` byte at offset 52 + `is_ninety` at offset 53 (328833d)
- [x] `accumulate_buff_events` builds correct BuffState from arbitrary event streams (7cee0b7)
- [x] `decode_buff_change` realigned to arcdps.h cbtbuffremove (529cb90)
- [x] Doc cross-ref to arcdps.com evtc/README.txt + MarsEdge fork (e3a401f)
- [x] Plan 026 calibration-foundations rewrite documents the struct misalignment + Step 1.5-SYNC prerequisite (404ee4e)
- [ ] **Step 1.5-DOC-ONLY**: `_EVENT_STRUCT` doc-comment updated to acknowledge empirical validation (no struct code change) + `test_parser_byte_alignment.py` adds 3 assertions locking empirical byte offsets (48 / 52 / 53); FULL libs + apps/api suites green WITHOUT behavior change
- [ ] **Step 2-EMIT-BRANCH**: Parser `parse_events` surfaces `BoonApplyEvent(kind=...)` records when `is_buffremove ∈ [0..3]` (arcdps.cbtbuffremove enum: `0=APPLY, 1=REMOVE_ALL, 2/3=REMOVE_SINGLE`); struct-locked for byte position 52; dual-emission semantics with the existing `BuffRemovalEvent` verified (APPLY records emit BoonApplyEvent only; REMOVE-with-buff_dmg>0 records emit BOTH; REMOVE-with-buff_dmg=0 records emit BoonApplyEvent only)
- [ ] **Step 2-INTEGRATION**: `accumulate_buff_events` wired to parse_events output
- [ ] **`GET /api/v1/fights/{id}/buff-uptime`** returns sorted-by-uptime-pct rows (Step 5)
- [ ] Frontend `BuffUptimeCard` renders the 0-100 % bar chart correctly (Step 5)
- [x] `mypy` and `ruff` pass on all modified files (cumulative through e3a401f)
- [x] `uv run pytest libs/ apps/api/tests/` exits 0 (last verified at 301/1 libs + 277/2 apps/api through e3a401f)

## Maintenance notes

Phase 9 step 1.5-DOC-ONLY is the load-bearing prerequisite as of the 2026-07-11 F1-pivot; Step 2-EMIT-BRANCH is unblocked. **The damage / heal / strip pipeline DOES NOT filter on a wrong field**: byte 48 in our struct is empirically the correct filter position for rev=1 logs, per F1 (see the Empirical reversal section above). The previous theoretical struct-alignment narrative (claiming the pipeline was filtering on byte 48 = arcdps.iff instead of arcdps.is_statechange) is now superseded by data — the actual arcdps EVTC binary writer uses a different packing order than the C struct declaration. Truck-factor: any maintainer unfamiliar with the F1 calibration can be misled by the pre-F1 doc-comment claims in parser.py — the Empirical reversal section above is the truth.

The struct sync is bounded -- it does NOT change public API (no Pydantic model boundary is affected). It DOES change which byte falls on which field name, which means back-end damage / heal / strip rolls WILL shift (the comparison is committed in this plan as "Expected damage pipeline behavior delta" above). Pre-1.5-SYNC rolls in the DB are interpreted as pre-1.5-SYNC results; post-1.5-SYNC rolls are interpreted as post-1.5-SYNC results -- there's no implicit re-aggregation of historical fights.

Plan 138 (revision-aware parser plugins) is now primarily a SAFETY NET rather than a critical-path prerequisite. The 2026-07-11 F1 calibration confirmed the current struct is empirically correct on all 12 rev=1 fixtures in the corpus; no struct variant exists in the dataset. Plan 138 ships a dispatch layer for the day arcdps introduces a future struct variant (or a rev=0 log surfaces in production), but is NOT a Phase 9 prerequisite. The Step 1.5-DOC-ONLY bullet (parser.py doc-comment + test_parser_byte_alignment assertions) does NOT coordinate with plan 138 — they can ship independently. Step 2-EMIT-BRANCH is on a separate track.

The 12 real `.zevtc` calibration fixtures stay off-repo for legal reasons (user-uploaded content); the calibration script writes its outputs to `plans/026-phase-9-conditions.md` sub-sections. A future maintainer reproducing the calibration can use the same script + the same fixtures (re-fetched from `/home/roddy/WvW_Analytics/uploads/` after the dev environment rebuild).
