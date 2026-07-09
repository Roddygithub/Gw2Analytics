# Plan 117 (v0.9.38) — `routes/fights.py::get_fight_events` monolithic 200+ lines → extract per-target roll-up helper for DRY

## Files touched
- `apps/api/src/gw2analytics_api/routes/fights.py` (introduce a NEW `_aggregate_per_target_rollup(events, agent_id_to_name, duration_s, event_cls, aggregator_cls) -> list[RowOut]` helper that the 3 sibling roll-ups share, collapsing the `get_fight_events` route handler from 200+ lines to ~80)
- `apps/api/tests/routes/test_fights_per_target_helper.py` (NEW — 5 hermetic tests pinning the helper's discriminator + dispatch + assert invariants)

## Findings (audit)

- `apps/api/src/gw2analytics_api/routes/fights.py::get_fight_events` line ~250 spans **~200 lines** with three structurally-identical branches back-to-back:

  ```python
  target_dps = TargetDpsAggregator().aggregate(
      [e for e in events if isinstance(e, DamageEvent)],
      duration_s,
      name_map=agent_id_to_name,
  )
  target_healing = TargetHealingAggregator().aggregate(
      [e for e in events if isinstance(e, HealingEvent)],
      duration_s,
      name_map=agent_id_to_name,
  )
  target_buff_removal = TargetBuffRemovalAggregator().aggregate(
      [e for e in events if isinstance(e, BuffRemovalEvent)],
      duration_s,
      name_map=agent_id_to_name,
  )
  ```

  Each branch is structurally identical:
  1. Filter the heterogeneous `events` stream via `isinstance(e, X)`.
  2. Pick the corresponding aggregator class.
  3. Aggregate with `(events, duration_s, name_map=...)`.
  4. Schema-validate each row via `TargetXRowOut.model_validate(r.model_dump())`.

  The 3 occurrences of `model_validate(r.model_dump())` ALSO share the same pattern — list comprehension across `[TargetDpsRowOut, TargetHealingRowOut, TargetBuffRemovalRowOut]` outputs.

- The `EventBucketOut` cold branch above (the `event_windows` roll-up) is genuinely different (consumes the full heterogeneous stream + a different aggregator) — it stays inline.
- Net effect: the route handler is **~120 lines of pure cuttable noise** that obscures the routing contract (response shape, error codes, dependency injection).
- Why this matters more than just plain DRY:
  - The 3 per-target roll-ups MUST have IDENTICAL semantic invariants (sum-of-row == sum-of-event, name-resolve consistency, ordering invariance). If a future maintainer adds an optional `window_s` to the `TargetDpsAggregator` (e.g. "include overtime damage"), they would have to edit 3 filtered-list comprehensions + 3 aggregate calls + 3 schema validating list comprehensions — every divergence is a bug surface.
  - The `_to_fight_out` helper, the `_load_fight_events` helper, and the `_parse_profession_filter` helper exist BECAUSE of this exact pattern. Extending it to per-target roll-ups is the canonical next step.
  - The 200+ line route handler violates the "routes should be thin" principle — the Phase 7 v1 design explicitly noted the routes consolidate "thin serialization + cross-cutting layer concerns" (each <40 lines per the v0.8.0 design doc).
- A separate **adjacent** finding: `_TIMELINE_DEFAULT_WINDOW_S: int = 5` + `_TIMELINE_MAX_WINDOW_S: int = 600` are declared at lines ~108-109 of `fights.py`, and `_EVENTS_DEFAULT_WINDOW_S: int = 5` + `_EVENTS_MAX_WINDOW_S: int = 600` are declared AGAIN at lines ~218-219. Two declarations with the same defaults `5` + same bounds `[1, 600]`. Both should consolidate to a single module-level `_PER_FIGHT_DEFAULT_WINDOW_S: int = 5` + `_PER_FIGHT_MAX_WINDOW_S: int = 600` — but this is a hygiene grab; the bigger finding is the monolithic handler.

## Fix

1. NEW `_aggregate_per_target_rollup` helper in `routes/fights.py`:

   ```python
   from gw2_analytics.target_buff_removal import TargetBuffRemovalRow, TargetBuffRemovalAggregator
   from gw2_analytics.target_dps import TargetDpsRow, TargetDpsAggregator
   from gw2_analytics.target_healing import TargetHealingRow, TargetHealingAggregator

   def _aggregate_per_target_rollup(
       events: list[Event],
       agent_id_to_name: dict[int, str | None],
       duration_s: float,
       event_cls: type[Event],
   ) -> list[TargetDpsRow | TargetHealingRow | TargetBuffRemovalRow]:
       """Compute one per-target roll-up branch (DPS / healing / buff-removal).

       Centralises the 3 sibling roll-up branches in
       :func:`get_fight_events` (the one structural change
       introduced by Phase 8 v0.8.0 + v0.8.3). Each branch was
       3 lines: an ``isinstance`` filter, an aggregator call
       with ``(events, duration_s, name_map=...)``, and a
       schema-validation list comprehension. The helper picks
       the aggregator + output-row-type by ``event_cls`` so the
       route layer wraps schema validation in a thin
       comprehension with the right ``RowOut`` subclass.

       Mapping
       -------
       ``DamageEvent`` -> :class:`TargetDpsAggregator`
       ``HealingEvent`` -> :class:`TargetHealingAggregator`
       ``BuffRemovalEvent`` -> :class:`TargetBuffRemovalAggregator`

       Any other ``event_cls`` (e.g. a Phase 9
       ``ConditionDamageEvent``) raises ``ValueError`` -- the
       dispatch table is explicitly closed-form so a future
       addition is a single-line edit here.

       Performance
       -----------
       The ``isinstance`` filter is one pass over ``events``.
       For a multi-million-event fight (rare but possible in
       WvW) the filter is still O(N) -- the cost is amortised
       across the 3 calls because the same event is filtered
       3 times. The aggregated shape (a few hundred rows) is
       small by comparison.
       """
       if event_cls is DamageEvent:
           aggregator = TargetDpsAggregator()
       elif event_cls is HealingEvent:
           aggregator = TargetHealingAggregator()
       elif event_cls is BuffRemovalEvent:
           aggregator = TargetBuffRemovalAggregator()
       else:
           raise ValueError(
               f"_aggregate_per_target_rollup: unknown event_cls {event_cls!r}; "
               f"expected DamageEvent | HealingEvent | BuffRemovalEvent"
           )
       return aggregator.aggregate(
           [e for e in events if isinstance(e, event_cls)],
           duration_s,
           name_map=agent_id_to_name,
       )
   ```

2. Refactor `get_fight_events` to call the helper:

   ```python
   target_dps_rows = _aggregate_per_target_rollup(
       events, agent_id_to_name, duration_s, DamageEvent,
   )
   target_healing_rows = _aggregate_per_target_rollup(
       events, agent_id_to_name, duration_s, HealingEvent,
   )
   target_buff_removal_rows = _aggregate_per_target_rollup(
       events, agent_id_to_name, duration_s, BuffRemovalEvent,
   )
   ```

   The route body drops from ~120 lines to ~20 in the per-target section. Total handler shrinks from ~200 lines to ~80 lines.

3. Consolidate `_TIMELINE_*_WINDOW_S` + `_EVENTS_*_WINDOW_S` constants:

   ```python
   # Module-level single-source-of-truth for window-S bounds.
   # The per-fight timeline + the per-bucketed events roll-up
   # share the same default (5 seconds -- the standard GW2
   # toolchain bucketing convention) and the same bounds
   # (1 second minimum -- aggregator invariant; 600 seconds
   # ceiling -- sanity bound). The previous design declared
   # the constants twice with identical values
   # (``_TIMELINE_DEFAULT_WINDOW_S`` + ``_EVENTS_DEFAULT_WINDOW_S``);
   # this is the canonical single-source.
   _PER_FIGHT_DEFAULT_WINDOW_S: int = 5
   _PER_FIGHT_MAX_WINDOW_S: int = 600
   ```

   Both `get_fight_timeline` + `get_fight_events` reference the unified constants.

4. Add an `EventBucketOut` cold-branch (the `event_windows` roll-up) — leave as-is (different aggregator signature, full heterogeneous stream).

## Tests (5, NEW `apps/api/tests/routes/test_fights_per_target_helper.py`)

- `test_per_target_helper_dispatches_damage_event_to_dps_aggregator` — call `_aggregate_per_target_rollup(events_with_one_damage, name_map, 12.5, DamageEvent)` → returns 1 row, the row's `total_damage == 42` (the fixture's damage value).
- `test_per_target_helper_dispatches_healing_event_to_healing_aggregator` — same pattern with `HealingEvent` → `TargetHealingRow`.
- `test_per_target_helper_dispatches_buff_removal_event_to_buff_removal_aggregator` — same pattern with `BuffRemovalEvent` → `TargetBuffRemovalRow`.
- `test_per_target_helper_raises_value_error_on_unknown_event_cls` — pass `FakePhase9Event` (a `FakeConditionDamage(Event)` subclass in the test file) → `ValueError` with the canonical message.
- `test_per_target_helper_returns_empty_list_for_empty_iterator` — call with `events=[]` + arbitrary valid `event_cls` → `[]`.

