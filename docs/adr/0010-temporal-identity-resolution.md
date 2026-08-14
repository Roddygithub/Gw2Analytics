# ADR 0010: Temporal Identity Resolution for CAP-4 (Story 3)

## Context

Story 3 requires certifying identities and temporal ownership:
- Player slices (`firstAware`/`lastAware` windows)
- Character swaps mid-fight
- Instance ID reuse (same ID recycled for different entities)
- Master/pet/minion ownership relationships

**Key constraint from spec**: *"Une architecture explicite est requise avant implémentation si plusieurs modèles de résolution temporelle restent viables."*

Current state in `ei_compare.py`:
- Slice-aware comparison via `_slice_bounds()` using EI's `firstAware`/`lastAware`
- Agent selection by account/name/profession/instance_id in `select_player_agent()`
- `player_agent_ids()` groups by `instance_id` for buff uptime aggregation
- `scan_agent_awareness()` provides raw first/last aware timestamps per agent_id
- **Gap**: No temporal ownership model — `instance_id` is treated as static identity, but pets/minions are owned *temporarily*, instance IDs can be recycled, and character swaps mean the same account maps to different agents at different times.

## Decision

Adopt a **Time-Indexed Ownership Graph** architecture with three layers:

### Layer 1: Raw Agent Timeline (source of truth)
`scan_agent_awareness` already provides `{agent_id: (first_ms, last_ms)}` fight-relative. Extend to emit **statechange events** (spawn/despawn/teamchange/agentupdate) as a timeline per agent.

### Layer 2: Ownership Intervals (derived)
Build **ownership intervals** from raw events:
- `AgentSpawnEvent` → `(agent_id, owner_agent_id, start_ms, end_ms?)`  
  (end_ms from despawn or next spawn of same instance_id)
- `StateChangeEvent` (teamchange, agentupdate) → updates owner metadata
- Instance ID recycling → split intervals when same `instance_id` appears on non-contiguous agent_ids

Result: `ownership_intervals = list[OwnershipInterval]` where each interval is:
```python
@dataclass
class OwnershipInterval:
    agent_id: int  # the minion/pet/gadget agent
    owner_agent_id: int | None  # master at this time (None = uncontrolled)
    instance_id: int
    start_ms: int  # fight-relative
    end_ms: int  # fight-relative (exclusive)
    species_id: int
    is_player: bool
```

### Layer 3: Temporal Identity Resolution (query API)
Provide a **time-parameterized resolver** used by `ei_compare.py`:

```python
class TemporalIdentityResolver:
    def __init__(
        self, intervals: list[OwnershipInterval], agent_awareness: dict[int, tuple[int, int]]
    ): ...

    def owner_at(self, agent_id: int, time_ms: int) -> int | None:
        """Return owning agent_id at given fight-relative timestamp."""
        ...

    def owned_agents_at(self, owner_agent_id: int, time_ms: int) -> list[int]:
        """All agents owned by master at time_ms."""
        ...

    def slice_owner_account(self, owner_agent_id: int, slice_lo: int, slice_hi: int) -> str | None:
        """Account name for the owner during a player slice (for EI player matching)."""
        ...

    def agent_identity_at(self, agent_id: int, time_ms: int) -> AgentIdentity:
        """Resolve full identity: (account, profession, elite, is_player, slice_index?)."""
        ...
```

## Integration Points

| Current code | Change |
|--------------|--------|
| `select_player_agent()` | Replace static lookup with `resolver.agent_identity_at(agent_id, slice_midpoint)` |
| `player_agent_ids()` | Replace `instance_id` grouping with `resolver.owned_agents_at(master_id, time_ms)` per time window |
| `_awareness_bound()` | Keep (uses `agent_awareness` directly) |
| `build_skill_rotation()` | Already receives `agent_id_by_instance` — extend to pass resolver for pet/minion cast attribution |

## Implementation Plan (Incremental)

1. **Parse ownership events** in `gw2_evtc_parser` (new `scan_ownership_intervals()`), emit `OwnershipInterval` list.
2. **Build `TemporalIdentityResolver`** in `gw2_analytics` (new module `temporal_identity.py`).
3. **Wire into `ei_compare.py`**: construct resolver once per fight, pass to comparison helpers.
4. **Add tests** for each CAP-4 scenario (character swap, instance recycle, pet ownership).
5. **Run corpus** — classify new deltas as `KNOWN_DELTA` with rules, iterate until zero unexplained `FAIL`.

## Why This Model

- **Temporal first**: ownership is a function of time, not a static property.
- **Minimal**: reuses existing `scan_agent_awareness` + statechange events; no new parser passes.
- **Composable**: resolver is a pure function of `(intervals, awareness)` — testable in isolation.
- **Compatible**: `ei_compare.py` already slices by time (`in_slice()`); resolver fits same pattern.
- **Extensible**: future phases (phases, target attribution) can query same resolver.

## Alternatives Considered

| Alternative | Rejected Because |
|-------------|------------------|
| Global `instance_id -> owner` map | Fails on instance recycle & character swap (same ID, different owner at different times) |
| Per-slice static resolution | Misses mid-slice ownership changes (pet despawn/respawn within a player slice) |
| Full event-sourcing replay | Overkill; ownership intervals are the minimal sufficient projection |

## Consequences

- New dependency: `gw2_analytics.temporal_identity` used by `ei_compare.py`.
- `gw2_evtc_parser` exposes `scan_ownership_intervals()` (pure, no I/O).
- All CAP-4 deltas become explainable via time-parameterized queries.
- Synthetic tests can inject ownership intervals directly without full EVTC.

---

**Status**: Accepted — ready for implementation in Story 3.