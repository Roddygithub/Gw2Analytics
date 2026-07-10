# Plan 005 — Alembic structural drift (RUN COMPLETE, DRIFT FOUND)

**Date**: 2026-07-10
**Audit base**: `84138d0` (post-v0.10.3 close-out)
**Scope**: detect drift between the ORM models in `apps/api/src/gw2analytics_api/models.py` and the Alembic migration versions in `apps/api/alembic/versions/`.

## Status: RUN COMPLETE — DRIFT DETECTED (12 items)

The `alembic check` command returned exit 255 with the canonical
``New upgrade operations detected.`` failure. The drift detector
(package the project's CI uses) found 12 items needing a migration
to bring the DB into lockstep with the v2 model surface. The earlier
"manual diff" conclusion is **incorrect** — the manual review looked
only at column-level ``add_column`` / ``create_table`` ops, not at
the index/constraint changes alembic autogenerate detects. This
document has been rewritten on 2026-07-10 to reflect the live result.

## Procedure that worked

```bash
# 1. psycopg2 is NOT installed in the project's venv (confirmed --
#    only psycopg v3 is). Use the explicit ``postgresql+psycopg://``
#    URL prefix so SQLAlchemy routes the connection through the
#    installed driver.
#
# 2. Port 5432 is occupied on the host by an OLD container named
#    ``wvw-postgres`` (from a different project). Use ``5433:5432`` in
#    docker-compose.yml to avoid the bind collision. The postgres
#    container itself still listens on 5432 INSIDE the container --
#    only the host-side port mapping needs to shift.
#
# 3. Bring the container up + wait for the healthcheck to land on green.
docker compose down --remove-orphans
docker compose up -d postgres
# wait ~9s for `pg_isready -U gw2analytics` to flip healthy
echo

# 4. Generate a Fernet key + pin DATABASE_URL + run migrations.
cd apps/api
export FK=$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
export SECRETS_KEK="$FK"
export DATABASE_URL='postgresql+psycopg://gw2analytics:gw2analytics@localhost:5433/gw2analytics'
SECRETS_KEK="$FK" DATABASE_URL="$DATABASE_URL" uv run alembic upgrade head
# -- passes; 0012_check_constraints migration applied (last in history)

# 5. Run alembic check (the structural drift detector).
SECRETS_KEK="$FK" DATABASE_URL="$DATABASE_URL" uv run alembic check
# -- exit 255; emits "New upgrade operations detected: [...]"
```

## Drift items (12 total) — see advisor-plans/006 for the fix

The categorical breakdown of the detected drift (full text in the
``alembic check`` output, abbreviated here for navigation):

**A. Index removals (10 items)** — the v2 ORM models dropped several
indexes that the v0.10.3+ migrations created. Either the ORM-side
``__table_args__`` lists were edited without a corresponding migration,
OR the migration added the indexes but the model side removed the
``Column(..., index=True)`` flags without a follow-up ``op.drop_index``.
Affected tables: `fight_player_summaries`, `fight_skills`,
`webhook_deliveries`, `webhook_dlq`, `webhook_subscriptions`.

1. `ix_fight_player_summaries_account_fight` on `fight_player_summaries` (composite PK)
2. `ix_fight_skills_fight_id` on `fight_skills` (composite PK)
3. `ix_uploads_sha256` (was non-unique, the **ORM now declares it unique**)
4. `ix_webhook_deliveries_delivered_at`
5. `ix_webhook_deliveries_subscription_id`
6. `ix_webhook_deliveries_upload_id`
7. `ix_webhook_dlq_moved_to_dlq_at`
8. `ix_webhook_dlq_subscription_id`
9. `ix_webhook_subscriptions_revoked_at`

**B. Constraint changes (1 item)**

10. `uploads.sha256`: ORM now declares ``unique=True``; migration
    currently leaves the column without a UNIQUE constraint. This is
    a behavioral change (re-uploading the same SHA now hits a
    constraint rather than the application-layer ``ON CONFLICT``).

**C. Type modification (1 item)**

11. `webhook_subscriptions.filter`: ORM column type drifted from
    `JSONB(astext_type=Text())` to `JSON()`. The Postgres value type
    is binary-compatible for read but ``JSONB`` has different index
    semantics (`GIN` works only on `JSONB`). Federal feature flag:
    anyone with a webhooks subscription filter relying on JSONB
    GIN-index lookup will silently lose that path.

## Classification

| Item | Severity | Owner | Recoverability |
|------|---------|-------|----------------|
| 1-9 (index drops) | LOW | lib maintainer | automatic via empty 0013_migration |
| 10 (uploads.sha256 unique flip) | MEDIUM | lib maintainer | requires ATTENTION if prod data has duplicate SHAs |
| 11 (filter JSONB → JSON) | MEDIUM | lib maintainer | requires review of webhook subscription filter consumers |

## Next step

The drift items are forwarded to :file:`advisor-plans/006-alembic-drift-fix.md`
which scopes a single migration (``0013_drift_cleanup``) to bring the
schema back into lockstep with the v2 ORM. Pre-flight procedure to
avoid surprise: drop + recreate the dev DB (``docker compose down -v``)
to start from a clean slate before applying ``0013_drift_cleanup``.

## Fallback (no Postgres locally)

For purely offline introspection, the equivalent check is:

```bash
uv run python -c "
import sys
sys.path.insert(0, 'apps/api/src')
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers
from gw2analytics_api.models import Base
configure_mappers()
engine = create_engine('postgresql://stub')
migrations_table = sorted([(t.name, sorted([(c.name, str(c.type), c.nullable) for c in t.columns])) for t in Base.metadata.sorted_tables])
for name, cols in migrations_table:
    print(name)
    for c in cols:
        print('  ', c)
"
```

Cross-reference against ``grep -hE 'op.create_table|op.create_index|op.add_column|op.alter_column' apps/api/alembic/versions/*.py``
manually.
