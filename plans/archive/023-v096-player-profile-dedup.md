# Plan 023 — v0.9.6: `PlayerProfileAggregator` accumulates per-character contributions

**Author:** senior-advisor audit (improve skill, standard effort) — deep audit of libs/* + web/*.
**Drift base:** `44ea862`.
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** executor model with NO prior context.

---

## Why this matters

`libs/gw2_analytics/src/gw2_analytics/player_profile.py::PlayerProfileAggregator.aggregate` (around line 115-130) checks `if key in seen_pairs: continue` BEFORE accumulating `total_damage` / `total_healing` / `total_buff_removal`. The dedup was meant to handle "the same `(account, fight_id)` pair appears twice" (route layer bug, manual fixup) — but the fix silently drops the per-character damage/healing/strip from the second occurrence. For a player with 2 characters in the same fight (e.g. a WvW squad swap mid-fight), the second character's contribution is under-counted.

Fix: drop the `if key in seen_pairs: continue` early-skip. The `attended_fight_ids` set already handles dedup via set semantics; we want to ACCUMULATE the magnitudes (across multiple characters in the same fight), not drop them.

---

## Files IN scope

- `libs/gw2_analytics/src/gw2_analytics/player_profile.py` (`PlayerProfileAggregator.aggregate`).
- `libs/gw2_analytics/tests/test_player_profile.py` (add 1 multi-character test).

## Files NOT in scope

- The `FightContribution` schema (per-character `total_damage` etc. are already there; the bug is in the aggregation).
- The `PlayerProfile` schema (`attended_fight_ids` is already a set, dedup is automatic).
- The route layer (`apps/api/src/gw2analytics_api/routes/players.py`) — its `_contributions_from_blob_walk` emits one `FightContribution` per (account, fight_id) pair, but a future plan could change it to per-character without re-touching this aggregator.

---

## Current code (read from `44ea862`)

### `player_profile.py::PlayerProfileAggregator.aggregate` (around line 110-135)

```python
for c in contributions:
    acct = c.account_name
    first_seen_profession.setdefault(acct, c.profession)
    first_seen_elite.setdefault(acct, c.elite)
    last_seen_name[acct] = c.name
    # Dedup on (account_name, fight_id): the same account
    # appearing twice in the same fight (route layer bug,
    # manual table fixup) silently folds to a single
    # contribution. ``seen_pairs.add(...)`` returns None if
    # the pair was already present; the subsequent accumulation
    # steps are skipped in that case so ``fights_attended``
    # stays at the actual count of distinct fights.
    key = (acct, c.fight_id)
    if key in seen_pairs:
        continue  # ← BUG: drops per-character magnitudes
    seen_pairs.add(key)
    attended_fight_ids.setdefault(acct, set()).add(c.fight_id)
    total_damage[acct] = total_damage.get(acct, 0) + c.total_damage
    total_healing[acct] = total_healing.get(acct, 0) + c.total_healing
    total_buff_removal[acct] = total_buff_removal.get(acct, 0) + c.total_buff_removal
```

---

## Step-by-step

### Step 1 — Drop the `seen_pairs` early-skip; always accumulate

REPLACE the inner loop body with:

```python
for c in contributions:
    acct = c.account_name
    # v0.9.6 plan 023: a single account can emit multiple
    # ``FightContribution`` records for the same fight (one per
    # character — a class swap / squad move / reconnect emits a
    # new agent under the same ``account_name``). We ACCUMULATE
    # the per-character magnitudes; the ``attended_fight_ids``
    # set below handles the dedup automatically (set semantics
    # collapse the duplicates). The pre-plan-023
    # ``if key in seen_pairs: continue`` early-skip silently
    # dropped the second character's contribution; the fix
    # moves the per-magnitude accumulation OUTSIDE the
    # dedup check.
    first_seen_profession.setdefault(acct, c.profession)
    first_seen_elite.setdefault(acct, c.elite)
    last_seen_name[acct] = c.name
    attended_fight_ids.setdefault(acct, set()).add(c.fight_id)
    total_damage[acct] = total_damage.get(acct, 0) + c.total_damage
    total_healing[acct] = total_healing.get(acct, 0) + c.total_healing
    total_buff_removal[acct] = total_buff_removal.get(acct, 0) + c.total_buff_removal
```

### Step 2 — Remove the now-unused `seen_pairs` set

The `seen_pairs: set[tuple[str, str]] = set()` declaration at the top of `aggregate` is no longer used; drop it.

### Step 3 — Tests

Add to `libs/gw2_analytics/tests/test_player_profile.py`:

```python
def test_player_profile_accumulates_per_character_contributions():
    """v0.9.6 plan 023: 2 characters in 1 fight contribute their magnitudes."""
    from gw2_core import EliteSpec, Profession
    c1 = FightContribution(
        fight_id="fight1", account_name=":acct.1234",
        name="CharA", profession=Profession.WARRIOR, elite=EliteSpec.BERSERKER,
        total_damage=1000, total_healing=0, total_buff_removal=0,
    )
    c2 = FightContribution(
        fight_id="fight1", account_name=":acct.1234",
        name="CharB", profession=Profession.MESMER, elite=EliteSpec.MIRAGE,
        total_damage=500, total_healing=200, total_buff_removal=10,
    )
    profiles = PlayerProfileAggregator().aggregate([c1, c2])
    assert len(profiles) == 1
    p = profiles[0]
    assert p.fights_attended == 1  # set semantics
    assert p.total_damage == 1500  # 1000 + 500
    assert p.total_healing == 200  # 0 + 200
    assert p.total_buff_removal == 10  # 0 + 10
    assert p.name == "CharB"  # last-seen name wins
```

---

## Verification commands

```bash
uv run ruff check libs
uv run mypy --no-incremental libs
uv run pytest libs/gw2_analytics/tests/test_player_profile.py -v
# Expected: existing tests pass + 1 new test passes.
```

A worktree `git diff` against `44ea862` must show ONLY:
- `libs/gw2_analytics/src/gw2_analytics/player_profile.py` (drop `seen_pairs` + remove early-skip; always accumulate).
- `libs/gw2_analytics/tests/test_player_profile.py` (add 1 test).

## Maintenance note

- The fix is mechanical: drop the `if key in seen_pairs: continue` line. The accumulator handles dedup via set semantics on `attended_fight_ids`.
- The `last_seen_name` continues to overwrite per-contribution (which is the canonical "last-seen" semantic).
- For a player who never swaps class, the first-seen profession/elite are unchanged. For a player who swaps, the first-seen stays anchored to the first character.

## Escape hatches

- If a future plan surfaces "this player has used N characters" as a per-profile field, add `character_count: int = 0` to `PlayerProfile` + accumulate during the loop. Out of scope here.
- If a future plan needs to surface the per-character timeline (e.g. "CharA was used for 5 fights, CharB for 3"), add a `per_character_contributions: dict[str, list[FightContribution]]` field. Out of scope.
