# Plan 026 — Phase 9 condition damage tracking (buff uptime + apply/remove distinction)

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md`.

> **Drift check (run first)**: `git diff --stat 3c524d9..HEAD -- libs/gw2_analytics buf_*/ apps/api/src/gw2analytics_api/`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding.

## Status

- **Priority**: P2
- **Effort**: L (3-4 weeks)
- **Risk**: MEDIUM
- **Depends on**: plan 024 (combat-readout spike), plan 025 (webhook DLQ done)
- **Category**: analytics
- **Planned at**: commit `3c524d9`, 2026-07-11

## Why this matters

The v0.10.6 cycle landed `buff_uptime.py` (per-buff historical tracking) + `buff_dispatch.py` (3-way apply/remove-single/remove-all decoder) in `libs/gw2_analytics`. Two gaps remain before the analyst surface is composable:

1. **No API surface**. The buff models are pure Python; `/api/v1/fights/{id}` + `/api/v1/players/{name}` don't expose buff-state queries.
2. **No parser integration**. The arcdps event stream carries the `is_buffremove` byte (0/1/2) that distinguishes apply vs single vs all-remove, but `parse_events` discards it (the byte is read into a struct field but unused).

Phase 9 closes both gaps by:
- Adding 1 new Event subclass (`BoonApplyEvent`) to `gw2_core`'s discriminated union
- Threading `decode_buff_change` through `parser.parse_events`
- Exposing per-buff uptime via the new endpoint `GET /api/v1/fights/{id}/buff-uptime`

## Current state

### `libs/gw2_analytics/src/gw2_analytics/buff_uptime.py` (Phase 9 prep)
- `BuffState` Pydantic model with `history: list[tuple[int, int]]` (time_ms, stacks)
- `append_stacks(time_ms, stacks)` returns a new model (frozen=True)
- `total_uptime_ms(state, fight_end_ms)` computes the sum of stacks × duration
- `interval_uptime_pct(state, fight_end_ms, fight_start_ms=0)` returns [0.0, 100.0]
- Validators: `NonMonotonicHistoryError`, `NegativeStacksError`

### `libs/gw2_analytics/src/gw2_analytics/buff_dispatch.py` (Phase 9 prep)
- `BuffChangeKind(Enum)`: APPLY, REMOVE_SINGLE, REMOVE_ALL
- `decode_buff_change(is_buffremove_byte: int) -> BuffChangeKind`: 0 → APPLY, 1 → REMOVE_SINGLE, 2 → REMOVE_ALL, unknown → REMOVE_SINGLE (forward-compat)

### `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`
- `parse_events(raw)` reads the 64-byte cbtevent records
- The 9th byte (offset 56 in the struct) is `is_buffremove` — currently read into the struct but discarded

### API surface (today)
- `GET /api/v1/fights/{id}/events` aggregates damage + healing + buff-removal per TARGET agent
- `GET /api/v1/fights/{id}/squads` aggregates per SUBGROUP
- `GET /api/v1/fights/{id}/skills` aggregates per SKILL
- No buff-state endpoint exists

### Schemas (today, modular split landed)
- `apps/api/src/gw2analytics_api/schemas/fight.py:TargetBuffRemovalRowOut` (per-target strip roll-up)
- No `BuffUptimeRowOut` / `BoonStateOut` schemas

## Scope

**In scope**:
- `libs/gw2_core/src/gw2_core/models.py`: add `BoonApplyEvent` subclass
- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`: thread `is_buffremove` byte into `BoonApplyEvent.skills_applied` (or new field) + 3-way decoded enum
- `libs/gw2_analytics/src/gw2_analytics/buff_uptime.py`: extend with `accumulate_buff_events(events) -> dict[int, BuffState]` (per-skill-id BuffState builder from a stream of BoonApplyEvent)
- `apps/api/src/gw2analytics_api/schemas/fight.py`: add `BuffUptimeRowOut` (skill_id + stacks + uptime_ms + uptime_pct)
- `apps/api/src/gw2analytics_api/routes/fights.py`: new `get_fight_buff_uptime(fight_id)` endpoint (1 SQL query to fetch the events blob + per-fight parse + aggregator)
- `apps/api/tests/test_fight_buff_uptime.py`: hermetic tests with 8 fixtures (single buff, multi-buff, stack dynamics, etc.)
- `web/src/lib/api/fights.ts`: add `fetchFightBuffUptime(fightId)` client
- `web/src/app/fights/[id]/BuffUptimeCard.tsx`: render the uptime table

**Out of scope**:
- Skill-database work (Phase 10+; buff names come from `OrmFightSkill` for now)
- Cross-fight buff uptime aggregation (Phase 10+; the per-account timeline is enough for v0.10.x)
- Damage/source attribution by buff (Phase 10; would require a 2nd SQL query and a new aggregator)

## Steps

### Step 1: Add `BoonApplyEvent` to `gw2_core`

In `libs/gw2_core/src/gw2_core/models.py`:

```python
class BoonApplyEvent(Event):
    event_type: Literal["boon_apply"] = "boon_apply"
    skill_id: int
    duration_ms: int
    stacks: int
    # arcdps 2023+ 3-way kind: APPLY (0), REMOVE_SINGLE (1), REMOVE_ALL (2)
    kind: Literal["apply", "remove_single", "remove_all"] = "apply"
```

Update the `Event` discriminated union:
```python
Event = Annotated[
    Union[DamageEvent, HealingEvent, BuffRemovalEvent, BoonApplyEvent],
    Field(discriminator="event_type"),
]
```

