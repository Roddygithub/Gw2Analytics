# Plan 137: BuffState Pydantic v2 model + 3-way buff_remove dispatch

> **Executor instructions**: This is a future-sprint plan. Captures
> the chronological-history arithmetic pattern from
> a public GW2 community reference implementation's `BuffState` dataclass + the 3-way
> `is_buffremove` dispatch for arcdps 2023+ buffs. Do NOT copy code
> — re-implement with Pydantic v2 (no mutation, no `defaultdict`
> hidden state).

> **Drift check (run first)**: `git diff --stat HEAD~1..HEAD -- libs/gw2_analytics/src/gw2_analytics/ libs/gw2_analytics/tests/`
> If any in-scope file changed, compare against the live code before proceeding.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plan 136 (sidecar merge contract feeds the same per-skill data)
- **Category**: tech-debt / aggregation
- **Planned at**: commit `c935acb`, 2026-07-10 (documentation only)

## Why this matters

The buff uptime calculation lives in a public GW2 community reference implementation as a mutable
`BuffState` dataclass with a `history: list[tuple[int, int]]` that
is built chronologically and supports interval arithmetic
(`total_uptime_ms`, `interval_uptime_pct`). Two algorithmic ideas
worth keeping:

1. **Chronological-history invariant** — `history` is appended at
   `ev.time` in monotonic order, so no `sorted(reversed(history))`
   is needed at read time. The uptime sum uses
   `(history[i+1][0] - history[i][0]) * stacks_i`. Pure arithmetic,
   `O(history)`.

2. **3-way `is_buffremove` dispatch** — arcdps 2023+ encodes buff
   apply/remove SINGLE / remove ALL via the same `is_statechange ==
   0` + `ev.buff != 0` channel, distinguished by the
   `is_buffremove` byte (0 = apply, 1 = single-stack remove,
   2 = full-stack remove). Pre-fix, a public GW2 community reference implementation's 2-way dispatch
   collapsed REMOVE_ALL onto REMOVE_SINGLE. The calibration caught
   the bug via per-target condi-cleanses undercount.

We re-implement this in Pydantic v2 (no mutation, validation
barrier) rather than copying the dataclass.

## Source calibration (do not copy code)

a public GW2 community reference implementation `parser.py` has the canonical reference. Key snippets
NOT to copy verbatim:

```python
# Mutable dataclass with history list (FORBIDDEN in our Pydantic style)
@dataclass
class BuffState:
    stacks: int = 0
    history: list[tuple[int, int]] = field(default_factory=list)
```

```python
# Chronological invariant: history is appended at ev.time
# (no sorted/reverse needed at read time)
def total_uptime_ms(self, fight_end: int) -> int:
    for i in range(len(self.history) - 1):
        t, s = self.history[i]
        next_t = self.history[i + 1][0]
        total += s * (next_t - t)
```

```python
# 3-way dispatch calibration (parser.py, dec 2025 follow-up)
# REMOVE_ALL on untracked buffs (condi cleanses) MUST increment by 1,
# NOT by ``max(1, abs(ev.value))`` — observed pattern on real fights
# was 4,294,967,378 / 8,589,934,653 / 17,179,869,277 — all just above
# 2^32 / 2^33 / 2^34, the classic 32-bit-signed-integer overflow
# signature.
```

## Current state

Our project has `role_detection.py` (heuristic role classification)
and `cross_account_timeline.py` (timeline aggregator) in
`libs/gw2_analytics/`. Buff uptime is NOT currently tracked. The
`OrmFightPlayerSummary` schema has no per-buff storage; a future
additive migration could add `buff_uptimes JSONB NULLABLE` to
preserve per-buff ratios.

arcdps 2023+ buff tracking is unimplemented in v0.10.4. This plan
sets up the abstraction layer so the future executor doesn't need
to re-read a public GW2 community reference implementation's source.

## Repo conventions

- `libs/gw2_analytics/` is the home for aggregators; this plan stays
  in that package.
- Pydantic v2 `BaseModel` for stateful tracking — never use
  `dataclass` with mutable defaults; Pydantic validates on input.
- Pure functions for arithmetic (`total_uptime_ms`, `interval_pct`).
  Test them as standalone (no fixture dance).
- Docstring convention: every public function gets a one-line
  summary + complexity (`O(history)`) + invariants on `history`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `uv run ruff check libs/gw2_analytics/src/gw2_analytics/buff_uptime.py` | exit 0 |
| Typecheck | `uv run mypy --no-incremental libs/gw2_analytics/src/gw2_analytics/buff_uptime.py` | exit 0 |
| Tests | `uv run pytest libs/gw2_analytics/tests/test_buff_uptime.py -v` | all pass |

