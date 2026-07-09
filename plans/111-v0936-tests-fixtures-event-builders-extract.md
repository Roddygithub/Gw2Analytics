# Plan 111 (v0.9.36) — Event factory fixtures DRY: `_damage` + `_healing` + `_strip` extraction

## Files touched
- NEW `libs/gw2_analytics/tests/_event_fixtures.py` (NEW — `make_damage_event(...)` + `make_healing_event(...)` + `make_buff_removal_event(...)` factories)
- `libs/gw2_analytics/tests/test_target_dps.py` (replace local `_damage` with `make_damage_event`)
- `libs/gw2_analytics/tests/test_target_healing.py` (replace local `_damage`; rename parameter `damage→healing` if present)
- `libs/gw2_analytics/tests/test_target_buff_removal.py` (replace local `_damage`/`_strip`; the `_strip.buff_removal` field naming difference is a real bug-class consumer)
- `libs/gw2_analytics/tests/test_squad_rollup.py` (replace local `_damage`/`_heal`/`_strip`; the `_heal.value` vs `_healing.healing` parameter naming difference is a real bug-class consumer)
- `libs/gw2_analytics/tests/test_per_fight_timeline.py` (replace local `_damage`/`_healing`/`_strip`)

## Findings (audit)

- `test_target_dps.py::_damage(time_ms, damage, target=1, source=1)` helper. Builds `DamageEvent(time_ms=time_ms, source_agent_id=source, target_agent_id=target, skill_id=42, damage=damage)` — implicit `skill_id=42`.

- `test_squad_rollup.py::_damage(time_ms, src, dst, value, skill_id=1)` helper. Builds the SAME `DamageEvent` but uses `src`, `dst`, `value` arg names instead of `source`, `target`, `damage`. The functional field mapping is `damage=value`. **Parameter naming divergence + value-vs-domain-name divergence** — the same call signature means different things.

- `test_squad_rollup.py::_heal(time_ms, src, dst, value, skill_id=2)` helper. Builds `HealingEvent(... healing=value)` — uses `src`, `dst`, `value`. Same divergence.

- `test_per_fight_timeline.py::_damage(time_ms, damage, target=1)` helper. Builds the SAME `DamageEvent` but with `source_agent_id=99` (a different default), `skill_id=42`.

- `test_per_fight_timeline.py::_healing(time_ms, healing)` helper. Builds `HealingEvent(source_agent_id=99, target_agent_id=1, skill_id=43, healing=healing)` — uses `target_agent_id=1` (hard-coded, not defaulted).

- The 5 test files extract the SAME 3 events (`DamageEvent`/`HealingEvent`/`BuffRemovalEvent`) but with 4 different parameter naming conventions:
  - `test_target_dps.py`: `time_ms, damage, target, source` (domain names)
  - `test_squad_rollup.py`: `time_ms, src, dst, value` (raw-pointer names)
  - `test_per_fight_timeline.py`: `time_ms, damage, target` (domain names, partial)
  - `test_target_*` / `test_target_buff_removal.py` (NOT YET READ): probably more divergence
- Real-world impact: when a test moves (e.g. test_squad_rollup imports from the canonical helper), the parameter names change and 6+ test call sites need updating. The convention divergence is a maintenance hazard.
- The constants (skill_ids: 42 / 43 / 44 in the timeline file; 1 / 2 / 3 in the squad file; 42 in the dps file) ALSO diverge — they don't need to be the same number, but they document themselves inconsistently. Worse, the skill_id defaults COULD collide across tests that mock the same skill.
- `value` is the term the raw cbtevent layout uses (the integer payload of one cbtevent record). The aggregator types name the same field by its semantic meaning (`damage`, `healing`, `buff_removal`). The DRY violation spans BOTH the test surface AND the cbtevent ↔ Pydantic mapping layer.

## Fix

