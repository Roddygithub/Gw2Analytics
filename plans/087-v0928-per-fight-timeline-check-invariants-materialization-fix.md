# Plan 087 — v0.9.28 — `libs/gw2_analytics/per_fight_timeline.py::_check_invariants` materialization → expected-totals parameter (streaming-friendly)

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Addressed finding (LOW perf + memory):** `per_fight_timeline.py::PerFightTimelineAggregator._check_invariants` takes the `events: Iterable[Event]` parameter and materialises it via `list(events)`:

```python
@staticmethod
def _check_invariants(
    rows: list[PerFightTimelineRow],
    events: Iterable[Event],
) -> None:
    """..."""
    events_list = list(events)
    expected_damage = sum(e.damage for e in events_list if isinstance(e, DamageEvent))
    expected_healing = sum(e.healing for e in events_list if isinstance(e, HealingEvent))
    expected_strip = sum(e.buff_removal for e in events_list if isinstance(e, BuffRemovalEvent))
    ...
```

This is wasteful for streaming callers — the canonical apps/api aggregator chain feeds the events through `parse_events` (one-pass). After `aggregate()` already drained the stream once to build the per-bucket rows, `_check_invariants` materialises it a SECOND TIME to do the sum-preservation invariant check.

For a canonical WvW raid event blob (~100k+ events), this means 2x materialisation: the events are decoded once, walked for buckets, walked again for invariants. The `expected_damage` + `expected_healing` + `expected_strip` totals can be computed inline in the `aggregate()` loop (single pass) and passed to `_check_invariants` as 3 ints directly. The fix is small (~5 lines saved in `_check_invariants`, ~10 lines added in `aggregate()` for 3 running totals) but it makes the streaming caller 1-pass instead of 2-pass for the invariant check.

The dual-emit events (`HealingEvent` + `BuffRemovalEvent` from the same cbtevent record) would have their magnitudes counted in BOTH `expected_healing` AND `expected_strip` — same as the inline accumulator — so the invariant holds.

## File changes

### 1 file edited + 1 NEW test file

**`libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py`** — current 130-line file. 4 surgical edits:

```diff
 class PerFightTimelineAggregator:
     def aggregate(self, events, agents=(), duration_s=0.0, *, window_s=5):
         if window_s < _MIN_WINDOW_S:
             raise ValueError(...)
+        # Plan 087: streaming-friendly invariant plumbing. The 3
+        # running totals are computed inline (single-pass) and
+        # passed to `_check_invariants` as ints. Replaces the
+        # prior `_check_invariants(rows, events)` materialisation
+        # pattern that drained the stream a SECOND time.
+        expected_damage = 0
+        expected_healing = 0
+        expected_strip = 0
         ...
         for e in events:
             bucket_index = e.time_ms // window_ms
             last_bucket_index = max(last_bucket_index, bucket_index)
             if isinstance(e, DamageEvent):
                 damage_by_bucket[bucket_index] += e.damage
+                expected_damage += e.damage
             elif isinstance(e, HealingEvent):
                 healing_by_bucket[bucket_index] += e.healing
+                expected_healing += e.healing
             elif isinstance(e, BuffRemovalEvent):
                 strip_by_bucket[bucket_index] += e.buff_removal
+                expected_strip += e.buff_removal

         rows = []
         for idx in range(last_bucket_index + 1):
             rows.append(PerFightTimelineRow(...))

-        self._check_invariants(rows, events)
+        self._check_invariants(rows, expected_damage, expected_healing, expected_strip)
         return list(rows)

     @staticmethod
-    def _check_invariants(
-        rows: list[PerFightTimelineRow],
-        events: Iterable[Event],
-    ) -> None:
-        """..."""
-        events_list = list(events)
-        expected_damage = sum(e.damage for e in events_list if isinstance(e, DamageEvent))
-        expected_healing = sum(e.healing for e in events_list if isinstance(e, HealingEvent))
-        expected_strip = sum(e.buff_removal for e in events_list if isinstance(e, BuffRemovalEvent))
+    def _check_invariants(
+        rows: list[PerFightTimelineRow],
+        expected_damage: int,
+        expected_healing: int,
+        expected_strip: int,
+    ) -> None:
+        """..."""
         actual_damage = sum(r.total_damage for r in rows)
-        ...
```

### NEW `libs/gw2_analytics/tests/test_per_fight_timeline_invariants_refactor.py` — 4 hermetic tests

| # | Test | Asserts |
|---|---|---|
| 1 | `PerFightTimelineAggregator().aggregate([empty], window_s=1)` returns `[]` AND `_check_invariants([], 0, 0, 0)` does NOT raise | Empty input + expected=0 invariants pass |
| 2 | 1 damage event at t=1500 → 1 bucket + `_check_invariants([bucket], 1234, 0, 0)` does NOT raise | The damage-only happy path |
| 3 | Mixed fixture (damage + healing + strip, single bucket) → `_check_invariants([bucket], DAMAGE, HEALING, STRIP)` does NOT raise with the post-aggregate totals | The 3-kind same-bucket Path |
| 4 | `_check_invariants` with mismatched totals raises `ValueError` (e.g., damage_total summed does NOT match expected_damage) | The invariant failure path (post-refactor still fires) |

The existing 7 tests in `test_per_fight_timeline.py` are unchanged — they verify the post-refactor output is identical to the pre-refactor output (regression contract).

## Considered and rejected

- **Alternative: leave `_check_invariants` materializing + add a single-pass invariant method `_check_invariants_streaming(rows, events)`** — 2 invariants methods on the same class is more surface to maintain; the inlined approach is the minimum.
- **Alternative: pass a callback `expected_sum_fn: Callable[[Iterable[Event]], tuple[int, int, int]]`** — the callable can drain the stream once, but the canonical caller drains the stream once anyway (inside `aggregate()`). Passing the 3 ints directly is simpler.
- **Alternative: skip the invariant check entirely** (rely on type-checking) — the sum-preservation invariants are the canonical tests for "did the aggregator drop / double-count any events"; removing them would regress test quality.
- **Alternative: use `functools.reduce` for the per-bucket accumulator** — the canonical per-bucket accumulator IS a `defaultdict(int)` + a per-iteration accumulator; the `functools.reduce` approach is less idiomatic.
- **Alternative: inline `_check_invariants` body into `aggregate`** (no separate method) — loses the static-method API for the type checker; the static-method approach is canonical.

## Effort

`S` — 1 file edit (4 surgical patches in `aggregate()` + 1 patch in `_check_invariants`) + 1 NEW test file (4 hermetic tests). Net code change: ~0 lines (replace 2-line `events_list = list(events)` block with 3-int parameter plumbing). The performance win is real for streaming callers (1x materialisation instead of 2x). Independent of plans 086 + 088.
