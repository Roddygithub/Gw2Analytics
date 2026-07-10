# Plan 135: condi/power split heuristic (arcdps build-date gate)

> **Executor instructions**: This is a future-sprint plan. No code yet.
> Captures the per-build-date arcdps combat-event encoding pattern
> the arcdps combat-event decoder (arcdps changelog 2024-05+) as documentation
> for the next v0.10.5 cycle. Do NOT copy code — re-implement the
> algorithm cleanly in our Pydantic+mypy-strict conventions.

> **Drift check (run first)**: `git diff --stat HEAD~1..HEAD -- libs/gw2_analytics/src/gw2_analytics/ libs/gw2_evtc_parser/src/gw2_evtc_parser/`
> If any in-scope file changed, compare the "Current state" excerpts against the live code before proceeding; on mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (additive, no migration needed)
- **Category**: tech-debt / analytics accuracy
- **Planned at**: commit `c935acb`, 2026-07-10 (documentation only)

## Why this matters

arcdps changed its combat-event encoding in mid-2024 (build date
`>= 20240501`): the `buff_dmg` field on strike records now carries
the condi portion of the same hit. Pre-mid-2024 builds encode the
condi portion implicitly (skill name lookup vs a known-condition
list — Bleeding, Burning, Confusion, Poisoned, Torment — matches the
arcdps-named conditions the parser sees in the skill table).

Without this split, condi specs (Scourge, Firebrand, Mirage) report
`power_damage = 100%` on pre-mid-2024 logs, which inverts the squad
roll-up's "condi vs power DPS" column. The calibration is documented
in a public GW2 community reference implementation's `parser.py` per-build-date branching.

## Source calibration (do not copy code)

a public GW2 community reference implementation `parser.py` distinguishes two eras:

```python
# Old-build branch (buff_dmg is metadata, condi inferred via skill-name)
elif skills.get(skill_id) is not None and skills[skill_id].name in KNOWN_CONDI_NAMES:
    condi_portion = value  # entire hit is condi
# New-build branch (buff_dmg encodes condi portion directly, capped)
condi_portion = min(value, max(0, buff_dmg))
```

KNOWN_CONDI_NAMES (a public GW2 community reference implementation) = `frozenset({"Bleeding", "Burning", "Confusion", "Poisoned", "Torment"})`.

Build-date gate: `build_str.isdigit() and int(build_str) >= 20240501`.

Their calibration note explicitly warns: the previous `>= 20260501`
threshold silently disabled the split on every arcdps build (typo,
May 2026 not shipped). The real threshold is `20240501`. We document
the lesson here so the next implementer doesn't repeat the typo.

## Current state

Our project has `libs/gw2_analytics/` with `multi_fight.py`,
`target_dps.py`, `target_healing.py`, `target_buff_removal.py`,
`player_profile.py`, `cross_account_timeline.py`,
`aggregate.py`, `role_detection.py`. The condi/power split is NOT
yet implemented as a separate aggregator; the player roll-up
currently reports `total_damage` only, not the per-kind split.

The `gw2_core` package exposes `EliteSpec.LUMINARY/PARAGON/...` for
the v0.10.3 + Visions of Eternity elite specs (plan 123). The
profession/elite enums are IntEnum-stable — safe to switch on.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint    | `uv run ruff check libs/gw2_analytics/src/gw2_analytics/condi_power_split.py` | exit 0 |
| Typecheck | `uv run mypy --no-incremental libs/gw2_analytics/src/gw2_analytics/condi_power_split.py` | exit 0 |
| Tests | `uv run pytest libs/gw2_analytics/tests/test_condi_power_split.py -v` | all pass |

## Scope

**In scope** (when this plan is executed):
- `libs/gw2_analytics/src/gw2_analytics/condi_power_split.py` — pure function
- `libs/gw2_analytics/tests/test_condi_power_split.py` — hermetic tests
- Aggregation-mapper in `routes/players.py` (`_compute_contributions`) optionally projects the split onto `FightContribution` (additive — does NOT remove existing fields)