1. NEW `libs/gw2_analytics/tests/_event_fixtures.py`:

   ```python
   """Shared synthetic event factories for :mod:`gw2_analytics` tests.

   The :class:`~gw2_core.DamageEvent` /
   :class:`~gw2_core.HealingEvent` /
   :class:`~gw2_core.BuffRemovalEvent` builders were
   duplicated across 5 test files (test_target_dps,
   test_target_healing, test_target_buff_removal,
   test_squad_rollup, test_per_fight_timeline) with
   subtly different parameter naming conventions.

   This module is the canonical single source. Future tests
   import from here. The factories use the DOMAIN-NAMED
   parameter style (``target``, ``damage``) — NOT the
   raw-pointer style (``src``, ``dst``, ``value``) used in
   test_squad_rollup.py — because domain names ARE how a
   future contributor reasons about the event.

   Defaults:
   - ``skill_id``: 42 (damage) / 43 (healing) /
     44 (buff-removal). Mimics the per_fight_timeline.py
     pattern (range starts at 42, increments by 1 per
     event kind). The previous divergent defaults (1/2/3
     in squad_rollup, 42/43/44 in per_fight_timeline) are
     reconciled here -- the canonical range is 42-44.
   - ``source_agent_id``: 99 (the per_fight_timeline
     default; the conventional "any-source" sentinel
     that's distinct from any specific target).
   - ``target_agent_id``: 1.

   Constructors are intentionally pure (no randoms, no
   mocks, no async, no IO) so they're trivially testable
   AND reusable in any test pattern.
   """
   from __future__ import annotations

   from typing import Final

   from gw2_core import BuffRemovalEvent, DamageEvent, HealingEvent

   # Per-event-kind canonical skill_id. The 42-44 range is
   # arbitrary -- what matters is that the 3 kinds use
   # DISTINCT ids so a test that asserts the skill_id on a
   # yielded event can detect a kind-mismatch (a real bug
   # class in the parser-side dual-emit path).
   _SKILL_ID_DAMAGE: Final[int] = 42
   _SKILL_ID_HEALING: Final[int] = 43
   _SKILL_ID_BUFF_REMOVAL: Final[int] = 44

   # Canonical "any source" sentinel. Distinct from any
   # target_agent_id used in the realistic fight tests (typically
   # 1-99 for player targets, 100-999 for NPC targets).
   _ANY_SOURCE_AGENT_ID: Final[int] = 99


   def make_damage_event(
       time_ms: int,
       damage: int,
       *,
       target: int = 1,
       source: int = _ANY_SOURCE_AGENT_ID,
       skill_id: int = _SKILL_ID_DAMAGE,
   ) -> DamageEvent:
       """Build a :class:`DamageEvent` with domain-named parameters.

       Use the canonical default skill_id / source unless the
       test requires an override (e.g. a multi-source test).
       """
       return DamageEvent(
           time_ms=time_ms,
           source_agent_id=source,
           target_agent_id=target,
           skill_id=skill_id,
           damage=damage,
       )


   def make_healing_event(
       time_ms: int,
       healing: int,
       *,
       target: int = 1,
       source: int = _ANY_SOURCE_AGENT_ID,
       skill_id: int = _SKILL_ID_HEALING,
   ) -> HealingEvent:
       """Build a :class:`HealingEvent` with domain-named parameters."""
       return HealingEvent(
           time_ms=time_ms,
           source_agent_id=source,
           target_agent_id=target,
           skill_id=skill_id,
           healing=healing,
       )


   def make_buff_removal_event(
       time_ms: int,
       buff_removal: int,
       *,
       target: int = 1,
       source: int = _ANY_SOURCE_AGENT_ID,
       skill_id: int = _SKILL_ID_BUFF_REMOVAL,
   ) -> BuffRemovalEvent:
       """Build a :class:`BuffRemovalEvent` with domain-named parameters."""
       return BuffRemovalEvent(
           time_ms=time_ms,
           source_agent_id=source,
           target_agent_id=target,
           skill_id=skill_id,
           buff_removal=buff_removal,
       )
   ```

