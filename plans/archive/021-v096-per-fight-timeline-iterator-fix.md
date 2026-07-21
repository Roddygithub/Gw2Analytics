# Plan 021 — v0.9.6: `PerFightTimelineAggregator` doesn't drain the events iterator

**Author:** senior-advisor audit (improve skill, standard effort) — deep audit of libs/* + web/*.
**Drift base:** `44ea862`.
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** executor model with NO prior context.

---

## Why this matters

`libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py::PerFightTimelineAggregator.aggregate` (around line 110-150) iterates `events` once in the bucket-fill loop, then calls `self._check_invariants(rows, events)`. The invariant check then does `events_list = list(events)` (line 175). If the caller passes a **generator** (the canonical case from the route layer's `_load_fight_events` which returns `list[Event]` but the aggregator's signature is `Iterable[Event]`), the first loop drains the iterator + the second `list(events)` returns `[]`. The expected sums are all 0; the actual sums are non-zero; `ValueError` raised on every call. The endpoint crashes permanently.

Fix: accumulate the expected sums in the first loop + pass them to `_check_invariants` instead of the (drained) iterator.

This is a CRITICAL bug — every call site that passes a generator to the aggregator triggers the invariant violation.

---

## Files IN scope

- `libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py` (`aggregate` + `_check_invariants`).
- `libs/gw2_analytics/tests/test_per_fight_timeline.py` (add 1 generator test).

## Files NOT in scope

- The route layer (`apps/api/src/gw2analytics_api/routes/fights.py::get_fight_timeline`) — passes a `list[Event]` today (the helper's return type), so the bug is currently latent. After plan 021 the helper is free to return a generator for memory efficiency.

---

## Current code (read from `44ea862`)

### `per_fight_timeline.py::PerFightTimelineAggregator.aggregate` (around line 110-150)

```python
def aggregate(self, events, agents=(), duration_s=0.0, *, window_s=5):
    if window_s < _MIN_WINDOW_S:
        raise ValueError(...)
    window_ms = window_s * 1000
    damage_by_bucket: dict[int, int] = defaultdict(int)
    healing_by_bucket: dict[int, int] = defaultdict(int)
    strip_by_bucket: dict[int, int] = defaultdict(int)
    last_bucket_index = -1
    _ = (agents, duration_s)
    for e in events:
        bucket_index = e.time_ms // window_ms
        last_bucket_index = max(last_bucket_index, bucket_index)
        if isinstance(e, DamageEvent):
            damage_by_bucket[bucket_index] += e.damage
        elif isinstance(e, HealingEvent):
            healing_by_bucket[bucket_index] += e.healing
        elif isinstance(e, BuffRemovalEvent):
            strip_by_bucket[bucket_index] += e.buff_removal
    rows: list[PerFightTimelineRow] = []
    for idx in range(last_bucket_index + 1):
        rows.append(PerFightTimelineRow(...))
    self._check_invariants(rows, events)  # ← events is drained
    return list(rows)
```

### `per_fight_timeline.py::_check_invariants` (around line 170-215)

```python
@staticmethod
def _check_invariants(rows, events):
    events_list = list(events)  # ← empty if events was a generator
    expected_damage = sum(e.damage for e in events_list if isinstance(e, DamageEvent))
    ...
    if actual_damage != expected_damage:
        raise ValueError(...)  # ← always raised when events was a generator
```

---

## Step-by-step

### Step 1 — Accumulate expected sums in the first loop

REPLACE the `for e in events` block in `aggregate` with:

```python
    expected_damage = 0
    expected_healing = 0
    expected_strip = 0
    for e in events:
        bucket_index = e.time_ms // window_ms
        last_bucket_index = max(last_bucket_index, bucket_index)
        if isinstance(e, DamageEvent):
            damage_by_bucket[bucket_index] += e.damage
            expected_damage += e.damage
        elif isinstance(e, HealingEvent):
            healing_by_bucket[bucket_index] += e.healing
            expected_healing += e.healing
        elif isinstance(e, BuffRemovalEvent):
            strip_by_bucket[bucket_index] += e.buff_removal
            expected_strip += e.buff_removal
```

### Step 2 — Pass the pre-computed sums to `_check_invariants`

```python
    self._check_invariants(rows, expected_damage, expected_healing, expected_strip)
    return list(rows)
```

### Step 3 — Update `_check_invariants` to take sums (not the iterator)

REPLACE the signature + body:

```python
@staticmethod
def _check_invariants(
    rows: list[PerFightTimelineRow],
    expected_damage: int,
    expected_healing: int,
    expected_strip: int,
) -> None:
    actual_damage = sum(r.total_damage for r in rows)
    actual_healing = sum(r.total_healing for r in rows)
    actual_strip = sum(r.total_buff_removal for r in rows)
    if actual_damage != expected_damage:
        msg = (
            f"sum of row.total_damage ({actual_damage}) != "
            f"expected ({expected_damage})"
        )
        raise ValueError(msg)
    if actual_healing != expected_healing:
        msg = (
            f"sum of row.total_healing ({actual_healing}) != "
            f"expected ({expected_healing})"
        )
        raise ValueError(msg)
    if actual_strip != expected_strip:
        msg = (
            f"sum of row.total_buff_removal ({actual_strip}) != "
            f"expected ({expected_strip})"
        )
        raise ValueError(msg)
    for prev, curr in pairwise(rows):
        if prev.window_end_ms != curr.window_start_ms:
            msg = (...)
            raise ValueError(msg)
```

### Step 4 — Tests

Add to `libs/gw2_analytics/tests/test_per_fight_timeline.py`:

```python
def test_aggregate_accepts_generator_without_draining_it():
    """v0.9.6 plan 021: passing a generator does NOT crash on invariants."""
    def gen():
        for t, dmg, heal, strip in [
            (0, 100, 0, 0), (1500, 200, 0, 0), (3000, 0, 50, 5),
        ]:
            if dmg:
                yield DamageEvent(time_ms=t, source_agent_id=1, target_agent_id=2, skill_id=1, damage=dmg)
            if heal:
                yield HealingEvent(time_ms=t, source_agent_id=1, target_agent_id=2, skill_id=1, healing=heal)
            if strip:
                yield BuffRemovalEvent(time_ms=t, source_agent_id=1, target_agent_id=2, skill_id=1, buff_removal=strip)
    rows = PerFightTimelineAggregator().aggregate(gen(), window_s=1)
    assert len(rows) == 3
    assert rows[0].total_damage == 100
    assert rows[1].total_damage == 200
    assert rows[2].total_healing == 50
    assert rows[2].total_buff_removal == 5
```

---

## Verification commands

```bash
uv run ruff check libs
uv run mypy --no-incremental libs
uv run pytest libs/gw2_analytics/tests/test_per_fight_timeline.py -v
# Expected: 7 existing pass + 1 new pass.
```

A worktree `git diff` against `44ea862` must show ONLY:
- `libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py` (refactor aggregate + _check_invariants signature).
- `libs/gw2_analytics/tests/test_per_fight_timeline.py` (add 1 test).

## Maintenance note

- The fix is mechanical: pre-compute sums once, pass them to the invariant check. No behavior change for the list-input case (which is the canonical route-layer input today).
- The signature change to `_check_invariants` is internal — no public-API impact.
- The `pairwise` contiguous-bucket check is preserved unchanged.

## Escape hatches

- If a future plan needs to support `events: AsyncIterator[Event]`, the sums can be accumulated inside an async for loop. Out of scope here.
