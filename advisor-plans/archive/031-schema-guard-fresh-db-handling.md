# Plan 031 — v0.10.10: `schema_guard.check_schema_drift` must catch `UndefinedTable` on a fresh DB (graceful startup before migrations)

**Stamped at:** `f0249ef` (working-tree diff HEAD; all changes in this plan live in the uncommitted working tree)
**Severity:** LOW-MED (dx — fresh deployment crashes Uvicorn with a confusing traceback before migrations have run)
**Category:** dx
**Addresses finding:** `apps/api/src/gw2analytics_api/schema_guard.py:104` executes `db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()`. If the DB is **fresh** (e.g. a brand-new docker-compose stack boots the API container before running migrations — a common pattern in Helm-charts and Compose's `depends_on: condition: service_healthy`), the `alembic_version` table does NOT exist; psycopg raises `psycopg.errors.UndefinedTable: relation "alembic_version" does not exist`. The drift guard crashes Uvicorn with an opaque SQL stacktrace. The author's comments (`schema_guard.py:96-100`) explicitly say: *"The helper does NOT catch the SQLAlchemy exception on step 3; a Postgres outage at startup is a different operational concern (the sessionmaker itself will fail at first use) and should NOT be masked behind a 'schema drift' error message."* — but a MISSING `alembic_version` TABLE is the canonical "migrations never ran" signal, NOT a Postgres outage, and the current contract silently turns it into a confusing psycopg crash.

---

## Finding

Evidence (current working-tree source):

```python
# apps/api/src/gw2analytics_api/schema_guard.py:100-110
cfg.set_main_option(...)  # (post plan 030 fix)
head = ScriptDirectory.from_config(cfg).get_current_head()
with get_sessionmaker()() as db:
    actual = db.execute(
        text("SELECT version_num FROM alembic_version"),
    ).scalar_one_or_none()
if actual != head:
    msg = (
        f"Schema drift detected: database is at {actual!r}, "
        ...
    )
    raise RuntimeError(msg)
```

### Three distinct startup states

1. **DB reachable, alembic_version table exists, version row matches head → OK** (the canonical happy path).
2. **DB reachable, alembic_version table exists, version row mismatches head → RuntimeError** (the canonical v0.10.1 plan 010 contract).
3. **DB reachable, alembic_version table EXISTS but row is NULL → RuntimeError** (`actual is None`; existing test `test_drift_when_db_alembic_version_row_missing` covers this).
4. **DB reachable, alembic_version table DOES NOT EXIST** (the missing-state plan 031 covers) → `psycopg.errors.UndefinedTable` propagates from the `text(...)` query, NO RuntimeError; Uvicorn dies with the raw psycopg traceback.

Case 4 ≠ case 3 yet both surface as "drift detected" to the operator in their head. The fix is to dose-state #4 into a friendlier RuntimeError that surfaces the same "did you run migrations?" diagnosis as case 3.

---

## Fix

### Step 1 — Catch the `UndefinedTable` exception and route to a friendly RuntimeError

In `apps/api/src/gw2analytics_api/schema_guard.py`, wrap the `db.execute(...)` block in a narrow `try`/`except`:

```python
from sqlalchemy.exc import ProgrammingError  # parent class for any DBAPI's "relation does not exist" (psycopg's `UndefinedTable`, SQLite's `OperationalError`, asyncpg's `UndefinedTableError`). Single import covers all drivers.
```

Add to the body of `check_schema_drift`:

```python
try:
    actual = db.execute(
        text("SELECT version_num FROM alembic_version"),
    ).scalar_one_or_none()
except ProgrammingError as exc:
    # v0.10.10 plan 031: the canonical "fresh DB before migrations"
    # case. The SQL targets ONLY the ``alembic_version`` table, so
    # any ``ProgrammingError`` (parent class for every DBAPI driver's
    # "relation does not exist": psycopg's ``UndefinedTable``,
    # SQLite's ``OperationalError``, asyncpg's ``UndefinedTableError``)
    # indicates the table is missing. Pre-fix, the raw
    # ``psycopg.errors.UndefinedTable: relation "alembic_version"
    # does not exist`` surfaced as a confusing traceback that
    # operators misread as a Postgres outage. Post-fix, the
    # operator sees the same actionable RuntimeError as case 3
    # (NULL version row), with a hint pointing at the migration
    # command.
    #
    # NOTE: avoid ``from psycopg.errors import UndefinedTable`` —
    # ``psycopg`` is not a top-level dependency in pyproject.toml
    # (the canonical SQLAlchemy pattern pulls it via ``sqlalchemy[binary]``
    # extras). A bare top-level ``import`` would fail with
    # ``ModuleNotFoundError`` in dev/test envs that don't activate
    # the extras. ``ProgrammingError`` IS the SQLAlchemy umbrella
    # for ALL DBAPI "missing relation" errors.
    logger.info(
        "schema drift check: alembic_version table missing — operators should "
        "run `alembic upgrade head` before the API"
    )
    raise RuntimeError(
        f"Schema drift detected: alembic_version table missing. "
        f"Did you forget to run `alembic upgrade head`? "
        f"(Set SKIP_SCHEMA_GUARD=1 to bypass in emergencies.)"
    ) from exc
```

### Step 2 — Keep the existing case 3 contract intact

The existing test `test_drift_when_db_alembic_version_row_missing` asserts `actual is None` → RuntimeError with `"None"` + `"Schema drift detected"`. This case is for the table-EXISTS-but-NULL-row state. Post-fix, the same `actual is None` check stays; the new branch fires only on `UndefinedTable`.

### Step 3 — Document the canonical message format

The fix surfaces a RuntimeError with the substring "alembic_version table missing" — adjacent to the existing "Schema drift detected" prefix. Both helper-runbook greps continue to work:

```bash
grep -E 'Schema drift detected' /tmp/fastapi.log
grep -E 'alembic_version table missing' /tmp/fastapi.log
```

The maintainer's operational runbook mentions `SKIP_SCHEMA_GUARD=1` in both the original error message AND the new one (intentional: same escape hatch, same hint).

---

## Tests

### Test file 1 — NEW `apps/api/tests/test_schema_guard_fresh_db.py`

Pattern reference: `apps/api/tests/test_schema_guard.py` (existing hermetic schema-guard tests).

4 hermetic tests using `monkeypatch` + `unittest.mock.patch` to simulate the `UndefinedTable` exception:

1. `test_undefined_table_raises_runtime_error_with_actionable_hint` — patch `db.execute(text(...))` to raise `sqlalchemy.exc.ProgrammingError("relation \"alembic_version\" does not exist", params=None, orig=Exception("..."))`. Assert the post-fix code raises `RuntimeError` (NOT `ProgrammingError`); the RuntimeError msg contains the substrings `"alembic_version table missing"` AND `"alembic upgrade head"` AND `"SKIP_SCHEMA_GUARD"`. **Avoid** raising `psycopg.errors.UndefinedTable` directly in the test — psycopg is not a direct test dep.

2. `test_programming_error_with_other_relation_message_still_routes_correctly` — patch `db.execute(text(...))` to raise `sqlalchemy.exc.ProgrammingError("relation \"some_other_table\" does not exist")`. Asserts that the broad `ProgrammingError` catch fires regardless of the specific relation-name (the SQL query targets `alembic_version` named in the literal; any `ProgrammingError` on it is the missing-table case). Tests the "broad catch is acceptable" argument from the docstring rationale.

3. `test_non_related_programming_error_does_not_route_to_runtime_error` — patch `db.execute(text(...))` to raise `sqlalchemy.exc.ProgrammingError("syntax error at or near 'VERSION'")` (intentional: simulates a future bug where the SQL query has a typo — NOT a missing-relation error). Assert `ProgrammingError` STILL propagates (the catch is for "relation N does not exist" only; syntax errors must surface loudly). The discrimination is by exception TYPE (`ProgrammingError` is parent for BOTH syntax errors AND missing relations); if the executor narrows the catch, they must check the message.

4. `test_routing_rationale_covers_all_dbadp_drivers` — a documentation-style test: assert that the catch block is `sqlalchemy.exc.ProgrammingError` (NOT `psycopg.errors.UndefinedTable` nor any DBAPI-specific class). The test reads the source and asserts the import + the except tuple. Pins the multi-driver operand rationale (any DBAPI's "relation does not exist" surfaces as SQLAlchemy's `ProgrammingError`).

### Test file 2 — EXTEND `apps/api/tests/test_schema_guard.py`

Add 1 regression test:

`test_alembic_version_missing_diagnoses_actionably` — explicitly use `pytest.raises(RuntimeError, match="alembic upgrade head")` so a future executor who reverts to the broad `except Exception` style is caught by the existing test infrastructure. Pin the actionable hint.

---

## Out of scope

- Auto-running migrations from the schema-guard helper (the helper's job is to detect drift, not to fix it). The operator's runbook continues to be `uv run alembic upgrade head` from inside `apps/api/`.
- Changing the v0.10.1 plan 010 contract for the "in-table, NULL row" case (already covered by `test_drift_when_db_alembic_version_row_missing`; this plan does NOT change that path).
- Migrating the alembic_version query to use `inspect()` from SQLAlchemy 2.0 (more idiomatic; out of scope: the canonical `text("SELECT ...")` is the v0.10.1 contract).
- A startup-retry mechanism (e.g. retry up to N times before giving up) — out of scope: the helper is fail-fast by design; operators using `depends_on: condition: service_healthy` already get the correct ordering.

---

## Done criteria

Run from repo root after the fix is applied:

```bash
# 1. Ruff is clean.
uv run ruff check apps/api/

# 2. mypy --strict tolerates the new imports (`psycopg.errors.UndefinedTable`, `sqlalchemy.exc.ProgrammingError`).
uv run mypy libs apps --no-incremental

# 3. Both new/extended test files pass.
uv run pytest apps/api/tests/test_schema_guard_fresh_db.py -v
uv run pytest apps/api/tests/test_schema_guard.py -v

# 4. The full apps/api tests stay green (no regression on the legacy drift cases).
uv run pytest apps/api/tests/ -q

# 5. The legacy "Programmer-facing `UndefinedTable` propagation" is gone.
grep -nE 'UndefinedTable' apps/api/src/gw2analytics_api/schema_guard.py
# Expected output: 1 match in the `except (ProgrammingError, UndefinedTable)` clause + the import line.
# NOT: any `db.execute(...).UndefinedTable` propagation chain (the bare psycopg traceback).
```

---

## Maintenance note

- The fix relies on `psycopg` being importable at module load. If a future SQLAlchemy refactor switches driver (e.g. to `asyncpg`), the `UndefinedTable` import must be updated to the new driver's equivalent (`asyncpg.UndefinedTableError`). The `sqlalchemy.exc.ProgrammingError` catch is the **defence in depth** fallback.
- The error message wording is grep-stable per the existing convention: `"Schema drift detected"` + `"alembic_version table missing"`. The repo's runbook grep `grep -E 'Schema drift detected' /tmp/fastapi.log` continues to match.
- Combining plans 030 + 031 in the same PR is encouraged (both touch `schema_guard.py`; one atomic commit can be reviewed holistically). If the maintainer prefers two PRs, each plan's tests are independent so order is not load-bearing.

---

## Escape hatches

- **Driver surface changes in the future (e.g. asyncpg becomes available only via extras)?** The `ProgrammingError` catch is the canonical SQLAlchemy umbrella. If a future SQLAlchemy version introduces a more specific subclass for "missing relation" (e.g. `MissingRelationError`), narrow the catch to that subclass. The test `test_non_related_programming_error_does_not_route_to_runtime_error` continues to pass because syntax errors propagate from any parent class.
- **The fix surfaces a RuntimeError for a *legitimate* Postgres outage (table-was-just-created mid-call)?** The `UndefinedTable` race is narrow (only fires on the literal `relation "alembic_version" does not exist`); a Postgres outage fires other errors (`OperationalError`, `InterfaceError`) which are NOT in the `except` tuple. No false-positive on outages.
- **Operator wants the bare traceback for forensic debugging?** Set `SKIP_SCHEMA_GUARD=1`. The original traceback won't surface (the bypass short-circuits before the SQL query), but the operator can flip the bypass off for one boot to inspect. Out of scope as a permanent mode.

---

## Dependency graph

- **Independent.** Touches only `apps/api/src/gw2analytics_api/schema_guard.py` + 1 NEW test file + 1 EXTENDED test file. No plan depends on this one; this plan doesn't depend on any.

## Cross-references

- Plan 010 (v0.10.1) — the original schema-drift guard (which introduced the SQL query). This plan closes a UX defect in the helper's failure mode.
- Plan 030 (v0.10.10) — sibling plan (closes the CWD-resolution defect). Both plans touch `schema_guard.py` for the same line range; ship together for review efficiency.
