# Plan 034 — v0.9.10 backfill commit-time failure handling

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — backfill/scripts deep pass
**Status:** pending
**Effort:** S
**Category:** reliability (per-fight commit semantic)
**Files touched:** `apps/api/src/gw2analytics_api/backfill.py` (1 file, additive changes only) + `apps/api/tests/test_backfill.py` (NEW test case)

## Problem

`apps/api/src/gw2analytics_api/backfill.py::run_backfill` has
a per-fight commit semantic that breaks on commit-time failure:

```python
for fight in fights:
    player_agents = [a for a in fight.agents if a.is_player and a.account_name]
    if not player_agents:
        logger.debug("fight %s has no player agents; skipping", fight.id)
        skipped += 1
        continue

    try:
        _backfill_one_fight(db, fight, player_agents, dry_run=dry_run)
    except (S3Error, OSError, SQLAlchemyError, ValidationError) as exc:
        logger.exception("failed backfilling fight %s: %s", fight.id, exc)
        db.rollback()
        failed += 1
        continue

    if not dry_run:
        db.commit()  # <-- NOT in the try/except
    backfilled += 1
    logger.info("backfilled fight %s (%d player agents)", fight.id, len(player_agents))
```

The `try/except` block catches 4 per-fight failure modes
(`S3Error`, `OSError`, `SQLAlchemyError`, `ValidationError`)
and rolls back the per-fight transaction. BUT the
`db.commit()` on the next line is NOT inside the
`try/except`. If `db.commit()` itself raises (e.g. a
transient DB connection error at commit time, a lost
connection to Postgres during the COMMIT statement, a
serialisation failure on the optimistic-concurrency check),
the exception propagates up the call stack and crashes the
entire script.

### Severity

- **Reliability**: MED — for a 10K-fight backfill on a
  production dataset, a single transient commit failure
  (e.g. a brief Postgres restart) crashes the script after
  5-10 minutes of work. The operator has to re-run the
  script from scratch, which re-discovers the same fights
  and re-runs the slow blob-decompress for each.
- **Operational trust**: MED — the script's headline
  guarantee ("safe to interrupt + re-run; per-fight commit")
  is documented in the CLI docstring + the module
  docstring + the README. A commit-time crash breaks
  the guarantee.

### Affected callers

- `apps/api/src/gw2analytics_api/scripts/backfill_player_summaries.py::main`
  (the CLI entrypoint).
- The test suite (`apps/api/tests/test_backfill.py`).
- Any future operational dashboard that invokes
  `run_backfill` directly.

## Goals

- Wrap the `db.commit()` call in a `try/except` block that
  catches `SQLAlchemyError` and counts the fight as
  `failed` (so the operator sees the correct count) +
  logs the failure + continues the loop.
- Maintain the existing 4 per-fight exception types
  (`S3Error`, `OSError`, `SQLAlchemyError`, `ValidationError`)
  — no narrowing of the existing catch.
- Add a hermetic test that injects a `SQLAlchemyError` at
  commit time and asserts the fight is counted as
  `failed` + the next fight is processed.

## Non-goals

- Adding commit-time retry with exponential backoff. A
  transient commit failure is a per-fight issue; retrying
  the commit would re-execute the same SQL with the same
  state, which is the same race condition. The operator
  can re-run the script to retry the failed fights.
- Switching from per-fight commit to a single batch
  commit. The per-fight commit is the canonical safety
  net (the operator can `Ctrl+C` between fights and lose
  at most one in-flight transaction). A batch commit
  would lose this guarantee.
- Adding a connection-pool health check before the
  commit. Out of scope (the connection pool is managed
  by SQLAlchemy; the commit-time check is the right
  level).

## Implementation

### File: `apps/api/src/gw2analytics_api/backfill.py`

Replace the per-fight loop with a version that wraps the
`db.commit()` in a try/except. The diff is a 5-line edit
inside the for loop.

