# Plan 022 — v0.9.6: `MultiFightAggregator` dedups reconnecting player accounts

**Author:** senior-advisor audit (improve skill, standard effort) — deep audit of libs/* + web/*.
**Drift base:** `44ea862`.
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** executor model with NO prior context.

---

## Why this matters

`libs/gw2_analytics/src/gw2_analytics/multi_fight.py::MultiFightAggregator.aggregate` (around line 125) iterates `per_fight.combatants` and increments `player_attendance[acct] = player_attendance.get(acct, 0) + 1` for **every combatant** — including the case where one account has multiple combatants in a single fight (a reconnect, a class swap, a squad move). The invariant `c.player_attendance <= len(fight_ids)` then fails with `ValueError` for any such fight, crashing the multi-fight aggregation permanently.

Fix: dedup `account_name` per-fight before incrementing. A player is "in this fight" if ANY of their combatants is present, not "N times per combatant".

---

## Files IN scope

- `libs/gw2_analytics/src/gw2_analytics/multi_fight.py` (`MultiFightAggregator.aggregate`).
- `libs/gw2_analytics/tests/test_multi_fight.py` (add 1 reconnect test).

## Files NOT in scope

- The `SingleFightAggregator` (per-fight rollup); the reconnect produces multiple combatants there but the per-fight invariant is `player + npc == agent` (sum-preservation, not attendance).
- The `CombatantRollup` schema; the field name `player_attendance` stays.

---

## Current code (read from `44ea862`)

### `multi_fight.py::MultiFightAggregator.aggregate` (around line 95-135)

```python
for fight in fights:
    ...
    per_fight = self._inner.aggregate(fight)
    for c in per_fight.combatants:
        acct = c.account_name
        first_seen_profession.setdefault(acct, c.profession)
        first_seen_elite.setdefault(acct, c.elite)
        last_seen_name[acct] = c.name
        player_attendance[acct] = player_attendance.get(acct, 0) + 1
        # ↑ BUG: increments per-combatant, not per-fight-per-account.
        # Reconnects produce multiple combatants with the same account_name
        # within a single fight → attendance over-counts → invariant crash.
```

---

## Step-by-step

### Step 1 — Add per-fight `seen_accounts` dedup

REPLACE the inner `for c in per_fight.combatants` loop with:

```python
for fight in fights:
    ...
    per_fight = self._inner.aggregate(fight)
    # v0.9.6 plan 022: dedup per-fight before incrementing attendance.
    # A player who reconnects / swaps class / moves squad within a
    # single fight has multiple combatants with the same
    # account_name; we count attendance ONCE per fight per account
    # (the player is either "in this fight" or "not in this fight",
    # not "in this fight N times"). The state is per-fight, so
    # re-initialise inside the outer loop.
    seen_accounts_this_fight: set[str] = set()
    for c in per_fight.combatants:
        acct = c.account_name
        if acct in seen_accounts_this_fight:
            continue
        seen_accounts_this_fight.add(acct)
        first_seen_profession.setdefault(acct, c.profession)
        first_seen_elite.setdefault(acct, c.elite)
        last_seen_name[acct] = c.name
        player_attendance[acct] = player_attendance.get(acct, 0) + 1
```

### Step 2 — Tests

Add to `libs/gw2_analytics/tests/test_multi_fight.py`:

```python
def test_multi_fight_dedups_reconnecting_players_per_fight():
    """v0.9.6 plan 022: a single account with 2 combatants in 1 fight counts as 1 attendance."""
    from gw2_core import Agent, EliteSpec, EvtcHeader, Fight, Profession

    # A fight with 2 agents sharing the same account_name (reconnect scenario).
    fight = Fight(
        id="fight1",
        header=EvtcHeader(build_version="20240101", encounter_id=1, skill_count=0, agent_count=2),
        agents=[
            Agent(id=1, name="CharA", profession=Profession.WARRIOR, elite=EliteSpec.BERSERKER,
                  elite_raw=18, is_player=True, account_name=":acct.1234", subgroup="1"),
            Agent(id=2, name="CharA", profession=Profession.WARRIOR, elite=EliteSpec.BERSERKER,
                  elite_raw=18, is_player=True, account_name=":acct.1234", subgroup="1"),
        ],
        skills=[],
    )
    agg = MultiFightAggregator().aggregate([fight])
    assert len(agg.fight_ids) == 1
    assert len(agg.combatant_rollups) == 1
    assert agg.combatant_rollups[0].account_name == ":acct.1234"
    assert agg.combatant_rollups[0].player_attendance == 1  # not 2
    assert agg.total_players == 1
```

---

## Verification commands

```bash
uv run ruff check libs
uv run mypy --no-incremental libs
uv run pytest libs/gw2_analytics/tests/test_multi_fight.py -v
# Expected: existing tests pass + 1 new test passes.
```

A worktree `git diff` against `44ea862` must show ONLY:
- `libs/gw2_analytics/src/gw2_analytics/multi_fight.py` (add `seen_accounts_this_fight` set + `if acct in seen_accounts_this_fight: continue`).
- `libs/gw2_analytics/tests/test_multi_fight.py` (add 1 test).

## Maintenance note

- The dedup is keyed on `account_name`. If a future plan needs to distinguish "the player disconnected" from "the player was the same agent the whole time", add an `agent_id` field to `CombatantRollup` (one row per agent, not per account). Out of scope here.
- The `seen_accounts_this_fight` set is initialised inside the outer `for fight in fights` loop, so it resets per-fight correctly.
- The `last_seen_name` is overwritten on every combatant (the original code overwrote it per-combatant too). With the dedup, the overwrite happens on the FIRST combatant per fight (which is the deterministic first-combatant — the `per_fight.combatants` is sorted by `SingleFightAggregator`'s deterministic ordering).

## Escape hatches

- If a future plan surfaces the per-combatant character-name timeline (e.g. "CharA was renamed to CharB mid-fight"), the `last_seen_name` should track per-combatant not per-account. Out of scope here.
- If the per-fight dedup needs to be lifted for analytics (e.g. "how many agents did the player use in this fight"), add a `combatant_ids_per_fight: dict[str, set[int]]` field. Out of scope.
