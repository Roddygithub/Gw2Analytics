# Plan 022 — DRY profession/elite wire-format helpers

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f0249ef..HEAD -- apps/api/src/gw2analytics_api/routes/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plan 019 (mypy catches signature mismatches in the shared helper)
- **Category**: tech-debt
- **Planned at**: commit `f0249ef`, 2026-07-11

## Why this matters

Two route modules implement the same profession/elite → wire-label mapping with different code:

- `fights.py:793`: `"UNKNOWN" if a.profession == 0 else f"PROF({a.profession})"` — inlined in `_to_fight_out`
- `players.py:858-877`: `_profession_label()` and `_elite_label()` — dedicated functions but duplicated logic

If the wire format changes (e.g., from `"PROF(7)"` to `"Mesmer"`), both sites must be updated in lockstep. One could drift.

## Current state

### `routes/fights.py:781-802`
```python
def _to_fight_out(fight: OrmFight) -> FightOut:
    return FightOut(
        ...
        agents=[
            AgentOut(
                ...
                profession=("UNKNOWN" if a.profession == 0 else f"PROF({a.profession})"),
                elite_spec=("BASE" if a.elite_spec == 0 else f"ELITE({a.elite_spec})"),
            )
            for a in fight.agents
        ],
    )
```

### `routes/players.py:858-877`
```python
def _profession_label(profession: Profession) -> str:
    v = profession.value if isinstance(profession, Profession) else int(profession)
    return "UNKNOWN" if v == 0 else f"PROF({v})"

def _elite_label(elite: EliteSpec) -> str:
    v = elite.value if isinstance(elite, EliteSpec) else int(elite)
    return "BASE" if v == 0 else f"ELITE({v})"
```

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `uv sync` | exit 0 |
| Tests | `uv run pytest apps/api/tests/ -x -q` | all pass |
| Lint | `uv run ruff check apps/api/` | exit 0 |
| Typecheck | `uv run mypy apps/api/src/` | exit 0 |

## Scope

**In scope**:
- `apps/api/src/gw2analytics_api/routes/fights.py` (replace inline mapping)
- `apps/api/src/gw2analytics_api/routes/players.py` (keep exported helpers, or move to shared module)
- NEW `apps/api/src/gw2analytics_api/route_helpers.py` (or add to `schemas/fights.py`)

**Out of scope**:
- `gw2_core` models (Profession/EliteSpec enums stay unchanged)
- `AgentOut` schema shape
- Any frontend changes

## Steps

### Step 1: Create shared helpers

Create `apps/api/src/gw2analytics_api/route_helpers.py`:

```python
from gw2_core import EliteSpec, Profession

def format_profession(profession: Profession | int) -> str:
    v = profession.value if isinstance(profession, Profession) else int(profession)
    return "UNKNOWN" if v == 0 else f"PROF({v})"

def format_elite_spec(elite: EliteSpec | int) -> str:
    v = elite.value if isinstance(elite, EliteSpec) else int(elite)
    return "BASE" if v == 0 else f"ELITE({v})"
```

**Verify**: `uv run ruff check apps/api/` → exit 0

### Step 2: Update `routes/fights.py`

Replace the inline `"UNKNOWN" if a.profession == 0 else f"PROF({a.profession})"` in `_to_fight_out` with `format_profession(a.profession)` and the elite equivalent.

Import: `from gw2analytics_api.route_helpers import format_elite_spec, format_profession`

**Verify**: `uv run pytest apps/api/tests/test_fights_*.py -x -q` → all pass

### Step 3: Update `routes/players.py`

Replace the inline code in `_profession_label` and `_elite_label` with calls to the shared helpers. Keep the wrapper functions as thin re-exports for backward compat (they're imported by tests), or deprecate them.

```python
from gw2analytics_api.route_helpers import format_elite_spec, format_profession

def _profession_label(profession: Profession) -> str:
    return format_profession(profession)

def _elite_label(elite: EliteSpec) -> str:
    return format_elite_spec(elite)
```

**Verify**: `uv run pytest apps/api/tests/test_players_*.py -x -q` → all pass

## Test plan

No new tests. Existing route-level tests (from plan 018) cover the wire format contract. The helpers are trivially simple (1-2 lines each).

## Done criteria

- [ ] `route_helpers.py` exists with `format_profession` + `format_elite_spec`
- [ ] Both route modules import and use the shared helpers
- [ ] `uv run pytest apps/api/tests/ -x -q` passes
- [ ] `uv run mypy apps/api/src/` passes
- [ ] `uv run ruff check apps/api/` passes

## STOP conditions

Stop and report if:
- A cycle emerges between `route_helpers.py` and any route module.
- `AgentOut` wire format has changed (drift).

## Maintenance notes

When the wire format changes (e.g., to human-readable profession names), edit `route_helpers.py` — both route modules pick it up automatically.
