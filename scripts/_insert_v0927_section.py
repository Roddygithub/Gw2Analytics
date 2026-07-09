#!/usr/bin/env python3
"""One-shot helper: insert the v0.9.27 section into plans/README.md.

Usage:
    python3 scripts/_insert_v0927_section.py

Idempotent: re-running finds the new section and refuses to re-insert.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README_PATH = ROOT / "plans" / "README.md"

NEW_SECTION = """## v0.9.27 audit (current)

**Author:** senior-advisor audit (improve skill, standard effort) — libs/gw2_analytics sibling-aggregators deep pass (the 9 sibling modules under the orchestrator aggregate.py had only limited coverage: v0.9.6 touched event_window.py only as part of a broader libs+web deep-pass; v0.9.17 covered aggregate.py orchestrator + the 3 __init__.py public surfaces but did NOT separately audit the 8 per-target/per-squad/per-skill/per-timeline siblings; the Phase 8 BuffRemovalEvent addition to gw2_core did not cascade to event_window.py per-bucket accumulator, and the 3 per-target siblings are byte-for-byte near-clones that drift independently)
**Stamped at:** 44ea862 (origin/main HEAD at audit time — after the v0.9.26 apps/api/tests/* + apps/api/README.md pass landed: 3 plans 080/081/082 written + indexed)
**Recon scope:** libs/gw2_analytics/src/gw2_analytics/multi_fight.py + target_dps.py + event_window.py + target_healing.py + target_buff_removal.py + squad_rollup.py (skill_usage.py + player_profile.py + per_fight_timeline.py covered by v0.9.6 deep-pass scope; not re-audited here)
**Audit mode:** standard effort; targeted deep pass on the 6 sibling modules; 3 findings selected for planning (1 MED correctness + 1 MED DX/perf + 1 LOW DX/cleanup)

### v0.9.27 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 083 | [083-v0927-event-window-phase8-buff-removal-gap](./083-v0927-event-window-phase8-buff-removal-gap.md) | **pending** (3 surgical edits in libs/gw2_analytics/src/gw2_analytics/event_window.py: (a) EventBucket gains new buff_removal_total: int = Field(default=0, ge=0); (b) the aggregate() for-loop gains an `elif isinstance(e, BuffRemovalEvent): buff_removal_by_bucket[bucket_index] += e.buff_removal` branch + a buff_removal_by_bucket accumulator; (c) _check_invariants gains a total_strip sum check. default=0 keeps pre-Phase-8 fixtures compatible. 6 NEW hermetic tests appended to libs/gw2_analytics/tests/test_event_window.py cover: empty-input short-circuit + Damage-only path + BuffRemoval-only path + mixed-kinds same-bucket + multi-bucket strip accumulation + Pydantic field default+annotation introspection) | #1 libs/gw2_analytics/src/gw2_analytics/event_window.py was NOT updated when Phase 8 added BuffRemovalEvent to libs/gw2_core (v0.8.0). target_buff_removal.py was added in the same commit, but EventWindowAggregator's per-bucket accumulator only handles DamageEvent + HealingEvent. Result: the per-fight timeline chart (apps/web/src/app/fights/[id]/page.tsx PerFightTimelineChart) has no per-bucket buff-strip band — a researcher investigating "which 5s window saw the most corrupting concentration" has no timeline answer, only the per-target rollup which is blind to per-bucket chronology (correctness, MED) | S |
| 084 | [084-v0927-per-target-aggregators-template-duplication](./084-v0927-per-target-aggregators-template-duplication.md) | **pending** (1 NEW libs/gw2_analytics/src/gw2_analytics/_per_target_base.py: PerTargetRollupBase(Generic[TEvent, TRow]) abstract class implementing aggregate() + _check_invariants() once + a frozen PerTargetFields dataclass-config (event_attr_name + total_attr_name + count_attr_name + rate_attr_name + default_rate). 3 file edits: target_dps.py + target_healing.py + target_buff_removal.py each retain their PUBLIC TargetXxxRow Pydantic model (no API change) + shrink their TargetXxxAggregator body from ~120 lines to ~30 lines. Net diff: ~210 lines deleted across the 3 files + ~150 lines added in the new base = ~60 lines net removed. 8 NEW hermetic tests in NEW libs/gw2_analytics/tests/test_per_target_rollup_base.py cover: empty-list invariants + single-row happy path + multi-row ordering (descending + tie-break) + the 3 subclasses unchanged post-refactor regression tests) | #2 target_dps.py + target_healing.py + target_buff_removal.py are byte-for-byte near-clones that differ ONLY in 5 strings (event attr.name + row field names + rate sentinel). The duplicated parts (~350 lines across 3 files): duration guard + defaultdict accumulators + per-event accumulation + _check_invariants sum-check + pairwise ordering. A future wire-format change requires editing 3 sites in lockstep — drift risk (DX + perf, MED) | S |
| 085 | [085-v0927-squad-rollup-dual-stream-loop-extraction](./085-v0927-squad-rollup-dual-stream-loop-extraction.md) | **pending** (1 file edit in libs/gw2_analytics/src/gw2_analytics/squad_rollup.py: the 3 byte-identical for-loops (one per damage_events + healing_events + strip_events) collapse into 3 calls to a NEW private helper _accumulate_subgroup_totals(events, source_attr_name, contribution_attr_name, totals_dict, hits_dict) -> int that returns the per-stream grand total. 4 NEW hermetic tests in NEW libs/gw2_analytics/tests/test_squad_rollup_refactor.py cover: empty-input short-circuit + single-event happy path + map-driven subgroup rotation + 10-random-event identical-output regression) | #3 squad_rollup.py::SquadRollupAggregator.aggregate() has 3 byte-for-byte near-clone for-loops (for dmg in damage_events: + for heal in healing_events: + for strip in strip_events:). Each loop shares 5 of 6 lines verbatim — only the per-event contribution attribute differs (.damage vs .healing vs .buff_removal). The grand-total accumulators are also near-clones. A Phase 9 +4th event-type addition requires a 4th loop following the same template; a maintainer who forgets hit_count[subgroup] += 1 would silently under-count (DX/cleanup, LOW) | S |

### Recommended execution order (v0.9.27)

1. **Plan 083** (event_window Phase 8 cascade) — S effort, the ONLY correctness finding. 1 file edit + 6 new tests. Independent of 084/085.
2. **Plan 084** (per-target template DRY) — S effort, the largest LOC reduction (~210 lines net). 1 NEW module + 3 file edits + 1 NEW test file. Independent of 083/085.
3. **Plan 085** (squad_rollup 3-stream DRY) — S effort, the smallest finding. 1 file edit + 4 new tests. Independent of 083/084.

All 3 are independent. Could ship in any order. The recommended order is by severity (MED correctness first), then by leverage (DX/perf template), then LOW DX/cleanup.

### Dependency graph (v0.9.27)

```
  plan 083 ──┐                              (event_window.py + test_event_window.py)
  plan 084 ──┼── INDEPENDENT ──────────     (_per_target_base.py NEW + target_dps.py + target_healing.py + target_buff_removal.py + test_per_target_rollup_base.py)
  plan 085 ──┘                              (squad_rollup.py + test_squad_rollup_refactor.py)
```

All 3 plans touch DIFFERENT sibling modules. Plan 084 is a single multi-file PR (one feature, multiple files = canonical multi-file refactor). Plans 083 + 085 can be PR'd in parallel to plan 084.

### Considered and rejected (v0.9.27)

- **Plan 083 alternative: keep EventBucket unchanged + add EventBucketWithStrip schema** — schemas proliferate; additive-field approach is cleaner.
- **Plan 083 alternative: track buff-removal as separate stream + new aggregate_with_strip method** — 2 methods on same class is more surface to maintain.
- **Plan 083 alternative: use Pydantic v2 discriminated unions with explicit type tags** — gw2_core uses isinstance discrimination (existing pattern); plan matches it.
- **Plan 084 alternative: module-level function with 8+ keyword args** — dataclass-config + abstract class is more type-safe + self-documenting.
- **Plan 084 alternative: use Generic[TTotal, TRate] on 3 row types to consolidate schemas** — schemas are PUBLIC API (wire contract); changing row names breaks the wire. Plan keeps PUBLIC row types unchanged.
- **Plan 084 alternative: keep 3 files as-is + add ruff custom rule for byte-identical duplication** — ruff doesn't have such a rule; explicit refactor is canonical fix.
- **Plan 085 alternative: extract generator yielding (subgroup, contribution) tuples** — caller still writes 4-line accumulation; helper-function-returning-int is more direct.
- **Plan 085 alternative: use pyspark or pandas for the join** — out of scope (library is pure-Python aggregates; no pandas dep).
- **Plan 085 alternative: keep 3 loops + add ruff custom rule for for-loops with same body** — rule is hard to write; explicit extraction is canonical.
- **Plan 085 alternative: keep 3 loops but DRY only the per-subgroup assignment line** — extracting only the rotation doesn't capture the full duplication (grand-total accumulation line is also identical).

## v0.9.22 audit (closed)
"""

def main() -> int:
    text = README_PATH.read_text(encoding="utf-8")
    if "## v0.9.27 audit (current)" in text:
        print("v0.9.27 section already present; refusing to re-insert.")
        return 1
    if "## v0.9.22 audit (closed)" not in text:
        print("Anchor '## v0.9.22 audit (closed)' not found; aborting.")
        return 1
    # Replace ONLY the unique v0.9.22 header with NEW_SECTION + v0.9.22 header.
    anchor = "## v0.9.22 audit (closed)"
    new_text = text.replace(anchor, NEW_SECTION, 1)
    README_PATH.write_text(new_text, encoding="utf-8")
    print(f"Inserted v0.9.27 section. README grew {len(new_text) - len(text):+d} chars.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
