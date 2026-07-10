# Plan 005 — Alembic structural drift (RESULT)

**Date**: 2026-07-10
**Audit base**: `84138d0` (post-v0.10.3 close-out)
**Scope**: detect drift between the ORM models in `apps/api/src/gw2analytics_api/models.py` and the Alembic migration versions in `apps/api/alembic/versions/`.

## Status: blocked on local-infra only; project-CI already gates this

The dry-run could not complete in the executor's local environment because
the dev Postgres container is partially broken (created-then-not-running
state, password-auth mismatch for user `gw2analytics`). A short re-run
is enough to close the loop in a properly-configured dev env, and the
project's own CI (`make ci` → `pytest apps/api` after
`docker compose up postgres -d && alembic upgrade head`) already gates
on `alembic check` upstream of any push.

## Procedure to close in a working env

```bash
# 1. Apply the latest schema.
cd apps/api
SECRETS_KEK=$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null || \
              python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())') \
  uv run alembic upgrade head
echo

# 2. Compare ORM models to migration history (the structural-drift detector).
SECRETS_KEK="$SECRETS_KEK" uv run alembic check
# Expected stdout: ``No new upgrade operations detected.`` if no drift.

# 3. Auto-generate an ephemeral revision WITHOUT committing it. This is
#    the canonical offline-style dry-run: the only durable artifact is
#    the diff text captured in /tmp.
SECRETS_KEK="$SECRETS_KEK" uv run alembic revision --autogenerate -m drift_inspect 2>&1 | tee /tmp/drift_inspect.txt
# Inspect, then either:
#   (a) rm apps/api/alembic/versions/*drift_inspect.py   [no drift]
#   (b) promote to real revisions/00XX_*.py if drift is real.
```

## Fallback (no Postgres locally)

For purely offline introspection, run ``uv run python -c "import sys;
sys.path.insert(0, 'apps/api/src'); from gw2analytics_api.models import
*; print(sorted([t.name for t in Base.metadata.sorted_tables]))"`` and
compare to ``grep -h 'op.create_table' apps/api/alembic/versions/*.py``
manually.

## Re-investigation outcome (qualified -- dry-run not completed in executor env)

The dry-run itself could not complete in the executor's local dev
environment (see "Status" above), so the conclusion below is the
result of a MANUAL diff between the v2 ORM models and the migration
history -- NOT a live ``alembic check`` / ``alembic revision
--autogenerate`` measurement. The CI env does gate this with
``alembic check`` upstream of any push; locally, run the procedure
in the next section to close the gap.

Manual diff outcome:
 - ``OrmFightPlayerSummary.detected_role`` + ``OrmFightPlayerSummary.detected_tags`` -- both covered by ``0011_player_role_detection`` (the v0.10.3 close-out migration).
 - ``OrmFightPlayerSummary.total_*`` magnitudes -- BY-DESIGN: introduced in v0.8.4 as the fast-path table; correctly referenced by the role-detection backfill path.

NO DRIFT DETECTED at the manual diff layer; a live ``alembic check`` is
required to confirm zero drift across the full surface (the section
"Procedure to close in a working env" above documents the exact
3-command sequence).
