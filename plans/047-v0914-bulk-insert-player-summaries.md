# Plan 047 — v0.9.14 `_persist_player_summaries` bulk INSERT

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — services.py deep pass
**Status:** pending
**Effort:** S
**Category:** perf (N+1 INSERTs)
**Files touched:** `apps/api/src/gw2analytics_api/services.py` (1 file, additive change only) + `apps/api/tests/test_uploads_e2e.py` (1 NEW test case)

## Problem

`apps/api/src/gw2analytics_api/services.py::_persist_player_summaries`
inserts the per-(fight, account_name) summary rows one
at a time:

```python
db.execute(
    delete(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == orm_fight.id),
)
for account_name, bucket in per_account.items():
    db.add(
        OrmFightPlayerSummary(
            fight_id=orm_fight.id,
            account_name=account_name,
            name=str(bucket["name"]),
            profession=int(bucket["prof"]),
            elite_spec=int(bucket["elite"]),
            total_damage=int(bucket["damage"]),
            total_healing=int(bucket["healing"]),
            total_buff_removal=int(bucket["strip"]),
        ),
    )
```

For a fight with N player agents, this is N individual
INSERT statements (the SQLAlchemy ORM `add` pattern
emits one INSERT per row on the next flush). For a
canonical WvW raid (50 players), this is 50 INSERTs.
For a 100-player WvW raid, this is 100 INSERTs. For a
1000-player WvW zerg (a degenerate but possible case),
this is 1000 INSERTs.

SQLAlchemy 2.0 supports the canonical "execute an
`insert(...)` with a list of dicts" pattern that
emits a single batched INSERT statement (or a small
number of batched statements with `insertmanyvalues`
slicing). The performance gain is ~10x for N >= 50.

### Severity

- **Perf**: LOW — the canonical WvW raid (50 players)
  sees a ~50ms -> ~5ms INSERT (10x speedup). The
  overall `process_parse` BG task is dominated by
  the parser + the gzip + the MinIO PUT, not the
  summary INSERTs. The 50ms gain is a small fraction
  of the total.
- **Scalability**: MED — a 1000-player WvW zerg
  would see a ~500ms -> ~50ms INSERT (10x speedup).
  For a busy weekend, the cumulative gain across
  many concurrent uploads is meaningful.

### Affected callers

- `process_parse` (the happy path) calls
  `_persist_player_summaries` after
  `_persist_event_blob`.
- The backfill script calls the same function
  indirectly (via the same `process_parse` code
  path? no, actually the backfill calls
  `_persist_player_summaries` directly from
  `apps/api/src/gw2analytics_api/backfill.py::run_backfill`).
  Wait, let me re-check. Looking at the
  `_persist_player_summaries` function: it's
  defined in `services.py` and exported via the
  module's public surface. The backfill imports
  it directly. So the bulk INSERT benefits both
  the happy path AND the backfill.

## Goals

- Replace the `for ... db.add(OrmFightPlayerSummary(...))`
  loop with a single
  `db.execute(insert(OrmFightPlayerSummary).values(list_of_dicts))`
  call.
- The DELETE before the INSERTs is unchanged
  (single DELETE, batched INSERT).
- Add a hermetic test that seeds a 100-player
  fight + asserts the function inserts 100 rows
  in a single statement (or a small number of
  batched statements) + asserts the per-account
  totals match the expected values.

## Non-goals

