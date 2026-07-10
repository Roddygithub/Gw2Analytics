# Plan 006 — Alembic drift fix migration (0013_drift_cleanup)

**Date**: 2026-07-10
**Drift base**: `01f59f0` (post-F1 followup)
**Status**: SCOPE-ONLY stub — full implementation lives in the next cycle
**Source of items**: advisor-plans/005 drift detection (live `alembic check` run)

F1 followup ran `alembic check` against a fresh Postgres 16 instance
and got `exit 255` + `New upgrade operations detected:` with 12
items. This plan scopes the single migration that brings the schema
back into lockstep with the v2 ORM (``0013_drift_cleanup``).

## The 12 detected items (copy-pasted from advisor-plans/005)

### A. Index removals (10 items)

The v2 ORM models dropped several indexes that the v0.10.3+ migrations
created. Either the ORM-side `__table_args__` lists were edited
without a corresponding migration, OR the migration added the indexes
but the model side removed the `Column(..., index=True)` flags
without a follow-up `op.drop_index`. Affected tables:

1. `ix_fight_player_summaries_account_fight` on `fight_player_summaries` (composite PK)
2. `ix_fight_skills_fight_id` on `fight_skills` (composite PK)
3. `ix_uploads_sha256` (was non-unique; ORM now declares it unique)
4. `ix_webhook_deliveries_delivered_at`
5. `ix_webhook_deliveries_subscription_id`
6. `ix_webhook_deliveries_upload_id`
7. `ix_webhook_dlq_moved_to_dlq_at`
8. `ix_webhook_dlq_subscription_id`
9. `ix_webhook_subscriptions_revoked_at`

### B. Constraint changes (1 item)

10. `uploads.sha256`: ORM declares `unique=True`; migration leaves
    the column without a UNIQUE constraint. Behavioural change
    (re-uploading the same SHA now hits a constraint rather than the
    application-layer `ON CONFLICT`).

### C. Type modification (1 item)

11. `webhook_subscriptions.filter`: ORM column type drifted from
    `JSONB(astext_type=Text())` to `JSON()`. The Postgres value type
    is binary-compatible for read but `JSONB` has different index
    semantics (`GIN` works only on `JSONB`). Anyone with webhooks
    subscription filter relying on JSONB GIN-index lookup will
    silently lose that path.

## Proposed 0013 migration skeleton

A single migration that:

1. Drops the 9 stale indexes (A.1-9 above) in dependency-safe order.
2. Drops the existing `ix_uploads_sha256` non-unique index, then
   drops the `uploads.sha256` UniqueConstraint as a side-effect of
   the column-decl drift, then recreates a UNIQUE index on
   `uploads.sha256` matching the ORM's new declaration
   (B.10). If the dev DB has duplicate SHA rows at the time of the
   migration, the UNIQUE re-creation will fail -- the migration
   pre-flight `SELECT sha256, COUNT(*) FROM uploads GROUP BY sha256
   HAVING COUNT(*) > 1` should be added and the script should `raise`
   if any duplicates exist.
3. The `webhook_subscriptions.filter` type change (C.11) is the
   highest-risk item. Two options:
    (a) `ALTER TABLE webhook_subscriptions ALTER COLUMN filter TYPE
        JSON USING filter::JSON` (loses GIN-index-ability for any
        existing data, requires `DROP INDEX IF EXISTS
        ix_webhook_subscriptions_filter_jsonb_gin` if present).
    (b) Revert the ORM column to `JSONB` (preserves GIN semantics;
        matches the migration history).
   Recommendation: **(b)** is the conservative call -- the migration
   history is correct, the ORM drifted. Add a 1-line code comment in
   `apps/api/src/gw2analytics_api/models.py` near the `filter`
   column definition pointing back at this plan.

## Pre-flight cleaning

Before applying 0013 in dev:

```bash
docker compose down --remove-orphans       # free port 5433 (or 5432)
docker compose up -d postgres              # fresh container
SECRETS_KEK=$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
SECRETS_KEK="$SECRETS_KEK" DATABASE_URL='postgresql+psycopg://gw2analytics:gw2analytics@localhost:5433/gw2analytics' \
  uv run --project apps/api alembic upgrade 0012_check_constraints
```

After 0013 lands, re-run `alembic check` to verify ``No new upgrade
operations detected.`` and commit.

## Sub-finding: condi_portion_getter callback is leaky

Tangential drift to the alembic work: the new ``F3 condi/power
split`` exposes a ``Callable[[DamageEvent], int]`` parameter
(``condi_portion_getter``) that closes over the parser's
``buff_dmg`` side-table. The plan 135 explicitly excludes touching
``libs/gw2_evtc_parser/``, so the callback is the pragmatic escape
hatch -- but it leaks parser internals into the lib's public
surface. Three alternatives to evaluate for a future cycle:

(a) Extend ``DamageEvent`` with an optional ``buff_dmg: int | None =
    None`` (requires lifting ``frozen=True``).
(b) Parser emits a dedicated ``CondiDamageEvent`` discriminated
    union member (touches parser + Event union -- the bigger lift).
(c) Ship the callback long-term + document the parser-internal
    coupling at the type signature; deprecate once a real fix
    lands.

Recommendation: track this as a separate plan (``006a-condi-shape``)
rather than coupling it to the alembic drift fix.