**Verify**: `uv run mypy libs/gw2_core/` → exit 0; `uv run pytest libs/gw2_core/tests/` → all pass with the 4th member added.

### Step 2: Thread `is_buffremove` through `parser.parse_events`

In `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`:

The `parse_events` method needs to read the 9th struct byte (`is_buffremove`, value 0/1/2) and:
- For records with `is_statechange == 0` + `is_nondamage == 1` + `value == 0` + `is_buffremove > 0`, currently surface a `BuffRemovalEvent`. Extend to also surface a `BoonApplyEvent` with the decoded `kind` (so the same record drives 2 events: one removal half, one apply-half if it's a reapply).
- For records with `is_statechange == 0` + `is_nondamage == 1` + `buff_dmg > 0` + `is_buffremove == 2`, surface a `BoonApplyEvent(kind="remove_all")` as well.

**Verify**: `uv run pytest libs/gw2_evtc_parser/tests/` → all pass with the new emission paths.

### Step 3: Extend `buff_uptime.py` with `accumulate_buff_events`

```python
def accumulate_buff_events(
    skill_id: int,
    events: Iterable[BoonApplyEvent],
    fight_end_ms: int,
    fight_start_ms: int = 0,
) -> BuffState:
    """Build a BuffState from a stream of BoonApplyEvent records."""
    ...
```

`REMOVE_SINGLE` and `REMOVE_ALL` decrement the stacks; `APPLY` increments.

**Verify**: `uv run pytest libs/gw2_analytics/tests/test_buff_uptime.py` → all pass; new test cases exercise the 3-way apply/single/all-remove sequence.

### Step 4: Add `BuffUptimeRowOut` schema

In `apps/api/src/gw2analytics_api/schemas/fight.py`:

```python
class BuffUptimeRowOut(BaseModel):
    skill_id: int
    skill_name: str | None = None
    stacks: int
    uptime_ms: int
    uptime_pct: float
```

**Verify**: `uv run mypy apps/api/src/gw2analytics_api/schemas/` → exit 0.

### Step 5: Add `GET /api/v1/fights/{id}/buff-uptime` route

In `apps/api/src/gw2analytics_api/routes/fights.py`:

```python
@router.get("/{fight_id}/buff-uptime", response_model=list[BuffUptimeRowOut])
def get_fight_buff_uptime(
    fight_id: str,
    db: Session = Depends(get_session),
) -> list[BuffUptimeRowOut]:
    ...
```

The route reuses `_load_fight_events` (the lru_cache-safe shared helper from the v0.10.5 refactor) + iterates BoonApplyEvent records + groups by skill_id + calls `accumulate_buff_events`.

**Verify**: `uv run pytest apps/api/tests/test_fight_buff_uptime.py` → all pass.

### Step 6: Wire frontend client + UI

In `web/src/lib/api/fights.ts`:

```typescript
export async function fetchFightBuffUptime(fightId: string): Promise<BuffUptimeRow[]> { ... }
```

In `web/src/app/fights/[id]/BuffUptimeCard.tsx`:

A grid-style card showing per-buff uptime with bar-chart visualisation (the existing pattern from `PerPlayerTimelineChart`).

**Verify**: `pnpm test web/src/app/fights/[id]/BuffUptimeCard.test.tsx` → all pass; `pnpm tsc --noEmit` → exit 0.

## Test plan

- `libs/gw2_core/tests/test_event_union.py`: add `BoonApplyEvent` round-trip tests (Pydantic v2 discriminator)
- `libs/gw2_evtc_parser/tests/test_parser_buff_kinds.py`: 5 fixtures exercising the 3-way dispatch
- `libs/gw2_analytics/tests/test_buff_uptime.py`: 8 cases (zero buffers, monotonic violation, stack over-limit, apply/single/remove-all sequences)
- `apps/api/tests/test_fight_buff_uptime.py`: 6 cases (single buff, multi-buff, stacks=0, etc.)
- `web/src/app/fights/[id]/BuffUptimeCard.test.tsx`: 4 cases (empty, 1 buff, 10 buffs, sort stability)

## Done criteria

- [ ] `BoonApplyEvent` round-trips through the Event discriminated union
- [ ] `parser.parse_events` surfaces `BoonApplyEvent(kind=...)` records when `is_buffremove > 0`
- [ ] `accumulate_buff_events` builds correct BuffState from arbitrary event streams
- [ ] `GET /api/v1/fights/{id}/buff-uptime` returns sorted-by-uptime-pct rows
- [ ] Frontend `BuffUptimeCard` renders the 0-100% bar chart correctly
- [ ] All existing tests still pass
- [ ] `mypy` and `ruff` pass on modified files
- [ ] `uv run pytest apps/api/tests/ libs/` exits 0 (excluding the pre-existing `test_uploads_e2e::test_players_list_returns_accounts_present_in_fight` infra failure)

## STOP conditions

Stop and report if:
- The `is_buffremove` byte position in the EVTC struct differs across arcdps versions (would require a parser version pin).
- The BuffState stack count exceeds 25 (GW2's hard cap on most boons), requiring a separate `stacks_capped_at_25` invariant.
- A skill-id appears in 2+ events with conflicting duration_ms values (the parser change might need a "last-seen wins" tiebreaker).

## Maintenance notes

The buff state tracker is a per-fight computation — cross-fight aggregation is Phase 10. The `BoonApplyEvent` lifetime on the wire is bounded by the fight (events blurbs are immutable post-parse). Any future "buff uptime over the last N fights" feature would join multiple per-fight BuffStates, not re-stream the events.