## Scope

**In scope** (when executed):
- `libs/gw2_analytics/src/gw2_analytics/buff_uptime.py` — `BuffState` Pydantic model + `compute_uptime` / `compute_interval_pct` pure functions
- `libs/gw2_analytics/src/gw2_analytics/buff_dispatch.py` — 3-way `is_buffremove` decoder returning a typed enum (`BuffChangeKind` in `{APPLY, REMOVE_SINGLE, REMOVE_ALL}`)
- `libs/gw2_analytics/tests/test_buff_uptime.py` + `test_buff_dispatch.py` — hermetic tests

**Out of scope**:
- `libs/gw2_evtc_parser/` — buff dispatch is downstream of parser struct decode
- Schema migrations (handled in plan 136 sidecar plan if needed for per-skill storage)
- Copying a public GW2 community reference implementation code wholesale — re-implement with Pydantic

## Steps (for future executor)

### Step 1: `BuffState` Pydantic model

```python
class BuffState(BaseModel):
    """Per-buff uptime tracker. History is append-only and chronological."""
    history: list[tuple[int, int]] = Field(default_factory=list)
```

Pydantic v2 enforces `tuple[int, int]` shape — buggy appends fail validation at model-construction time, not at runtime aggregation.

### Step 2: Pure uptime functions

```python
def total_uptime_ms(state: BuffState, fight_end_ms: int) -> int: ...
def interval_uptime_pct(state: BuffState, fight_end_ms: int, fight_start_ms: int = 0) -> float: ...
```

Both maintain the chronological-history invariant (the caller of `BuffState.append_stacks_at(time, stacks)` must ensure monotonic time). The docstring spells this out so a future maintainer doesn't break the invariant.

### Step 3: 3-way `BuffChangeKind` enum + dispatch

```python
class BuffChangeKind(Enum):
    APPLY = "apply"
    REMOVE_SINGLE = "remove_single"
    REMOVE_ALL = "remove_all"

def decode_buff_change(is_buffremove_byte: int) -> BuffChangeKind:
    """arcdps 2023+ 3-way dispatch via the is_buffremove byte (0/1/2)."""
```

This is the calibration-2025-12 fix: REMOVE_ALL on untracked buffs (condi cleanses) MUST be +1, NOT +weighted. The 3-way dispatch makes the bug invisible to the caller.

### Step 4: Tests

5 hermetic tests:

1. `BuffState` rejects invalid history entry (`[1, "x"]` fails validation).
2. `total_uptime_ms` on a 2-pair history sums correctly: `[(0, 0), (1000, 5), (2000, 0)]` + fight_end=3000 → uptime = 5000 (5 stacks × 1000 ms).
3. `interval_uptime_pct` returns 50.0 for half-the-time active.
4. `decode_buff_change(0)` → APPLY, `decode_buff_change(1)` → REMOVE_SINGLE, `decode_buff_change(2)` → REMOVE_ALL.
5. `decode_buff_change(99)` → safe default (REMOVE_SINGLE — matches a public GW2 community reference implementation's "unknown byte" fallback).

## Test plan

- 5 NEW hermetic tests
- Pattern model: `libs/gw2_analytics/tests/test_event_window.py` (event-construction style)

## Done criteria

- [ ] `uv run ruff check libs/gw2_analytics/src/gw2_analytics/buff_uptime.py libs/gw2_analytics/src/gw2_analytics/buff_dispatch.py` exits 0
- [ ] `uv run mypy --no-incremental libs/gw2_analytics/src/gw2_analytics/buff_uptime.py libs/gw2_analytics/src/gw2_analytics/buff_dispatch.py` exits 0
- [ ] `uv run pytest libs/gw2_analytics/tests/test_buff_uptime.py libs/gw2_analytics/tests/test_buff_dispatch.py -v` — all pass
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- If arcdps changes the `is_buffremove` byte semantics (e.g. adds
  REMOVE_PARTIAL=3), the dispatch needs an update. Verify against
  the latest arcdps changelog before implementing.
- If `BuffState.history` is somehow expected to be NON-chronological
  (e.g. multi-source merge), the invariants change. The current
  plan enforces chronological from the caller side.

## Maintenance notes

- The 3-way dispatch calibration is the load-bearing piece — DO NOT
  collapse to 2-way (regresses condi-cleanse credits).
- The `seen_native_heal` gate from a public GW2 community reference implementation's calibration is a
  separate concern (plan 136's sidecar merge contract); this plan
  does NOT implement the gate. Keep the two concerns separated.
- Buff uptimes without per-buff storage are out of scope here —
  future schema migration handles the persistence layer.