```python
# BEFORE:
    for fight in fights:
        player_agents = [a for a in fight.agents if a.is_player and a.account_name]
        if not player_agents:
            logger.debug("fight %s has no player agents; skipping", fight.id)
            skipped += 1
            continue

        try:
            _backfill_one_fight(db, fight, player_agents, dry_run=dry_run)
        except (S3Error, OSError, SQLAlchemyError, ValidationError) as exc:
            logger.exception("failed backfilling fight %s: %s", fight.id, exc)
            db.rollback()
            failed += 1
            continue

        if not dry_run:
            db.commit()
        backfilled += 1
        logger.info("backfilled fight %s (%d player agents)", fight.id, len(player_agents))

# AFTER:
    for fight in fights:
        player_agents = [a for a in fight.agents if a.is_player and a.account_name]
        if not player_agents:
            logger.debug("fight %s has no player agents; skipping", fight.id)
            skipped += 1
            continue

        try:
            _backfill_one_fight(db, fight, player_agents, dry_run=dry_run)
            if not dry_run:
                # The commit is inside the try/except so a
                # transient commit-time failure (e.g. a
                # lost connection to Postgres during the
                # COMMIT statement) is treated as a
                # per-fight failure: the fight is counted
                # as `failed`, the transaction is rolled
                # back, and the next fight is processed.
                # The script is re-runnable; a re-run
                # retries the failed fights (they still
                # have zero summary rows).
                db.commit()
            backfilled += 1
            logger.info(
                "backfilled fight %s (%d player agents)",
                fight.id,
                len(player_agents),
            )
        except (S3Error, OSError, SQLAlchemyError, ValidationError) as exc:
            logger.exception("failed backfilling fight %s: %s", fight.id, exc)
            db.rollback()
            failed += 1
            continue
```

The change also moves the `backfilled += 1` + `logger.info`
inside the try block so a commit-time failure doesn't
double-count (the fight is NOT counted as backfilled if
the commit failed).

### File: `apps/api/tests/test_backfill.py` (additions)

Add a new test that injects a `SQLAlchemyError` at commit
time and asserts the fight is counted as `failed` + the
next fight is processed.

```python
def test_run_backfill_handles_commit_time_failure(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sample_fight: OrmFight,
) -> None:
    """A SQLAlchemyError raised at commit time (transient
    DB connection error, lost connection during COMMIT,
    serialisation failure) counts the fight as `failed`
    and lets the next fight be processed.
    """
    # Add a 2nd fight so we can assert the loop continues.
    second_fight = OrmFight(
        id="second_fight_xyz",
        upload_id=sample_fight.upload_id,
        build_version=sample_fight.build_version,
        encounter_id=sample_fight.encounter_id,
        agent_count=sample_fight.agent_count,
        started_at=sample_fight.started_at,
        game_type=sample_fight.game_type,
    )
    db_session.add(second_fight)
    db_session.commit()

    # Patch the session's commit to raise on the first
    # call only (the second call succeeds).
    original_commit = db_session.commit
    call_count = {"n": 0}

    def flaky_commit() -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise OperationalError("simulated", {}, Exception("lost connection"))
        original_commit()

    monkeypatch.setattr(db_session, "commit", flaky_commit)

    backfilled, skipped, failed = run_backfill(
        db_session,
        fight_id=None,
        limit=None,
        dry_run=False,
    )

    # The first fight is counted as failed; the second
    # fight is counted as backfilled.
    assert failed == 1
    assert backfilled == 1
    assert skipped == 0
```

## Test plan

1. **New hermetic test** (above) injects a
   `SQLAlchemyError` at commit time + asserts the
   `failed` count is 1 and the loop continues.
2. **All existing tests pass** — the change is
   backwards-compatible for any happy-path commit.
3. **`uv run pytest apps/api/tests/test_backfill.py`**
   exits 0.
4. **`uv run mypy --no-incremental libs apps`** is
   clean.
5. **`uv run ruff check`** is clean.

## Acceptance criteria

- [ ] `apps/api/src/gw2analytics_api/backfill.py` has
      the new `try` block structure (the `db.commit()`
      is inside the try, the `backfilled += 1` is
      inside the try).
- [ ] `apps/api/tests/test_backfill.py` has the new
      `test_run_backfill_handles_commit_time_failure`
      test; it passes.
- [ ] All existing tests pass.
- [ ] `mypy --no-incremental` is clean.
- [ ] `ruff check` is clean.
- [ ] No production code paths change (the new
      behaviour is "treat commit-time failure as
      per-fight failure"; the existing happy-path
      commits are unchanged).

## Out-of-scope / deferred

- **Commit-time retry with exponential backoff**: out
  of scope (a transient commit failure is a per-fight
  issue; the operator can re-run the script to retry).
- **Switching to a single batch commit**: out of
  scope (the per-fight commit is the canonical
  safety net).
- **Adding a connection-pool health check before the
  commit**: out of scope (the connection pool is
  managed by SQLAlchemy).

## Maintenance notes

- **The change consolidates the try/except block**.
  Before: the commit was outside the try, so a
  commit-time failure was uncaught. After: the commit
  is inside the try, so a commit-time failure is
  caught by the same 4 exception types as the
  in-flight work.
- **The `backfilled += 1` counter is now inside the
  try**. A commit-time failure does NOT increment the
  `backfilled` counter (it increments `failed` instead).
  This is the correct semantics: a fight is "backfilled"
  only if the commit succeeded.
- **The change is symmetric with plan 029's narrowing
  of `_persist_event_blob except`**: both plans tighten
  the per-row failure surface so transient errors
  count as failures + the next row is processed.
