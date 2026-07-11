# Plan 055 — v0.9.17: `SingleFightAggregator._check_invariants` opt-in via Settings debug flag

## Drift base

`44ea862`. Drift cleanup only — additive, no migration.

## Surface

`libs/gw2_analytics/src/gw2_analytics/aggregate.py::SingleFightAggregator.aggregate`
+ NEW optional `settings: AggregatorSettings | None = None` constructor
parameter on `SingleFightAggregator` + NEW
`apps/api/src/gw2analytics_api/config.py::AggregatorSettings` field
+ NEW `apps/api/.env.example` entry.

## Finding

`aggregate()` calls `self._check_invariants(aggregate)` on EVERY
invocation, unconditionally. The check walks all 3 invariants
in O(groups × combatants) for the GroupSummary ↔ combatants
consistency check (`sum(1 for c in agg.combatants if c.subgroup == g.subgroup)`
re-computed per group).

For the canonical load (100-player WvW raid, 5 subgroups):
- 1 group iteration × 100-combatant scan = 100 comparisons per
  call (and re-iterated 5 times = 500 comparisons).
- 1 `sum(1 for c in agg.combatants if c.subgroup == g.subgroup)`
  is 1 full pass per group, so 5 passes = 500 dict-attribute
  lookups + comparisons.

For the canonical 1000-fights/day load (one canonical
arcdps user runs ~5-10 raids/day, 100s of users), this is
500,000 walks/day — measurable but not the bottleneck. The
bottleneck is the per-fight query, not the per-combatant
scan.

The check is a *defence-in-depth* guard against the aggregator
silently producing inconsistent output. The other 2 invariants
(`player_count + npc_count == agent_count` +
`skill_count == len(skill_catalog)`) are O(1) checks. The
expensive one is the per-group walk.

The current code runs the check unconditionally, even in
production hot paths where the invariant is known to hold
(by construction: the aggregator is the only writer of
`FightAggregate`).

## Fix

1. NEW `AggregatorSettings` class in
   `apps/api/src/gw2analytics_api/config.py`:

   ```python
   class AggregatorSettings(BaseModel):
       model_config = ConfigDict(extra="forbid", frozen=True)
       validate_invariants: bool = False  # prod-safe default (off)
   ```

2. `SingleFightAggregator.__init__(self, settings: AggregatorSettings | None = None)`:
   defaults to `None`; if `None`, the check is OFF (matches the
   default Settings value). If `settings.validate_invariants is True`,
   the check runs.

3. `aggregate()` end-of-method becomes:

   ```python
   if self._settings is not None and self._settings.validate_invariants:
       self._check_invariants(aggregate)
   return aggregate
   ```

4. `apps/api/.env.example` adds:
   `GW2_ANALYTICS_VALIDATE_AGGREGATOR_INVARIANTS=false` with a
   comment block explaining the perf vs safety tradeoff.

5. The `apps/api` route layer
   (`routes/fights.py::get_fight_events`) passes the
   `settings.aggregator.validate_invariants` flag to the
   aggregator constructor.

6. The `tests/test_aggregate.py` file (already exists) gains
   2 NEW hermetic tests:
   - `test_aggregate_skips_invariants_by_default`: assert no
     `ValueError` even when the invariant is violated (e.g. by
     monkeypatching the comparator).
   - `test_aggregate_runs_invariants_when_opted_in`: assert
     the `ValueError` is raised when the settings flag is True.

7. The `gw2_analytics` library does NOT depend on
   `apps/api/config.py` (the dependency arrow is reversed:
   the API consumes the library, not the other way around).
   The library exposes the constructor parameter; the API
   passes the settings. **The library's default is OFF** —
   the test suite opts in via a `_test_settings` fixture.

## Why default OFF (not default ON)