## Rejected alternatives

- **Merge `get_fight_timeline` into `get_fight_events`** — the v0.8.9 design doc explicitly carved out the timeline endpoint to allow parallel fetching via `Promise.allSettled`. Reverting that cost more than it gains. REJECTED (and re-ratified by Plan 049 design rationale).
- **Use `functools.singledispatch` on the `Event` superclass** — `singledispatch` registers handlers by type but the helper is closed-form (3 dispatch targets + 1 error case). A plain `if/elif` is more readable. REJECTED.
- **Move the helper NOT to `routes/fights.py` but to `_event_dispatch.py`** — the helper consumes aggregator classes that are tightly coupled to the route layer's wire format (TargetXRowOut → RowOut). The helper bridges raw events → wire-shape rows, which is a route-layer concern. Keep it in `routes/fights.py`. REJECTED.
- **Make the helper `async`** — synchronous aggregation is correct (the aggregators are in-memory, no IO). Adding `async` for symmetry with the `account.py` route is the wrong layering. REJECTED.
- **Fold the `event_windows` roll-up into the same helper** — `EventWindowAggregator` consumes the heterogeneous stream AND a `window_s` parameter; the signature is different. The helper is bounded to the 3 isomorphic per-target roll-ups for clarity. REJECTED.
- **Skip the constant consolidation (`_TIMELINE_*` + `_EVENTS_*`)** — minor but a clear DRY win (single-source-of-truth for two operating-mode defaults). KEPT.

