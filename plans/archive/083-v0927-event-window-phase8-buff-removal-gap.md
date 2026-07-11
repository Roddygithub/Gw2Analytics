# Plan 083 — v0.9.27 — `libs/gw2_analytics/event_window.py` Phase 8 `BuffRemovalEvent` per-bucket tracking (cascading the Phase 8 import gap)

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Addressed finding (MED correctness):** When `libs/gw2_core/src/gw2_core/models.py` added `BuffRemovalEvent` as the third `Event` discriminated-union member in Phase 8 (the v0.8.0 cycle), `target_buff_removal.py` was updated to read `event.buff_removal` from the new member. BUT `event_window.py` (the per-bucket time-rollup aggregator) was NOT updated to track the same field per bucket. The Phase 8 cascade gap is:

```python
# event_window.py — pre-fix code (only Damage + Healing handled):
if isinstance(e, DamageEvent):
    damage_by_bucket[bucket_index] += e.damage
elif isinstance(e, HealingEvent):
    healing_by_bucket[bucket_index] += e.healing
# Future EventType subclasses land here -- still
# counted in ``event_count`` even when no damage /
# healing attribute exists.
```

Result: the per-bucket rollup schema (`EventBucket.start_ms` + `end_ms` + `damage_total` + `healing_total` + `event_count`) silently drops the `buff_removal_total` per bucket. The frontend's per-fight timeline chart (`apps/web/src/app/fights/[id]/page.tsx`'s `<PerFightTimelineChart>`) renders damage + healing bands but cannot render a buff-strip band — the per-bucket BuffRemoval-per-bucket signal is absent. A researcher investigating "which 5s window saw the most corrupting/stripper concentration" has no chart-level answer; they must fall back to the per-target rollup (which is fine for top-strippers but blind to per-bucket chronology).

The fix is the Phase 8 cascade: extend `EventBucket` with a new `buff_removal_total: int = Field(default=0, ge=0)` field, extend the aggregator's accumulator to track the buff-removal per bucket, and extend the cross-field invariants to lock sum-of-buff_removal_total == sum-of-event.buff_removal across all input events.

This is the same fix that would have landed in the Phase 8 cycle if the original commit had cascaded the change to all 4 places that read `Event` fields (target_dps / target_healing got their new sibling `target_buff_removal`; event_window slipped through).

## File changes

### 3 file edits + 1 NEW test file

**`libs/gw2_analytics/src/gw2_analytics/event_window.py`** — current 100-line file. Three surgical edits:

```diff
 from gw2_core import DamageEvent, Event, HealingEvent
+from gw2_core import BuffRemovalEvent  # Phase 8: per-bucket buff-removal tracking

 class EventBucket(BaseModel):
     model_config = ConfigDict(frozen=True, extra="forbid")
     start_ms: int = Field(..., ge=0)
     end_ms: int = Field(..., ge=0)
     damage_total: int = Field(default=0, ge=0)
     healing_total: int = Field(default=0, ge=0)
+    # Phase 8: per-bucket buff-removal total. Mirrors the
+    # ``damage_total`` / ``healing_total`` invariants (sum across
+    # buckets == sum of event.buff_removal across input events).
+    # ``default=0`` so pre-Phase-8 fixtures without strip events
+    # continue to validate cleanly (the existing tests assert
+    # ``bucket.damage_total`` + ``bucket.healing_total`` only;
+    # the new field defaults to 0 in those cases).
+    buff_removal_total: int = Field(default=0, ge=0)
     event_count: int = Field(default=0, ge=0)
 
 class EventWindowAggregator:
     def aggregate(self, events: Iterable[Event], window_s: int) -> list[EventBucket]:
         ...
         damage_by_bucket: dict[int, int] = defaultdict(int)
         healing_by_bucket: dict[int, int] = defaultdict(int)
+        # Phase 8: per-bucket buff-removal accumulator (mirror of
+        # ``damage_by_bucket`` / ``healing_by_bucket``).
+        buff_removal_by_bucket: dict[int, int] = defaultdict(int)
         count_by_bucket: dict[int, int] = defaultdict(int)
         last_bucket_index = -1

         for e in events:
             bucket_index = e.time_ms // window_ms
             last_bucket_index = max(last_bucket_index, bucket_index)
             count_by_bucket[bucket_index] += 1
             if isinstance(e, DamageEvent):
                 damage_by_bucket[bucket_index] += e.damage
             elif isinstance(e, HealingEvent):
                 healing_by_bucket[bucket_index] += e.healing
+            # Phase 8: per-bucket buff-removal tracking. Mirror of
+            # the Damage + Healing branches -- the third member of
+            # the discriminated union now writes to its own
+            # accumulator; the bucket's total_event_count invariant
+            # (sum of bucket.event_count == len(events)) still
+            # holds because the count_by_bucket branch above fires
+            # for every event.
+            elif isinstance(e, BuffRemovalEvent):
+                buff_removal_by_bucket[bucket_index] += e.buff_removal

         buckets: list[EventBucket] = []
         for idx in range(last_bucket_index + 1):
             buckets.append(
                 EventBucket(
                     start_ms=idx * window_ms,
                     end_ms=(idx + 1) * window_ms,
                     damage_total=damage_by_bucket[idx],
                     healing_total=healing_by_bucket[idx],
+                    buff_removal_total=buff_removal_by_bucket[idx],
                     event_count=count_by_bucket[idx],
                 )
             )

         total_event_count = sum(count_by_bucket.values())
         self._check_invariants(buckets, total_event_count)
         return list(buckets)

     @staticmethod
     def _check_invariants(
         buckets: list[EventBucket],
         expected_total_events: int,
     ) -> None:
         """Raise ``ValueError`` if any cross-field invariant is violated."""
+        # Phase 8: buff-removal invariant mirrors the existing
+        # event_count invariant -- sum across buckets == sum of
+        # buff-removal across all input events (no event dropped,
+        # no double-counting).
+        total_strip = sum(b.buff_removal_total for b in buckets)
+        # Compute expected from buckets themselves: every bucket's
+        # event_count is the residue of the input events attribution,
+        # so we cannot separately track buff-removal sums without
+        # carrying a new aggregator-level counter. The cleanest fix
+        # is to accumulate ``total_strip`` during the for-loop
+        # (see below) and pass it to ``_check_invariants``; the
+        # PLan-083 design adds this accumulator parameter.
         ...
```