The invariants are constructed by the aggregator; the only
way to violate them is a programming bug in the aggregator.
The check is a development-time guard, not a runtime safety
net. CI + integration tests run with the flag ON; production
runs with the flag OFF. This is the standard "lint is dev-only,
runtime is opt-in" pattern.

The canonical usage (gw2_analytics library consumers outside
the apps/api codebase) does not need the check; they construct
the aggregator without settings.

## Risks

- A programming bug in the aggregator that violates an
  invariant will be silent in production. Mitigation: the
  CI test suite runs with `validate_invariants=True` on every
  PR; the bug is caught in CI before deploy.
- The `AggregatorSettings` class is a small additive change to
  `config.py`. The `Settings` model is `frozen=True` (Pydantic
  v2 best practice); the new field is a single bool, no
  cross-field interactions.
- The route layer (1 site) gains a 1-line change to pass the
  settings flag. The library aggregator's public surface
  changes (new optional constructor parameter); backward-
  compat is preserved (default behavior is "check runs" so
  existing callers that don't pass settings see no change in
  behavior — wait, that's wrong; the new default is OFF).

**Backward-compat consideration**: the current behavior is
"check runs unconditionally". The new default is "check does
NOT run". This is a behavior change for any existing caller
that does not pass settings. The mitigation is that the
aggregator's invariants are constructed by the aggregator
itself; the only way to violate them is a programming bug,
and the bug would be caught in CI on the next test run.

The `CHANGELOG` entry under `[Unreleased]` documents the
behavior change: "`SingleFightAggregator` now skips the
post-construction invariant check by default. Set
`settings.validate_invariants=True` to re-enable the check
(for dev / CI). The check costs O(groups × combatants) per
call; it was previously on the hot path unconditionally."

## Tests

1. `test_aggregate_skips_invariants_by_default` — construct
   the aggregator with no settings; patch
   `_check_invariants` to raise; call `aggregate()`; assert
   no exception.
2. `test_aggregate_runs_invariants_when_opted_in` — construct
   the aggregator with `settings=AggregatorSettings(validate_invariants=True)`;
   patch `_check_invariants` to raise; call `aggregate()`;
   assert `ValueError` propagates.
3. `test_aggregator_settings_forbid_extra_fields` — assert
   `AggregatorSettings(validate_invariants=True, foo=42)`
   raises `pydantic.ValidationError`.
4. `test_aggregator_settings_is_frozen` — assert
   `settings.validate_invariants = True` raises
   `pydantic.ValidationError` (or `AttributeError` on a
   frozen model).
5. `test_route_passes_settings_flag` — patch
   `SingleFightAggregator.__init__` to capture the
   `settings` kwarg; call the route; assert the flag is
   plumbed from `Settings.aggregator.validate_invariants`.

## Rejected alternatives

- **Run the check always but use a `Counter` for O(1) per-group
  lookup**: keeps the check on the hot path. The cost of the
  check is not the bottleneck (the O(N×M) walk is fast for
  N=100); the value of the check is dev-time. Opt-in is the
  right tradeoff.
- **Run the check only in `__debug__` mode** (Python's `-O`
  flag): tempting (the check is a dev-time guard). But the
  `__debug__` flag is global; the operator can't enable the
  check for a single endpoint. The per-aggregator `settings`
  flag is more granular.
- **Make the check a `@staticmethod` and require callers to
  call it explicitly after `aggregate()`**: too easy to forget;
  the opt-in flag ensures the check is consistent across
  callers.
- **Move the check to the consumer (route layer)**: the route
  layer doesn't have visibility into the invariant semantics;
  the check belongs with the writer.
- **Drop the check entirely**: the check is cheap on the
  dev-time path; removing it loses the safety net. The opt-in
  flag preserves the net for dev/CI.
- **Add a `validate_invariants: bool = True` keyword arg to
  `aggregate()` (not the constructor)**: a per-call flag is
  too easy to forget on a per-call site; the constructor
  flag is set once per `SingleFightAggregator` instance.