2. The 5 test files import from this canonical module. Their existing test bodies use the helpers as `_damage(...)`, `_heal(...)`, `_strip(...)` — preserve those aliases for backward-compat at the call sites:

   ```python
   # In test_target_dps.py:
   from tests._event_fixtures import make_damage_event as _damage
   ```

3. `test_squad_rollup.py` parameter naming changes from `src/dst/value` → `source/target/damage+healing+buff_removal` per kind — every call site in the file gets the same update. The aliases `_damage`/`_heal`/`_strip` are kept; only the keyword arguments inside them change.

## Tests (6, NEW file `libs/gw2_analytics/tests/test__event_fixtures.py`)

- `test_make_damage_event_default_args` — `make_damage_event(time_ms=1000, damage=200).damage == 200` AND `source_agent_id == 99` AND `target_agent_id == 1` AND `skill_id == 42`. Confirms the canonical defaults.
- `test_make_healing_event_default_args` — same with `_healing` field.
- `test_make_buff_removal_event_default_args` — same with `buff_removal` field.
- `test_three_kinds_have_distinct_skill_ids` — assert `_SKILL_ID_DAMAGE == 42`, `_SKILL_ID_HEALING == 43`, `_SKILL_ID_BUFF_REMOVAL == 44` — three distinct values. A future regression that conflates two kinds under one skill_id (e.g. a parser-side mistake) would fail this test.
- `test_make_damage_event_accepts_override` — explicit `skill_id=99`, `source=42`, `target=7` overrides all canonical defaults.
- `test_factories_return_immutable_pydantic_models` — `make_damage_event(0, 100)` is a frozen pydantic model; mutation raises (mirrors the `test_aggregate.py::test_aggregate_is_frozen_pydantic` contract pin).

## Rejected alternatives

- **Add `_damage(...)` etc. as private re-exports inside `_fixtures.py` (plan 110)** — couples the synthetic fixtures with the event factories; the 2 files have different scopes (agents+fight vs events). Two modules keep the scope tight. REJECTED.
- **Keep divergent skill_id defaults — "42 for damage, 43 for healing, 44 for buff-removal" is arbitrary anyway** — true, but the divergent values across files (``1/2/3`` in squad_rollup vs ``42/43/44`` in timeline) ARE the maintenance hazard. The canonical-42-44 is a defensible arbitrary that survives the consolidation. REJECTED.
- **Use a `@functools.cache` on the factories** — caching a Pydantic v2 model is fine but adds a cache invalidation concern (the test_factory_X is no longer "pure" — it returns the same cached object for the same args). Pure factories are simpler and the test runs fast enough. REJECTED.
- **Use the `value` parameter-naming convention everywhere** — `value` is the cbtevent-layer name (the raw integer payload); the aggregator surfaces it as `damage` / `healing` / `buff_removal`. Mixing the conventions in tests is the source of the divergence; the canonical helper picks the DOMAIN convention (aggregator-side). REJECTED.
- **Use `*args, **kwargs` for a fully-flexible factory** — defeats the typed-signature benefit; Pydantic v2 doesn't play well with reflective construction. The explicit `keyword=` form is the canonical pattern. REJECTED.

## Dependency graph

- Independent: NEW `tests/_event_fixtures.py` + 5 modified test files. No production code touched.
- Parallel-safe with plans 110 / 112.
- Pattern-aligns with plan 110: 2 parallel `_fixtures.py` + `_event_fixtures.py` modules in the tests package. Both are private (`_` prefix) and consume `gw2_core` Pydantic models.
- Future-proofs the 5 test files: each call site is now a single keyword invocation; adding a new field to `DamageEvent` (e.g. `crit: bool`) ripples to ONE central factory, not 5 per-file copies.
