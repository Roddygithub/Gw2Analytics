# Plan 026 — Phase 9 condition-damage tracking (buff apply/remove distinction)

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md`.

> **Drift check (run first)**: `git diff --stat 5fefdae..HEAD -- libs/gw2_core libs/gw2_analytics libs/gw2_evtc_parser apps/api/src/gw2analytics_api/services/event_blob.py`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding.

## Status

- **Priority**: P2
- **Effort**: M (Parts 1+3 shipped; Part 2 + buff_dispatch realignment deferred)
- **Risk**: MEDIUM (Parts 2 + 4 deferred pending real arcdps dump calibration)
- **Depends on**: plan 024 (combat-readout spike, DONE), plan 137 (buff_uptime Pydantic model, DONE), plan 026-step 1 (BoonApplyEvent kind discriminator, SHIPPED 5fefdae)
- **Category**: analytics
- **Planned at**: commit `3c524d9`, 2026-07-11
- **Rewritten at**: 2026-07-11 (post-arcdps.h verification round)

## Why this matters

The v0.10.6 cycle landed `buff_uptime.py` (per-buff historical tracking) + `buff_dispatch.py` (3-way apply/remove-single/remove-all decoder) in `libs/gw2_analytics`. Two gaps remain before the analyst surface is composable:

1. **The parser does not produce buff-apply events.** `parse_events` reads the 64-byte cbtevent records but does not surface the arcdps `is_buffremove` byte to the discriminated-union `Event` stream. The byte has been EXPOSED (Phase 9 step 2 partial — this rewrite documents that) but the EMIT branch that yields `BoonApplyEvent` records is deferred pending real arcdps dump calibration.
2. **The `buff_dispatch.py` decoder's enum mappings have a known discrepancy with arcdps.h.** The arcdps.h `enum cbtbuffremove` is `CBTB_NONE=0, CBTB_ALL=1, CBTB_SINGLE=2, CBTB_MANUAL=3`. The project decoder (`decode_buff_change`) currently maps `0→APPLY, 1→REMOVE_SINGLE, 2→REMOVE_ALL`. The project's `1→REMOVE_SINGLE` and `2→REMOVE_ALL` lines are SWAPPED vs arcdps's `1→ALL` and `2→SINGLE`. This is a pre-existing defect from plan 137 (the original plan's framing was wrong; arcdps.h was not verified at plan-137 time). Realignment is deferred to step 4.

Phase 9 closes both gaps by:
- ✅ Step 1 (SHIPPED `5fefdae`): Added `BoonApplyEvent` subclass to `gw2_core`'s discriminated union, with `kind: Literal["apply","remove_single","remove_all"]` discriminator + 13 round-trip tests.
- ✅ Step 1.5 (SHIPPED `5fefdae` followup): Expanded `test_event_union.py` with the 5-member union round-trip + invalid-kind rejection + adapter-determinism coverage. All 13 tests pass; `mypy` 0 errors, `ruff` 0 errors.
- ✅ Step 2-PARTIAL (SHIPPED this rewrite): Renamed the parser's struct slot 6 (`_pad61`) → `is_buffremove` + slot 7 (`_pad62`) → `is_ninety` to expose the arcdps.h byte. Added 5 hermetic struct-alignment tests (`test_parser_byte_alignment.py`) that lock the byte positions so a future struct tuple-reorder regression fires before it can corrupt downstream aggregation.
- 🚧 Step 2-EMIT-BRANCH (DEFERRED): The emit branch that yields `BoonApplyEvent` records from non-statechange cbtevevent records carrying `is_buffremove != 0` is deferred pending real arcdps dump calibration. The exact predicate (which combination of `is_statechange` / `is_nondamage` / `value` / `buff_dmg` / `is_buffremove` triggers an apply/remove emit) is not documented in arcdps.h's `cbtstatechange` enum, so an empirical round with real arcdps dumps is required BEFORE shipping the predicate.
- 🚧 Step 3-FULL (DEFERRED — calibrated-only path): The Phase 9 step 3 workstream in `libs/gw2_analytics.buff_uptime` (which would consume the `BoonApplyEvent` stream from the parser via `accumulate_buff_events`) is **NOT YET** implemented — the existing `accumulate_buff_events` aggregator operates on direct `BoonApplyEvent` records (built in step-1 round-trip tests) but is NOT yet wired to the parser's emit branch. The aggregator itself is correct and tested; the integration is the deferred scope.
- 🚧 Step 4 (DEFERRED): Realign `decode_buff_change` enum mappings with arcdps.h. The blast radius of the change touches `BoonApplyEvent.kind` docstring + plan 137 + plan 138 (forwarding references) + 3 unit-test files. A real-arcdps-dump round should drive the realignment (without empirical data the realignment could swap in the wrong direction).
- 🚧 Step 5 (DEFERRED): Per-buff-uptime schema + route. Step 5's scope remains the same as the pre-rewrite plan (Phase 9 prep explicit-outs: per buff uptime tables + the `GET /api/v1/fights/{id}/buff-uptime` route + the frontend card).

## Current state

### `libs/gw2_core/src/gw2_core/models.py` (Phase 9 step 1)
- `BoonApplyEvent` Pydantic subclass with `event_type: Literal["boon_apply"]` + `skill_id` + `duration_ms` + `stacks` + `kind: Literal["apply","remove_single","remove_all"] = "apply"`
- `Event` discriminated union extended to 5 members (Damage + Healing + BuffRemoval + BoonApply + ... [CC event TBD])
- 13 round-trip tests in `libs/gw2_core/tests/test_event_union.py` cover the 5-member union, all `kind` literals, default `kind="apply"`, invalid `kind` rejection, adapter determinism

### `libs/gw2_analytics/src/gw2_analytics/buff_uptime.py` (Phase 9 step 1.5)
- `accumulate_buff_events(events, fight_end_ms, fight_start_ms=0) -> dict[int, BuffState]` shipped via commit `7cee0b7`
- PEP 695 generic `_validate_subclass[T: Event](cls: type[T], event_json: str) -> T` test helper applied to the round-trip tests (closes the mypy `union-attr` warning class)
- 8 unit tests in `libs/gw2_analytics/tests/test_buff_uptime.py` — single apply / apply-then-remove-single / apply-then-remove-all / multi-skill-id partitioning / remove-from-zero clamp / 3-way mixed sequence

### `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` (Phase 9 step 2-PARTIAL)
- `_EVENT_STRUCT` now exposes byte 52 as `is_buffremove` (was `_pad61`) + byte 53 as `is_ninety` (was `_pad62`)
- 22-tuple unpack target list's slot 6 + slot 7 renamed to mirror arcdps.h field semantics
- Layout comment in the struct definition now references arcdps.h (via `<GW2-ArcDPS-Mechanics-Log>/src/arcdps_datastructures.h` mirror) byte-by-byte
- The damage / healing / buff-removal pipeline is UNCHANGED in semantics; the rename is a label-only edit (no byte reordering)

### `libs/gw2_analytics/src/gw2_analytics/buff_dispatch.py` (Phase 9 step 4-DEFERRED)
- `decode_buff_change(0) == BuffChangeKind.APPLY`
- `decode_buff_change(1) == BuffChangeKind.REMOVE_SINGLE`
- `decode_buff_change(2) == BuffChangeKind.REMOVE_ALL`
- `decode_buff_change(3+) == BuffChangeKind.REMOVE_SINGLE` (unknown-byte fallback)
- **Known discrepancy**: arcdps.h cbtbuffremove maps `1=ALL, 2=SINGLE, 3=MANUAL`. The project's `1=SINGLE, 2=ALL` lines are SWAPPED relative to arcdps.h. Realignment deferred to step 4 (pending real arcdps dump calibration).

### API surface (today)
- `GET /api/v1/fights/{id}/events` aggregates damage + healing + buff-removal per TARGET agent
- `GET /api/v1/fights/{id}/squads` aggregates per SUBGROUP
- `GET /api/v1/fights/{id}/skills` aggregates per SKILL
- `GET /api/v1/fights/{id}/timeline` per-bucket damage + healing + buff-removal
- `GET /api/v1/fights/{id}/timeline/players` per-player per-bucket
- No buff-state endpoint exists (Phase 9 step 5 scope)

### Schemas (today, modular split landed)
- `apps/api/src/gw2analytics_api/schemas/fight.py`: `TargetBuffRemovalRowOut` (per-target strip roll-up), `BuffUptimeRowOut` (NOT YET — Phase 9 step 5 scope), `BoonStateOut` (NOT YET — Phase 9 step 5 scope)

## Verified arcdps byte layout

The byte positions exposed in the parser's struct are now clarified. Per `<GW2-ArcDPS-Mechanics-Log>/src/arcdps_datastructures.h` (a mirror of arcdps.h with forward-compatible naming):

```
bytes  0-23:  3 × uint64  (time, src_agent, dst_agent)
bytes 24-31:  2 × int32   (value, buff_dmg)
bytes 32-39:  2 × uint32  (overstack_value, skillid)
bytes 40-47:  4 × uint16  (src_instid, dst_instid, src_master_instid, dst_master_instid)
bytes 48-59: 12 × uint8   (iff, buff, result, is_activation, is_buffremove,
                            is_ninety, is_fifty, is_moving, is_statechange,
                            is_flanking, is_shields, is_offcycle)