## Dependency graph

- Independent of plans 116 / 118. Plan 116 refactors the adapter-only; Plan 117 refactors the route body; Plan 118 surfaces the per-account accumulator typing. The 3 plans can ship concurrently as 3 separate PRs.
- Touches 1 production source file (`routes/fights.py`) + 1 NEW test file.
- Patterns align with the v0.9.27 plans 083-085 (per-target trio aggregation tests) — same `Raw → Aggregator → RowOut` shape. The helper is the route-layer mirror of the aggregator-library's already-existing `TargetDpsRow / TargetHealingRow / TargetBuffRemovalRow` row-typed outputs.
- Future-proofs the Phase 9 `ConditionDamageEvent` extension: adding the 4th per-target roll-up is a 1-line edit to the dispatch table + a 4-line edit to the route handler. The previous design would have required ~30 lines.

## Notes for executors

- The 3 aggregator classes all expose `.aggregate(events, duration_s, name_map=...)` with identical signatures. Verify after refactor.
- The schema-validation step (`TargetXRowOut.model_validate(r.model_dump())`) stays in the route handler — it's a wire-format concern, not an aggregation concern.
- The `EventBucketOut` cold branch (event_windows) is a separate `EventWindowAggregator().aggregate(events, window_s=window_s)` call — it does NOT fit the helper's signature.