**Out of scope** (do NOT touch):
- `libs/gw2_evtc_parser/` — the split is a downstream concern; the parser emits raw events only
- `apps/api/src/gw2analytics_api/services.py` — the ingestion path is unaffected
- Schema / migration — additive column only; nullable for back-compat
- Anything related to direct copy from a public GW2 community reference implementation — re-implement clean

## Steps (for future executor)

### Step 1: Create `condi_power_split.py`

Pure function:

```python
"""Condi/power damage split aggregator.

Pure function on the events stream (no IO, no DB). Returns the
condi and power totals separately for a single `(agent_id, time)` window.
"""
```

Signature sketch:

```python
def split_condi_power(
    events: Iterable[DamageEvent],
    *,
    build_date: str,  # arcdps build date, e.g. "20250925"
    skill_name_getter: Callable[[int], str | None],  # resolves skill_id -> name
) -> tuple[int, int]:  # (condi_damage, power_damage)
```

The body mirrors the a public GW2 community reference implementation branching but with targeted exceptions (DO NOT use a blanket `except Exception`) and Pydantic-friendly int totals.

### Step 2: Tests

3 hermetic tests:

1. New-build path: with `build_date="20250925"` and a DamageEvent carrying `buff_dmg=300, damage=1000`, expect `(300, 700)`. Caps `condi <= damage`.
2. Old-build path: with `build_date="20231101"` and a DamageEvent with `skill_id` whose name is `"Bleeding"`, expect the entire hit as condi.
3. Unknown skill on old-build: `skill_id` not in the skill table — fallback to power.

### Step 3: Wire into `_compute_contributions` (optional, additive)

If the maintainer wants the split to surface on the API: extend `FightContribution` (in `libs/gw2_analytics/src/gw2_analytics/player_profile.py`) with `power_damage: int` + `condi_damage: int`. Both nullable for back-compat with pre-v0.10.5 summary rows.

The `_compute_contributions` `_contributions_from_blob_walk` slow-path loop then calls `split_condi_power()` once per `(fight, account)`. The fast-path summary query stays unchanged for already-populated rows; a backfill CLI is documented separately.

## Test plan

- 3 NEW hermetic tests in `libs/gw2_analytics/tests/test_condi_power_split.py`
- Pattern model: `libs/gw2_analytics/tests/test_role_detection_voe_specs.py` (event-construction style)

## Done criteria

- [ ] `uv run ruff check libs/gw2_analytics/src/gw2_analytics/condi_power_split.py` exits 0
- [ ] `uv run mypy --no-incremental libs/gw2_analytics/src/gw2_analytics/condi_power_split.py` exits 0
- [ ] `uv run pytest libs/gw2_analytics/tests/test_condi_power_split.py -v` — 3 NEW tests pass
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:
- The a public GW2 community reference implementation calibrate-threshold (`20240501`) is no longer accurate per the latest arcdps changelog — verify before implementing.
- `gw2_core.DamageEvent` no longer carries `buff_dmg` (the field was renamed in a future core release).

## Maintenance notes

- The split is **not parser-side**. The parser emits raw `DamageEvent`; the aggregator decides per build_date. This preserves the parser's stream-friendly invariant.
- KNOWN_CONDI_NAMES is a stable set (no new condition classes in 5 years); a hardcoded frozenset is acceptable, but consider an env-driven override (`GW2_CONDITION_NAMES=foo:frozen,...`) for forward-compat.
- The build-date gate uses `build_str.isdigit()` to skip non-numeric build codes arcdps sometimes emits in beta builds. Robust against `int()` ValueError.
- Calibration citation: a public GW2 community reference implementation, 29 .zevtc corpus, 4.47M events, calibration 2025-12. We do NOT re-run that calibration — we trust the documented threshold.
