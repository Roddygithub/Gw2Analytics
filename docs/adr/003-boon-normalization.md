# ADR 003 — Boon Normalization

- **Status:** Proposed
- **Date:** 2026-07-24
- **Phase:** 3.1

## Context

``OrmFightPlayerSummary`` has 28 individual columns for boon uptimes
(``might_uptime``, ``fury_uptime``, …) and outgoing boon applications
(``outgoing_might``, ``outgoing_fury``, …). Adding a new tracked boon
requires a schema migration + model change + service update.

## Decision

Replace the 28 columns with a normalized ``fight_player_boons`` table
that stores one row per ``(fight_id, account_name, boon_name)`` triple:

```sql
CREATE TABLE fight_player_boons (
    fight_id      VARCHAR(64) NOT NULL REFERENCES fights(id),
    account_name  VARCHAR(128) NOT NULL,
    boon_name     VARCHAR(30) NOT NULL,    -- 'might', 'fury', etc.
    uptime        FLOAT,                   -- NULLable
    outgoing      BIGINT,                  -- NULLable
    PRIMARY KEY (fight_id, account_name, boon_name)
);
```

## Consequences

- **Positive:** Adding a new boon requires no schema migration — just
  a constant update.
- **Positive:** Storage is sparse — a player with 3 active boons
  produces 3 rows instead of 1 row with 25 NULL columns.
- **Positive:** Querying "all players with >50% alacrity uptime" is
  a simple ``WHERE boon_name='alacrity' AND uptime > 0.5``.
- **Negative:** Reading per-player boons requires a JOIN instead of
  a column projection.
- **Negative:** Migration from the old schema requires a data backfill.

## Migration Strategy

1. Create ``fight_player_boons`` table.
2. Backfill data from ``OrmFightPlayerSummary`` columns.
3. Dual-write for one release cycle (write to both old columns and
   new table).
4. Remove old columns in a follow-up release.