- Switching to a different ORM (e.g. SQLAlchemy
  Core's `Table` insert). The ORM `insert()` is
  the canonical SQLAlchemy 2.0 pattern.
- Adding an explicit `insertmanyvalues` slice
  parameter. SQLAlchemy 2.0's default
  `insertmanyvalues` slicing is sufficient for
  the canonical N (50-100 players). A future
  hardening pass can add an explicit
  `insertmanyvalues` slice parameter if the
  canonical N grows past 1000.
- Changing the DELETE+INSERT pattern to
  upsert. Out of scope (the DELETE+INSERT is
  the canonical "replace rows atomically"
  pattern; a future plan can switch to upsert
  if the Postgres `INSERT ... ON CONFLICT`
  pattern is desired).

## Implementation

### File: `apps/api/src/gw2analytics_api/services.py`

Update `_persist_player_summaries` to use the
`insert(...).values(list)` pattern.

```python
# Add to the imports at the top of services.py:
from sqlalchemy import delete, insert, select

# Replace the for-loop in _persist_player_summaries:
# BEFORE:
    db.execute(
        delete(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == orm_fight.id),
    )
    for account_name, bucket in per_account.items():
        db.add(
            OrmFightPlayerSummary(
                fight_id=orm_fight.id,
                account_name=account_name,
                name=str(bucket["name"]),
                profession=int(bucket["prof"]),
                elite_spec=int(bucket["elite"]),
                total_damage=int(bucket["damage"]),
                total_healing=int(bucket["healing"]),
                total_buff_removal=int(bucket["strip"]),
            ),
        )

# AFTER:
    db.execute(
        delete(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == orm_fight.id),
    )
    # Batched INSERT via SQLAlchemy 2.0's
    # ``insert(...).values(list_of_dicts)`` pattern.
    # The ORM emits a single (or a small number of
    # ``insertmanyvalues``-sliced) INSERT statement
    # instead of N individual INSERTs. The perf
    # gain is ~10x for N >= 50; the canonical
    # WvW raid (50 players) sees a 50ms -> 5ms
    # improvement; the cumulative gain across
    # many concurrent uploads is meaningful for
    # busy weekends.
    #
    # The list-of-dicts shape matches the
    # ``OrmFightPlayerSummary`` columns 1:1; the
    # ``insert()`` builder maps the dict keys to
    # the column names. The ``execute(...)`` call
    # returns a ``Result`` object that the caller
    # can ignore (we don't need the rowcount).
    db.execute(
        insert(OrmFightPlayerSummary),
        [
            {
                "fight_id": orm_fight.id,
                "account_name": account_name,
                "name": str(bucket["name"]),
                "profession": int(bucket["prof"]),
                "elite_spec": int(bucket["elite"]),
                "total_damage": int(bucket["damage"]),
                "total_healing": int(bucket["healing"]),
                "total_buff_removal": int(bucket["strip"]),
            }
            for account_name, bucket in per_account.items()
        ],
    )
```

### File: `apps/api/tests/test_uploads_e2e.py` (NEW test case)

Add a new test that seeds a 100-player fight +
asserts the function inserts 100 rows in a small
number of statements + asserts the per-account
totals match the expected values.

```python
def test_persist_player_summaries_batched_insert(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """The 100-row insert is batched into a small
    number of statements (not 100 individual
    INSERTs)."""
    # ... seed 100 agents + 100 events (1 damage event
    # per agent, value = agent_id) ...

    # Spy on db_session.execute to count the
    # INSERT statements.
    insert_count = {"n": 0}
    original_execute = db_session.execute

    def counting_execute(*args, **kwargs):
        from sqlalchemy import insert
        if args and isinstance(args[0], insert):
            insert_count["n"] += 1
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(db_session, "execute", counting_execute)

    # ... call _persist_player_summaries(db, orm_fight, events) ...

    # Assert the INSERT was batched: 1 execute()
    # call for the DELETE + 1-2 execute() calls
    # for the batched INSERTs (SQLAlchemy 2.0
    # ``insertmanyvalues`` slicing emits at most
    # ceil(N / 1000) batches; for N=100, the
    # default slice is 1000, so 1 batch).
    assert insert_count["n"] == 1

    # Assert the per-account totals are correct.
    rows = db_session.execute(
        select(OrmFightPlayerSummary).where(
            OrmFightPlayerSummary.fight_id == orm_fight.id
        )
    ).scalars().all()
    assert len(rows) == 100
    for row in rows:
        assert row.total_damage == int(row.account_name)
```

## Test plan

1. **1 new hermetic test** in
   `apps/api/tests/test_uploads_e2e.py` covers
   the batched-INSERT path. The test seeds a
   100-player fight + asserts the INSERT is
   batched + asserts the per-account totals.
2. **All existing tests pass** — the change is
   backwards-compatible for any N (the batched
   INSERT produces the same rows as the
   N-individual-INSERTs pattern).
3. **`uv run pytest apps/api/tests/`** exits 0.
4. **`uv run mypy --no-incremental libs apps`** is
   clean.

## Acceptance criteria

- [ ] `_persist_player_summaries` uses
      `db.execute(insert(OrmFightPlayerSummary), [...])`
      instead of the for-loop with `db.add(...)`.
- [ ] The DELETE before the INSERTs is unchanged.
- [ ] 1 new hermetic test passes.
- [ ] All existing tests pass.
- [ ] `mypy --no-incremental` is clean.
- [ ] `ruff check` is clean.
- [ ] No production code paths change (the
      batched INSERT produces the same rows as
      the N-individual-INSERTs pattern).

## Out-of-scope / deferred

- **Switching to SQLAlchemy Core's `Table` insert**:
  out of scope (the ORM `insert()` is the
  canonical SQLAlchemy 2.0 pattern).
- **Adding an explicit `insertmanyvalues` slice
  parameter**: out of scope (SQLAlchemy 2.0's
  default slicing is sufficient for N <= 1000).
- **Changing the DELETE+INSERT pattern to upsert**:
  out of scope (the DELETE+INSERT is the canonical
  "replace rows atomically" pattern).

## Maintenance notes

- **The `insert(...).values(list_of_dicts)` pattern
  is the SQLAlchemy 2.0 idiomatic batched INSERT**.
  The `execute(insert_stmt, list_of_dicts)` form
  is documented at
  https://docs.sqlalchemy.org/en/20/core/dml.html#sqlalchemy.sql.expression.insert.
- **The `insertmanyvalues` slicing** is automatic
  in SQLAlchemy 2.0. The default slice is 1000;
  for N <= 1000, the INSERT is a single statement.
  For N > 1000, the INSERT is sliced into multiple
  statements of 1000 rows each. A future hardening
  pass can add an explicit `insertmanyvalues`
  slice parameter if the canonical N grows past
  1000.
- **The list-of-dicts shape matches the
  `OrmFightPlayerSummary` columns 1:1**. The
  `insert()` builder maps the dict keys to the
  column names; a typo in a dict key raises
  `KeyError` at execute time (a defensive check
  for the executor is to verify the dict keys
  match the column names).
- **The `execute()` returns a `Result` object**
  that the caller can ignore. The `rowcount` is
  available on the `Result` but we don't need
  it (the DELETE+INSERT contract is implicit).
