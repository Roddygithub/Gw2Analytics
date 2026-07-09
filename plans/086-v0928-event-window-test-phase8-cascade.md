# Plan 086 — v0.9.28 — `libs/gw2_analytics/tests/test_event_window.py` Phase 8 `BuffRemovalEvent` test cascade (after Plan 083 adds the field)

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Addressed finding (MED test reliability):** Plan 083 (v0.9.27) adds `buff_removal_total: int = Field(default=0, ge=0)` to `EventBucket` + the `elif isinstance(e, BuffRemovalEvent)` branch in `EventWindowAggregator.aggregate()` + the `total_strip` invariant in `_check_invariants`. But the existing test file `libs/gw2_analytics/tests/test_event_window.py` is **frozen at Phase 7** — it only tests `DamageEvent` + `HealingEvent`, no `BuffRemovalEvent`, no `buff_removal_total` assertion. After plan 083 adds the Phase 8 source-code path, the tests pass verbatim (because the default `=0` makes pre-Phase-8 fixtures still validate). But the tests do NOT exercise the new code path → a future regression (e.g., a `ruff` rename of `e.buff_removal` to `e.strip_magnitude` in the source) would NOT be caught by the test suite, because no test triggers the strip accumulator branch.

This is the same diagnostic class as plan 083 (the source-code cascade gap), but on the test side. Pre-Phase-8 test coverage + new Phase-8 source code = silent regression risk on the strip accumulator's contribution to the per-bucket chart.

Plan 086 fixes the test-side Phase 8 cascade gap. The tests are added to the existing `test_event_window.py` file (which has 7 tests today; 6 new tests added for Phase 8).

## File changes

### 1 file edited + 0 NEW modules

**`libs/gw2_analytics/tests/test_event_window.py`** — current 7-test file. Add the test factory `_strip(time_ms, buff_removal)` near the existing `_damage` + `_healing` factories (the planned changes mirror the parallel `_strip` factory in `test_per_fight_timeline.py:20-30`). Add 6 new tests covering the Phase 8 cascade:

| # | Test | Asserts |
|---|---|---|
| 8 | `BuffRemovalEvent` alone yields 1 bucket with `damage_total=0`, `healing_total=0`, `buff_removal_total=300`, `event_count=1` | The Phase 8 source-code path (`elif isinstance(e, BuffRemovalEvent):`) fires |
| 9 | DPS-only fixture (1 damage event) yields `buff_removal_total=0` (the default-zero invariant) | The `default=0` in `EventBucket.buff_removal_total = Field(default=0, ge=0)` keeps pre-Phase-8 fixtures compatible |
| 10 | Mixed kinds in 1 bucket (1 damage + 1 healing + 1 strip) yields `damage_total=damage`, `healing_total=healing`, `buff_removal_total=300`, `event_count=3` | The 3-event same-bucket Phase 8 case |
| 11 | 2 strip events at distinct `time_ms` across 2 buckets yield correct per-bucket strip totals + the invariant sum-preservation across buckets (sum-of-buckets.buff_removal_total == sum-of-events.buff_removal) | The multi-bucket Phase 8 accumulation + the `_check_invariants` strip invariant |
| 12 | Dual emit (1 buff_removal event with `value=800` + 1 strip event from parser's dual-emit path) yields `buff_removal_total=300` not 800 (the damage does NOT bleed into strip) | The dual-emit strip accounting is precise |
| 13 | `EventBucket.model_fields["buff_removal_total"].default == 0` AND `.annotation is int` AND `.metadata` contains a `MinLen`/`MaxLen`-NOT-present constraint | The Pydantic field default + annotation + constraint introspection after Plan 083 |

### NEW `libs/gw2_analytics/tests/test_event_window_phase8_cascade.py` — alternative structure

Alternative (NOT used by this plan): split into a NEW test file. The split is NOT done because the 6 new tests fit naturally into the existing test class `TestEventWindowAggregator`'s Phase 6+v1+Phase 8 contract matrix; a NEW file would lose the visual continuity of the contract matrix (the existing `_damage` + `_healing` factories would need to be duplicated to the NEW file).

## Considered and rejected

- **Alternative: split into a new test file `test_event_window_phase8_cascade.py`** — duplicates the `_damage` + `_healing` factories; loses the test-matrix visual continuity. The 6 tests fit naturally into the existing `TestEventWindowAggregator` class.
- **Alternative: inherit the existing tests' factory pattern + add 6 new tests in `test_event_window.py`** — this IS the plan. The 6 new tests follow the same `class TestEventWindowAggregator` parent + use the `_damage`/`_healing`/`_strip` factory trio. Future tests can extend the matrix.
- **Alternative: add a single "Phase 8 smoke test" that exercises all 3 kinds** — 1 test is weaker than 6 discrete tests; the per-bucket accumulator + the multi-bucket invariants + the dual-emit path are SEPARATE concerns that should each have a test.
- **Alternative: mark the entire existing test file as deprecated + create v2** — the existing tests are NOT deprecated (they continue to validate the Phase 6 + v1 contracts); the new tests are added alongside.
- **Alternative: update tests in `test_per_fight_timeline.py` instead** — `per_fight_timeline.py` already has its own Phase 8 tests (`_strip` factory added in the v0.8.9 cycle). The 6 new tests are specifically for `event_window.py` which is the v0.6.0 module that did NOT get Phase 8 expansion.

## Effort

`S` — 1 file edit (add 1 factory `_strip` + 6 test methods to the existing `TestEventWindowAggregator` class) + 0 NEW test files (extending the existing one is cleaner than splitting). All additive; the 7 existing tests remain unchanged. Independent of plans 087 + 088.
