# Plan 015 — v0.9.4: player routes fast-path via `OrmFightPlayerSummary` direct query

**Author:** senior-advisor audit (improve skill, standard effort) — second pass on the deferred v0.9.3 audit findings.
**Drift base:** `44ea862` (origin/main HEAD at plan authoring).
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** an executor model with NO prior context.

---

## Why this matters

`apps/api/src/gw2analytics_api/routes/players.py` has 3 endpoints (`list_players`, `get_player`, `get_player_timeline`) that all load **every** `OrmFight` row + their `OrmFightAgent` relationships via `selectinload(OrmFight.agents)`, then iterate in memory to compute the per-fight contributions:

```python
fights = (
    db.execute(
        select(OrmFight)
        .order_by(OrmFight.started_at.desc())
        .options(selectinload(OrmFight.agents)),
    )
    .scalars()
    .all()
)
contributions = _compute_contributions(db, fights)
```

At 10k+ fights, this is **O(N) full-table scan + O(N) in-memory aggregation**. Latency > 1 s; memory spike during the load.

The v0.8.4 materialised `OrmFightPlayerSummary` table has every column the 3 routes need — **EXCEPT** `started_at` (which lives on `OrmFight`). The fix: a single SQL query that JOINs the summary table to `OrmFight` for `started_at` (per the senior-advisor thinker: "you don't need a migration; simply JOIN"). No new column on the summary, no Alembic migration.

---

## Files IN scope

- `apps/api/src/gw2analytics_api/routes/players.py` (`_compute_contributions`, `list_players`, `get_player`, `get_player_timeline`).
- `apps/api/tests/test_players_fastpath.py` — **NEW** (4 tests: 3 regression + 1 perf).
- `apps/api/src/gw2analytics_api/models.py` — NO change (re-reading the existing `OrmFightPlayerSummary` docstring + columns is enough).

## Files NOT in scope

- `libs/*` (no change to the `PlayerProfileAggregator`; it consumes `FightContribution` as before).
- `apps/api/alembic/versions/*` (no migration; the JOIN covers `started_at`).
- `apps/api/src/gw2analytics_api/services.py` (the materialisation in `_persist_player_summaries` is correct as-is; this plan only changes the READ path).

---

## Current code (read from `44ea862`)

### `routes/players.py::_compute_contributions` (around line 95-150)

```python
def _compute_contributions(db, fights):
    if not fights:
        return []
    fight_ids = [f.id for f in fights]
    fast_path_ids = _fast_path_fight_ids(db, fight_ids)
    contributions = []
    for fight in fights:
        if fight.id in fast_path_ids:
            contributions.extend(_contributions_from_summary(db, fight.id))
        else:
            contributions.extend(_contributions_from_blob_walk(fight))
    return contributions
```

The hybrid dispatches per-fight: fast-path (summary table) or slow-path (blob walk). The slow-path is O(events) per fight; the fast-path is O(rows) per fight, but the dispatch is still O(fights) in Python.

### `routes/players.py::list_players` (around line 174-205)

```python
fights = (
    db.execute(
        select(OrmFight)
        .order_by(OrmFight.started_at.desc())
        .options(selectinload(OrmFight.agents)),
    )
    .scalars()
    .all()
)
contributions = _compute_contributions(db, fights)
profiles = PlayerProfileAggregator().aggregate(contributions)
```

### `routes/players.py::get_player` and `get_player_timeline` (similar shape)

Both load all fights + agents; both build a `fight_id_to_started: dict` for the timeline sort.

---

## Step-by-step

### Step 1 — Replace `_compute_contributions` with a single JOIN-based query

```python
def _compute_contributions(db) -> tuple[list[FightContribution], dict[str, datetime]]:
    """Read ``OrmFightPlayerSummary`` directly with a JOIN to ``OrmFight``
    for ``started_at``. Returns a (contributions, fight_id_to_started) pair.

    The previous hybrid loaded ALL fights + agents + dispatched per-fight
    to either the summary path or the blob-walk path. The new path
    is a single indexed query (O(rows) with N log N on the PK index)
    and bypasses the blob walk entirely for post-v0.8.4 fights.

    Pre-v0.8.4 fights (those without ``OrmFightPlayerSummary`` rows)
    produce zero contributions on this path. The v0.8.5 backfill
    script + the v0.8.6 health probe already detect + remediate
    pre-v0.8.4 fights; once the production dataset is post-v0.8.4,
    the legacy ``_contributions_from_blob_walk`` fallback can be
    deleted in a future v0.9.5 cleanup plan.
    """
    rows = db.execute(
        select(
            OrmFightPlayerSummary.fight_id,
            OrmFightPlayerSummary.account_name,
            OrmFightPlayerSummary.name,
            OrmFightPlayerSummary.profession,
            OrmFightPlayerSummary.elite_spec,
            OrmFightPlayerSummary.total_damage,
            OrmFightPlayerSummary.total_healing,
            OrmFightPlayerSummary.total_buff_removal,
            OrmFight.started_at,
        )
        .join(OrmFight, OrmFight.id == OrmFightPlayerSummary.fight_id)
        .order_by(OrmFight.started_at.desc(), OrmFightPlayerSummary.fight_id.asc())
    ).all()
    contributions = [
        FightContribution(
            fight_id=r.fight_id,
            account_name=r.account_name,
            name=r.name,
            profession=Profession(r.profession),
            elite=EliteSpec(r.elite_spec),
            total_damage=r.total_damage,
            total_healing=r.total_healing,
            total_buff_removal=r.total_buff_removal,
        ) for r in rows
    ]
    fight_id_to_started = {r.fight_id: r.started_at for r in rows}
    return contributions, fight_id_to_started
```