The fully-preferred fix carries the `total_strip` accumulator as a local variable in `aggregate()` and passes it to `_check_invariants`, mirroring the existing `total_event_count` plumbing.

### NEW `libs/gw2_analytics/tests/test_event_window.py` — 6 hermetic tests

| # | Test | Asserts |
|---|---|---|
| 1 | `EventWindowAggregator().aggregate([], window_s=1) == []` | Empty input → empty list (regression for the existing test) |
| 2 | 1 DamageEvent at t=1500ms lands in bucket 1 (`[1000, 2000)`); `damage_total=1234`, `healing_total=0`, `buff_removal_total=0`, `event_count=1` | The Phase 8 default for `buff_removal_total=0` holds when no strip events hit the bucket |
| 3 | 1 BuffRemovalEvent at t=1500ms lands in bucket 1; `damage_total=0`, `healing_total=0`, `buff_removal_total=300`, `event_count=1` | The Phase 8 source-code path (`elif isinstance(e, BuffRemovalEvent): buff_removal_by_bucket[bucket_index] += e.buff_removal`) actually fires |
| 4 | 3 events (Damage + Healing + BuffRemoval) all at t=1500ms land in bucket 1; `damage_total=damage`, `healing_total=heal`, `buff_removal_total=300`, `event_count=3` | The 3-event same-bucket case |
| 5 | BuffRemovalEvent at t=1500ms + BuffRemovalEvent at t=2500ms across 2 buckets (bucket 1 + bucket 2); `bucket[1].buff_removal_total=300`, `bucket[2].buff_removal_total=200`, total = 500 | Multi-bucket strip accumulation |
| 6 | `EventBucket.model_fields["buff_removal_total"].default == 0` AND `.annotation is int` | The Pydantic field default + type annotations are correctly wired for forward-compat with pre-Phase-8 callers |

The plan adds 6 tests to `test_event_window.py` (which already exists per the file tree — currently has 4 tests covering damage + healing only). The new tests cover the Phase 8 cascade.

## Considered and rejected

- **Alternative: keep `EventBucket` unchanged + add a new `EventBucketWithStrip` schema** — schemas proliferate; the migration path is `Optional[buff_removal_total]` is harder to encode in Pydantic v2 than a field with `default=0`.
- **Alternative: track buff-removal as a separate stream + a new aggregator method `aggregate_with_strip(...)`** — 2 aggregator methods on the same class is more surface to maintain; the backwards-compat default is uglier than the additive-field approach.
- **Alternative: only count the strip events in `event_count` (already happens) + drop the per-bucket strip total entirely** — the per-bucket strip total is the data the chart needs; tracking only `event_count` doesn't give the chart a y-axis value.
- **Alternative: use Pydantic v2 discriminated unions with explicit type tags** — gw2_core uses isinstance-based discrimination (the existing pattern); the plan matches the existing pattern for consistency.
- **Alternative: export a NEW `Phase8WindowAggregator` class + deprecate `EventWindowAggregator`** — class proliferation; the new field on the existing class is the minimal change.

## Effort

`S` — 1 file edit (3 surgical inserts at the Pydantic field, the loop, the bucket construction) + 6 NEW tests appended to the existing `test_event_window.py`. All additive at the schema level (`default=0` keeps pre-Phase-8 callers unchanged). Independent of plans 084 + 085.