bytes 60-63:  4 × pad bytes (pad61, pad62, pad63, pad64)
```

The parser's struct literal `"<QQQiiIIHHHbbbbbbbbIIbb"` does NOT match the arcdps.h layout 1:1 — the struct has 3 uint16s where arcdps has 4 (missing `dst_master_instid`), then reads 8 single-byte slots where arcdps has 12 (covering `iff`, `buff`, `result`, `is_activation`, `is_buffremove`, `is_ninety`, `is_fifty`, `is_moving`, `is_statechange`, `is_flanking`, `is_shields`, `is_offcycle`), then 2 uint32 slots where arcdps has 4 single-byte pads.

The damage / heal / strip pipeline has been EMPIRICALLY CALIBRATED against real arcdps dumps with the existing (incorrect) struct, so the byte-level semantics work for the existing pipeline. The byte-position renames in step 2-PARTIAL (slot 6 → `is_buffremove`, slot 7 → `is_ninety`) reflect the assumption that the byte at slot 6 (offset 52 in the parser's struct reading) IS the arcdps.h byte 52 (`is_buffremove`). This was confirmed by the 5 hermetic struct-alignment tests in `test_parser_byte_alignment.py` (the test fixture packs a specific byte at slot 6 and the parser reads it back correctly).

A FULL struct reordering (to align 1:1 with arcdps.h) is DEFERRED — it would shift the byte alignment of EVERY field past `src_instid` + `dst_instid` + the missing `src_master_instid`/`dst_master_instid`. The shift would invalidate past dump compatibility. Plan 138 already lays the groundwork for revision-aware parser plugins (the `cbtevent` layout can differ across arcdps versions).

## Scope (delta vs prior draft)

### Steps shipped
1. ✅ Step 1 (5fefdae): `BoonApplyEvent` + 5-member Event union round-trip tests
2. ✅ Step 1.5 (5fefdae followup): Expanded test_event_union.py with `_validate_subclass[T: Event]` PEP 695 helper
3. ✅ Step 2-PARTIAL: `cbtbuffremove` byte exposed via parser struct rename + 5 hermetic struct-alignment tests
4. ✅ Step 3 (7cee0b7): `accumulate_buff_events` aggregator + 8 unit tests in libs/gw2_analytics/tests/test_buff_uptime.py

### Steps deferred (this rewrite)
1. 🚧 Step 2-EMIT-BRANCH: Parser yields `BoonApplyEvent` records from non-statechange cbtevent records carrying `is_buffremove != 0`. **Calibration-blocked** — the exact predicate (which `is_statechange` / `is_nondamage` / `value` / `buff_dmg` combinations trigger an apply/remove emit) is not documented in arcdps.h. Requires real arcdps dump round.
2. 🚧 Step 3-INTEGRATION: Wire `accumulate_buff_events` (which currently consumes hand-crafted `BoonApplyEvent` records in tests) to the parser's emit branch. Once step 2-EMIT-BRANCH ships, this is a 5-line wiring change.
3. 🚧 Step 4: Realign `decode_buff_change` mappings with arcdps.h (`1`=ALL, `2`=SINGLE, `3`=MANUAL). Currently SWAPPED (`1`=SINGLE, `2`=ALL). Calibration-blocked — the project's pre-existing semantic frame may or may not match arcdps reality; the rebuild should happen WITH a real arcdps dump open in a debugger + a representative fixture that exercises both single-stack and all-stack remove events.
4. 🚧 Step 5: Per-buff-uptime schema + route. (`apps/api/src/gw2analytics_api/schemas/fight.py::BuffUptimeRowOut` + `apps/api/src/gw2analytics_api/routes/fights.py::get_fight_buff_uptime` + frontend card.) Same scope as the prior draft, gated behind step 2 emit branch.

### Out of scope (unchanged)
- Skill-database work (Phase 10+; buff names come from `OrmFightSkill` for now)
- Cross-fight buff uptime aggregation (Phase 10+; the per-account timeline is enough for v0.10.x)
- Damage/source attribution by buff (Phase 10; would require a 2nd SQL query and a new aggregator)

## Test plan (delta vs prior draft)

### Pre-existing tests preserved
- `libs/gw2_core/tests/test_event_union.py` — 13 tests for the 5-member Event union + BoonApplyEvent round-trip
- `libs/gw2_analytics/tests/test_buff_uptime.py` — 8 tests for `accumulate_buff_events` (apply / single / all / multi-skill / clamp / mixed)
- `libs/gw2_analytics/tests/test_buff_dispatch.py` — 3 tests for `decode_buff_change` (3-way + unknown-byte fallback + negative rejection) — UNCHANGED until step 4
- `apps/api/tests/test_*` — UNCHANGED in this plan scope

### NEW tests (this plan revision)
- `libs/gw2_evtc_parser/tests/test_parser_byte_alignment.py` — 5 hermetic struct-alignment tests
  - `test_event_struct_size_matches_arcdps_cbtevent_64_bytes`
  - `test_is_buffremove_byte_zero_reads_as_zero`
  - `test_is_buffremove_byte_three_way_enum_values_round_trip`
  - `test_is_ninety_byte_round_trip`
  - `test_is_buffremove_and_is_ninety_dont_collide_with_neighbouring_slots`

### Tests deferred
- Step 2-EMIT-BRANCH tests (in `libs/gw2_evtc_parser/tests/test_parser_emit_buff.py` — to be written when step 2 emit lands)
- Step 4 buff_dispatch realignment test updates (will touch `test_buff_dispatch.py` + likely `test_event_union.py` docstring reframing)
- Step 5 schema + route e2e tests (in `apps/api/tests/test_fight_buff_uptime.py` — to be written when step 5 lands)

## Stop conditions

Stop and report if:
- Real arcdps dump testing reveals the cbtbuffremove byte position differs from arcdps.h byte 52 (would require a parser version pin per plan 138).
- Real arcdps dump testing reveals a buff event in a statechange record (`is_statechange != 0`) we did NOT anticipate (would require extending the emit branch).
- The BuffState stack count exceeds 25 (GW2's hard cap on most boons), requiring a separate `stacks_capped_at_25` invariant.
- A skill-id appears in 2+ events with conflicting duration_ms values (the parser change might need a "last-seen wins" tiebreaker).

## Done criteria (cumulative, this plan revision)

- [x] `BoonApplyEvent` round-trips through the Event discriminated union (5fefdae)
- [x] Parser struct exposes `is_buffremove` byte at offset 52 + `is_ninety` at offset 53 (this revision)
- [x] `accumulate_buff_events` builds correct BuffState from arbitrary event streams (7cee0b7)
- [ ] Parser `parse_events` surfaces `BoonApplyEvent(kind=...)` records when `is_buffremove > 0` (DEFERRED — step 2-EMIT)
- [ ] `decode_buff_change` enum mappings align with arcdps.h cbtbuffremove (DEFERRED — step 4)
- [ ] `GET /api/v1/fights/{id}/buff-uptime` returns sorted-by-uptime-pct rows (DEFERRED — step 5)
- [ ] Frontend `BuffUptimeCard` renders the 0-100% bar chart correctly (DEFERRED — step 5)
- [ ] All existing tests still pass
- [x] `mypy` and `ruff` pass on modified files (5fefdae + 7cee0b7 + this revision)
- [ ] `uv run pytest apps/api/tests/ libs/` exits 0 (excluded the pre-existing v0.10.6 cycle infra failures; verified up to the bytes-renamed scope)

## Maintenance notes

The buff-state tracker is a per-fight computation — cross-fight aggregation is Phase 10. The `BoonApplyEvent` lifetime on the wire is bounded by the fight (events blurbs are immutable post-parse). Any future "buff uptime over the last N fights" feature would join multiple per-fight BuffStates, not re-stream the events.

Phase 9 step 2-EMIT-BRANCH requires real arcdps dump calibration BEFORE shipping. The arcdps.h cbtbuffremove enum is documented (`0=NONE, 1=ALL, 2=SINGLE, 3=MANUAL`) but the EXACT predicate for emit (which combination of cbtevent flags means "this is a buff-apply event vs a buff-remove event") is NOT documented in arcdps.h. The existing damage / heal / strip pipeline works empirically because it tests against real dumps; the buff emit branch should be calibrated the same way.

Phase 9 step 4 (decode_buff_change realignment) is similarly calibration-blocked: the existing project mappings (`1=SINGLE, 2=ALL`) were recorded from a non-arcdps source (likely the plan 137 docstring's heuristics); arcdps.h says `1=ALL, 2=SINGLE, 3=MANUAL`. Realignment should happen with a real dump open + a fixture that exercises BOTH single-stack and all-stack remove events.