### Step 2 — Update the 3 route handlers

`list_players`, `get_player`, `get_player_timeline` all DROP the `fights` query + the `selectinload(OrmFight.agents)`. The new pattern is:

```python
@router.get("", response_model=list[PlayerListRowOut])
def list_players(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    profession: str = Query("", ...),
    db: Session = Depends(get_session),
) -> list[PlayerListRowOut]:
    parsed_profession = _parse_profession_filter(profession)
    # v0.9.4 plan 015: drop the ALL-fights + ALL-agents pre-load.
    # The materialised summary table is the source of truth.
    contributions, _ = _compute_contributions(db)
    profiles = PlayerProfileAggregator().aggregate(contributions)
    if parsed_profession is not None:
        profiles = [p for p in profiles if p.profession == parsed_profession]
    page = profiles[offset : offset + limit]
    return [...]
```

For `get_player` and `get_player_timeline`, the new pattern is:

```python
contributions, fight_id_to_started = _compute_contributions(db)
own_contributions = [c for c in contributions if c.account_name == account_name]
if not own_contributions:
    raise HTTPException(404, "player not found")
# fight_id_to_started is already provided by the JOIN — no separate query needed
```

The `get_player_timeline` route also gains a small refinement: the day-bucketing branch now keys off `fight_id_to_started[c.fight_id]` instead of the previous `fight_id_to_started = {f.id: f.started_at for f in fights}` line.

### Step 3 — Delete the now-unused helpers

The following helpers in `routes/players.py` are no longer called and should be deleted:

- `_fast_path_fight_ids` (the `EXISTS` query).
- `_contributions_from_summary` (per-fight SELECT).
- `_contributions_from_blob_walk` (the slow-path; kept ONLY if a future plan needs pre-v0.8.4 fallback; otherwise deleted).

The `selectinload(OrmFight.agents)` import is also dropped.

### Step 4 — Tests

`apps/api/tests/test_players_fastpath.py` (NEW):

```python
"""v0.9.4 plan 015: player routes fast-path direct query."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gw2analytics_api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_list_players_returns_same_data_as_pre_plan_015(seeded_data):
    """Regression: the new fast-path returns the same /players response."""
    # Seed 3 fights + 2 accounts (cross-fight rollup).
    # Compare against the pre-plan-015 reference response.


def test_get_player_returns_same_data_as_pre_plan_015(seeded_data):
    """Regression: the per-account profile is identical to the pre-plan output."""


def test_get_player_timeline_started_at_correctly_joined(seeded_data):
    """The timeline's started_at is correctly JOINed from OrmFight (not default epoch)."""


def test_fastpath_wallclock_under_100ms_for_1000_fights(seeded_data):
    """1000 fights seeded; /players wallclock < 100 ms (was ~500 ms)."""
```

---

## Verification commands

```bash
uv run ruff check apps/api
uv run ruff format --check apps/api
uv run mypy --no-incremental libs apps
uv run pytest apps/api/tests/test_players_fastpath.py -v
uv run pytest apps/api/tests/test_players.py -v  # existing 7 tests still pass
uv run pytest apps/api/tests/test_uploads_e2e.py -v  # the player-timeline e2e tests stay green
```

A worktree `git diff` against `44ea862` must show ONLY:
- `apps/api/src/gw2analytics_api/routes/players.py` (refactor `_compute_contributions` + 3 route handlers + delete 3 orphan helpers).
- `apps/api/tests/test_players_fastpath.py` (NEW, 4 tests).
- `CONTRIBUTING.md` (1 short subsection).

---

## Maintenance note

- The fast-path drops the pre-v0.8.4 fallback for non-summary fights. For dev environments with pre-v0.8.4 test data, the route returns empty contributions (no error). Production is all post-v0.8.4 since the v0.8.4 + v0.8.5 backfill cycle closed (per the v0.8.4 / v0.8.5 / v0.8.6 CHANGELOG entries).
- The JOIN uses the PK index on `fights.id` (the FK target of `fight_player_summaries.fight_id`). For 10k fights × N accounts per fight, the JOIN cost is O(N log N) — small per row.
- The `PlayerProfileAggregator` (cross-fight rollup, profession filter) still runs in Python. A future v0.9.5 plan could push those to SQL too (a 2nd `GROUP BY account_name` query).
- The `fight_id_to_started` dict returned alongside the contributions saves the 3 routes from re-querying `OrmFight` for `started_at` (the JOIN already loaded it).

## Escape hatches

- If a production deployment has a mix of v0.8.4 and pre-v0.8.4 fights and the fast-path is too aggressive, restore the hybrid via a 2-line change (the existing `_fast_path_fight_ids` helper is kept in the file under `if False:` for 1 cycle before final deletion).
- If a future plan needs pre-v0.8.4 fight data, re-add the blob-walk fallback as a `not _has_summary_rows_for(fights)` branch.
- If the JOIN becomes the bottleneck (unlikely — 10k rows is well within Postgres' indexed JOIN budget), add a covering index on `fight_player_summaries (fight_id) INCLUDE (account_name, ...)` to make the JOIN an index-only scan.
- If the `OrmFightPlayerSummary` table grows past 1M rows, the `ORDER BY` may need to become a hybrid: pre-filter by `account_name` for the detail endpoints, full-sort only for the list endpoint.
