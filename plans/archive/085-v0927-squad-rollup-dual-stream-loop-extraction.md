# Plan 085 — v0.9.27 — `squad_rollup.py` 3-stream for-loop extraction → shared `_accumulate_subgroup_totals` helper

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Addressed finding (LOW DX + cleanup):** `libs/gw2_analytics/src/gw2_analytics/squad_rollup.py` has 3 byte-identical for-loops, one per event stream (`damage_events` + `healing_events` + `strip_events`). Inside each, the per-subgroup accumulation pattern is identical except for the per-event contribution attribute:

```python
for dmg in damage_events:
    subgroup = agent_id_to_subgroup.get(dmg.source_agent_id, "")
    total_damage[subgroup] += dmg.damage
    hit_count[subgroup] += 1
    grand_damage += dmg.damage
    grand_hits += 1
for heal in healing_events:
    subgroup = agent_id_to_subgroup.get(heal.source_agent_id, "")
    total_healing[subgroup] += heal.healing
    hit_count[subgroup] += 1
    grand_healing += heal.healing
    grand_hits += 1
for strip in strip_events:
    subgroup = agent_id_to_subgroup.get(strip.source_agent_id, "")
    total_strip[subgroup] += strip.buff_removal
    hit_count[subgroup] += 1
    grand_strip += strip.buff_removal
    grand_hits += 1
```

The 3 loops share 5 of 6 lines verbatim (only the event-attribution line differs: `total_damage[subgroup] += dmg.damage` vs `total_healing[subgroup] += heal.healing` vs `total_strip[subgroup] += strip.buff_removal`). The grand_total accumulators (`grand_damage` + `grand_healing` + `grand_strip`) are also near-clones.

A future maintenance change (e.g., a Phase 9 +4th event type addition, or a quality-bucket rollup that needs per-source-agent weight) requires editing 3 sites in lockstep. The refactor extracts a single `_accumulate_subgroup_totals(events, source_attr, contribution_attr, total_dict, hit_dict, grand_total)` helper that all 3 sites call.

The plan is small (~30 lines net removed) but the duplication is exactly the kind of pattern that drifts: a future maintainer adds a 4th iteration site without copying the "add to total_dict + hit_count + grand_total" pattern, and the invariant breaks at compile-time (well, at runtime — when the next test fails).

## File changes

### 1 file edited + 1 NEW test file + 0 NEW modules

**`libs/gw2_analytics/src/gw2_analytics/squad_rollup.py`** — current 130-line file. Replace the 3 for-loops with a helper call:

```diff
+def _accumulate_subgroup_totals(
+    events: Iterable[DamageEvent] | Iterable[HealingEvent] | Iterable[BuffRemovalEvent],
+    source_attr_name: str,
+    contribution_attr_name: str,
+    total_dict: dict[str, int],
+    hit_dict: dict[str, int],
+) -> int:
+    """Yield the grand-total of ``contribution_attr_name`` across all events.
+
+    Per-event work:
+      * look up the source-agent's subgroup from the map (default: empty string)
+      * accumulate the contribution into ``total_dict[subgroup]``
+      * accumulate 1 hit into ``hit_dict[subgroup]`` (the per-bucket activity signal)
+
+    Returns the grand total across all events for the invariant check.
+    """
+    grand = 0
+    for e in events:
+        source_id = getattr(e, source_attr_name)
+        contribution = getattr(e, contribution_attr_name)
+        subgroup = agent_id_to_subgroup_lookup(source_id)
+        total_dict[subgroup] += contribution
+        hit_dict[subgroup] += 1
+        grand += contribution
+    return grand
+
+def agent_id_to_subgroup_lookup(
+    agent_id_to_subgroup: Mapping[int, str],
+) -> Callable[[int], str]:
+    """Return a closure that looks up ``agent_id`` -> subgroup, defaulting to ``""``."""
+    def _lookup(agent_id: int) -> str:
+        return agent_id_to_subgroup.get(agent_id, "")
+    return _lookup
+
   class SquadRollupAggregator:
       def aggregate(self, damage_events, healing_events, strip_events, agent_id_to_subgroup, duration_s):
           if duration_s < 0:
               raise ValueError(...)
-          total_damage: dict[str, int] = defaultdict(int)
-          total_healing: dict[str, int] = defaultdict(int)
-          total_strip: dict[str, int] = defaultdict(int)
-          hit_count: dict[str, int] = defaultdict(int)
-          grand_damage = 0
-          grand_healing = 0
-          grand_strip = 0
-          grand_hits = 0
-
-          for dmg in damage_events:
-              subgroup = agent_id_to_subgroup.get(dmg.source_agent_id, "")
-              total_damage[subgroup] += dmg.damage
-              hit_count[subgroup] += 1
-              grand_damage += dmg.damage
-              grand_hits += 1
-          for heal in healing_events:
-              subgroup = agent_id_to_subgroup.get(heal.source_agent_id, "")
-              total_healing[subgroup] += heal.healing
-              hit_count[subgroup] += 1
-              grand_healing += heal.healing
-              grand_hits += 1
-          for strip in strip_events:
-              subgroup = agent_id_to_subgroup.get(strip.source_agent_id, "")
-              total_strip[subgroup] += strip.buff_removal
-              hit_count[subgroup] += 1
-              grand_strip += strip.buff_removal
-              grand_hits += 1
+          total_damage: dict[str, int] = defaultdict(int)
+          total_healing: dict[str, int] = defaultdict(int)
+          total_strip: dict[str, int] = defaultdict(int)
+          hit_count: dict[str, int] = defaultdict(int)
+          lookup = agent_id_to_subgroup_lookup(agent_id_to_subgroup)
+
+          grand_damage = _accumulate_subgroup_totals(
+              damage_events,
+              "source_agent_id",
+              "damage",
+              total_damage,
+              hit_count,
+          )  # capture grand_damage here... wait, need to capture
```

