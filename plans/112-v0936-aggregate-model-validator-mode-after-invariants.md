# Plan 112 (v0.9.36) — `aggregate.py` invariants migration to `FightAggregate` `@model_validator(mode="after")`

## Files touched
- `libs/gw2_analytics/src/gw2_analytics/aggregate.py` (replace `SingleFightAggregator._check_invariants` static method with `@model_validator(mode="after") validator` on the `FightAggregate` Pydantic model; remove the manual call from `aggregate()`)

## Findings (audit)

- `libs/gw2_analytics/src/gw2_analytics/aggregate.py::FightAggregate` (`model_config = ConfigDict(frozen=True, extra="forbid")`) declares the per-field constraints. The class docstring says "the invariants listed on :class:`SingleFightAggregator` are *post-construction* validated".
- `libs/gw2_analytics/src/gw2_analytics/aggregate.py::SingleFightAggregator._check_invariants(agg)` is a `@staticmethod` that 3 invariants:
  1. `player_count + npc_count == agent_count`
  2. `skill_count == len(skill_catalog)`
  3. For every `GroupSummary g`: `g.combatant_count == actual_combatants_in_subgroup(g.subgroup)`
- The check is invoked at the END of `SingleFightAggregator.aggregate(fight)`. If invariant 1 or 2 is violated, the function raises `ValueError`.
- Real-world issues with this pattern:
  1. The schema `FightAggregate` has NO documented invariant protection. A future contributor who constructs a `FightAggregate` directly via `model_validate(...)` or `model_construct(...)` would silently bypass the invariants.
  2. Defense-in-depth (`test_aggregate_rejects_empty_fight_id_via_model_construct`) explicitly tests the path. The test is correct BUT reveals that the schema is under-defended.
  3. Pydantic v2 has the canonical `@model_validator(mode="after")` decorator for exactly this case (cross-field invariant validation that runs AFTER Pydantic's per-field validation). The pattern self-validates on `FightAggregate(...)` direct construction.
- A 3rd, weaker issue: the docstring on `SingleFightAggregator` enumerates the invariants as if they're constructor-side, but they're really schema-side (the invariants are about the OUTPUT `FightAggregate`, not about the INPUT `Fight`). The current location is misnomer.

## Fix

1. `libs/gw2_analytics/src/gw2_analytics/aggregate.py` — replace the static-method invariants with a Pydantic v2 `@model_validator(mode="after")` on the `FightAggregate` Pydantic model:

   ```python
   from pydantic import BaseModel, ConfigDict, Field, model_validator

   # ... existing model code unchanged ...

   class FightAggregate(BaseModel):
       """Denormalised single-fight aggregation.

       Cross-field invariants are enforced via :func:`_validate_invariants`
       (a Pydantic v2 :func:`model_validator(mode="after")`), which runs
       after Pydantic's per-field validation but before the
       ``model_validate(...)`` call returns to the caller.

       Pydantic's per-field constraints (``frozen=True``,
       ``extra=forbid``, ``min_length``, ``ge``, ``le``) catch
       individual-field violations; the
       :func:`_validate_invariants` hook catches the 3
       cross-field invariants that per-field constraints
       don't see.
       """

       model_config = ConfigDict(frozen=True, extra="forbid")

       fight_id: str = Field(..., min_length=1)
       encounter_id: int = Field(..., ge=0, le=0xFFFF)
       agent_count: int = Field(..., ge=0)
       player_count: int = Field(..., ge=0)
       npc_count: int = Field(..., ge=0)
       skill_count: int = Field(..., ge=0)
       combatants: list[CombatantSummary] = Field(default_factory=list)
       groups: list[GroupSummary] = Field(default_factory=list)
       skill_catalog: list[SkillCatalogEntry] = Field(default_factory=list)

       @model_validator(mode="after")
       def _validate_invariants(self) -> "FightAggregate":
           """Raise ``ValueError`` if any cross-field invariant is violated.

           Invariants enforced:

           1. ``player_count + npc_count == agent_count`` -- the
              two counts together MUST account for every agent in
              the fight.
           2. ``skill_count == len(skill_catalog)`` -- the values
              are coupled; the count is denormalised for fast
              cross-validation.
           3. For every :class:`GroupSummary g`` in
              ``self.groups``:
              ``g.combatant_count == sum(1 for c in combatants if c.subgroup == g.subgroup)`` --
              the per-subgroup count MUST match the actual
              combatants landing in the same bucket.
           """
           if self.player_count + self.npc_count != self.agent_count:
               msg = (
                   f"player_count + npc_count ({self.player_count + self.npc_count}) "
                   f"!= agent_count ({self.agent_count})"
               )
               raise ValueError(msg)
           if self.skill_count != len(self.skill_catalog):
               msg = (
                   f"skill_count ({self.skill_count}) != len(skill_catalog) ({len(self.skill_catalog)})"
               )
               raise ValueError(msg)
           for g in self.groups:
               expected = sum(1 for c in self.combatants if c.subgroup == g.subgroup)
               if g.combatant_count != expected:
                   msg = (
                       f"GroupSummary({g.subgroup!r}).combatant_count "
                       f"({g.combatant_count}) != actual combatants in that "
                       f"subgroup ({expected})"
                   )
                   raise ValueError(msg)
           return self
   ```

2. Replace the `aggregate()` body's final `_check_invariants` call with NOTHING (the validator runs at construction time). The current body:

   ```python
   aggregate = FightAggregate(...)

   # Cross-field invariants are not enforced by Pydantic BaseModel
   # field constraints; assert them post-construction.
   self._check_invariants(aggregate)
   return aggregate
   ```

   Becomes:

   ```python
   return FightAggregate(...)

   # Cross-field invariants are enforced inside ``FightAggregate``'s
   # @model_validator(mode="after") -> ``_validate_invariants``; a
   # violation raises ``ValueError`` at construction time, which
   # propagates to the ``aggregate`` caller. The Pydantic-v2
   # model_validator is the canonical cross-field invariant hook.
   ```

3. REMOVE the `SingleFightAggregator._check_invariants` static method entirely (it's superseded by the schema-side validator).

## Tests (4, NEW or EXTEND existing test_aggregate.py)

- `test_model_validator_catches_invariant_violation_via_model_validate` — `FightAggregate.model_validate({...agent_count=2, player_count=0, npc_count=1...})` raises `ValueError` whose message contains `"player_count + npc_count (1)"` and `"agent_count (2)"`. Defensive: confirms the validator fires on direct `model_validate` construction (the path that was UNDEFENDED before this plan).
- `test_model_validator_catches_skill_count_invariant` — same pattern, `skill_count=5` + `skill_catalog` with 4 entries → `ValueError`.
- `test_model_validator_catches_group_combatant_count_invariant` — same pattern, `combatant_count` mismatches the actual combatants in the subgroup.
- `test_aggregate_still_rejects_via_aggregator_path` (regression test) — `SingleFightAggregator().aggregate(fight_with_violation)` raises `ValueError`. Confirms the `aggregate()` path didn't lose the validation when the static method was removed.

## Rejected alternatives

- **Move the invariants to a `validate_invariants()` method on `FightAggregate` (kept outside Pydantic)** — same current state (a separate method, called manually). The `@model_validator(mode="after")` is the canonical Pydantic v2 hook; it fires at construction time without manual invocation. REJECTED.
- **Keep the static method AND add a `@model_validator`** — dual enforcement is DRY violation (3 invariants declared twice). The single-source-of-truth approach is the right call. REJECTED.
- **Use `@field_validator` for each field with cross-field checks** — `@field_validator` runs per-field at Pydantic field-validation time; cross-field invariants require `@model_validator(mode="after")` because by the time `@field_validator` runs, the cross-field context isn't yet available. REJECTED.
- **Move invariants to `MultiFightAggregator` (per plan 055 architecture)** — wrong location. The invariants are about the OUTPUT `FightAggregate` schema, not the cross-fight rollup. The schema is the canonical place. REJECTED.
- **Skip the migration; keep the static method** — leaves the schema undefended for direct `model_validate` paths. The defense-in-depth test in `test_aggregate.py` (`test_aggregate_rejects_empty_fight_id_via_model_construct`) already documents the concern. The migration closes that documented gap. REJECTED.

## Dependency graph

- Independent: touches `aggregate.py` only.
- Parallel-safe with plans 110 / 111 (different files).
- Pattern-aligns with the workspace-wide Pydantic v2 idiomatic-style (the rest of `gw2_core` and `apps/api/schemas.py` already use `@model_validator(mode="after")` for cross-field checks; this plan migrates the outlier in `gw2_analytics.aggregate.py`).
- Future-proofs future schemas (e.g. a Phase 9 multi-fight rollup that adds a new cross-field invariant) — the validator pattern is the canonical authoring pattern.