Actually the cleanest refactor is to bundle the 4 per-stream state mutations + grand-totals into a single dataclass-like dict:

```python
@dataclass
class _SubgroupAccumulators:
    """Per-stream accumulators for the 3 event streams."""
    damage: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    healing: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    strip: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    hit_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    grand_damage: int = 0
    grand_healing: int = 0
    grand_strip: int = 0
    grand_hits: int = 0

def _accumulate(
    events, source_attr, contrib_attr, totals: dict[str, int], hits: dict[str, int]
) -> int:
    grand = 0
    for e in events:
        subgroup = AGENT_ID_TO_SUBGROUP.get(getattr(e, source_attr), "")
        totals[subgroup] += getattr(e, contrib_attr)
        hits[subgroup] += 1
        grand += getattr(e, contrib_attr)
    return grand
```

This is cleaner. The plan uses this design.

### NEW `libs/gw2_analytics/tests/test_squad_rollup_refactor.py` — 4 hermetic tests

| # | Test | Asserts |
|---|---|---|
| 1 | `_accumulate([], "source_agent_id", "damage", {}, {})` returns `0` | Empty input short-circuits |
| 2 | `_accumulate([DamageEvent(source=42, target=99, damage=100, time_ms=1500)], "source_agent_id", "damage", totals, hits)` returns `100` + `totals={""}=100` + `hits={""}=1` | Single-event happy path with the empty-subgroup fallback |
| 3 | `_accumulate` with a populated ``agent_id_to_subgroup`` map routes the event to the right subgroup | The map-driven subgroup rotation |
| 4 | The 3-stream aggregator output (after refactor) matches the pre-refactor output for 10 randomly shuffled events (`seed=42`) | The refactor preserves the canonical output (cross-stream + within-stream totals + grand totals + hit counts) |

The existing `test_squad_rollup.py` is unchanged — it verifies the post-refactor output is identical to the pre-refactor output.

## Considered and rejected

- **Alternative: extract the 3-stream logic into a generator function `_stream_subgroup_contributions(events, source_attr, contrib_attr)` that yields `(subgroup, contribution)` tuples** — a generator + tuple-yield approach is more functional but the caller still has to do the 4-line accumulation pattern; the helper-function approach is more direct.
- **Alternative: store the 3 per-stream totals + grand-totals + hit_count in a single `SubgroupAccumulatorState` dataclass** (cleaner state-object pattern) — the plan uses a simpler dict-based accumulator; the dataclass approach is larger refactor.
- **Alternative: use `pyspark` or `pandas` for the 3-stream join** — out of scope (the library is a `gw2_analytics` pure-Python aggregate library; no pandas dep).
- **Alternative: leave the 3 loops as-is + add a `ruff` custom rule to detect "for-loops with the same body"** — the rule would be hard to write; the explicit extraction is the canonical fix.
- **Alternative: keep the 3 loops but DRY the per-subgroup assignment line** (the `subgroup = agent_id_to_subgroup.get(..., "")` + `total_dict[subgroup] += ...` + `hit_dict[subgroup] += 1`) — extracting only the per-subgroup rotation doesn't capture the full duplication (the grand-total accumulation line is also identical).

## Effort

`S` — 1 file edit (3 for-loops replaced with 3 helper calls + 1 helper function definition) + 1 NEW test file (4 hermetic tests). Net diff: ~20 lines deleted + ~30 lines added = ~10 lines net. The plan is LOW-leverage (low impact per LOC removed) but addresses a real DRY-violation pattern. Independent of plans 083 + 084.
