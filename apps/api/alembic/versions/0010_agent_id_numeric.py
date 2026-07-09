"""v0.10.2 hotfix: fight_agents.agent_id BIGINT → NUMERIC(20,0) for arcdps unsigned 64-bit IDs

Revision ID: 0010_agent_id_numeric
Revises: 0009_webhook_secret_at_rest
Create Date: 2026-07-09

Why
---
arcdps EVTC parser emits ``agent_id`` as a **uint64** (0 .. 2^64 - 1).
The original v0.5 schema declared ``agent_id`` as ``BIGINT`` (Postgres
signed 64-bit, max 2^63 - 1 = 9,223,372,036,854,775,807). WvW logs
routinely contain agents (turrets, siege engines, some players) with
``agent_id >= 2^63`` (~1.84e19), which overflows ``BIGINT`` and raises
``psycopg.errors.NumericValueOutOfRange: bigint out of range`` on the
INSERT into ``fight_agents``.

Pre-v0.10.2, the error was hidden by BackgroundTasks (silent crash in
the same process). v0.10.1's Arq worker surfaces the error cleanly in
``/tmp/arq.log`` and 8/8 parallel uploads got stuck on
``status="pending"`` indefinitely (re-test on 2026-07-09 with 8
``.zevtc`` files > 1 MB: 0/8 reached ``completed``).

Post-v0.10.2: ``agent_id`` is ``NUMERIC(20, 0)`` which holds the full
uint64 range (max 2^64 - 1 = 18,446,744,073,709,551,615, fits in 20
digits). The PK composite ``(fight_id, agent_id)`` is rebuilt
automatically by the ``ALTER COLUMN TYPE``; Postgres handles the
index rebuild transparently (the PK index is dropped + recreated in
the same DDL transaction).

Why NUMERIC(20, 0) and not NUMERIC(38, 0) (the Postgres max)?
- 20 digits is the smallest precision that holds 2^64 - 1
  (19.3 digits) without rounding.
- 38 digits would be 2x the index size for no benefit (no arcdps
  value will ever exceed uint64).
- 20 digits keeps the B-tree index compact (~12 bytes/row for the
  NUMERIC vs 8 bytes for BIGINT — acceptable trade-off for the
  correctness win).

Why not (b) check constraint ``agent_id < 2^63``?
- It would reject every WvW log with a turret/siege/player in the
  upper uint64 range. Defeats the purpose; the parser would crash
  on the same rows it crashes on today.

Why not (d) sentinel ``-1`` for overflow?
- The PK is composite ``(fight_id, agent_id)``. WvW fights often
  have 3-5 agents with overflow IDs (e.g. all 5 siege engines in
  a keep defense). Collapsing them to a single ``-1`` would crash
  on the second INSERT (``IntegrityError: duplicate key``).

Data loss
---------
None on upgrade. Postgres upcasts ``BIGINT`` → ``NUMERIC(20, 0)``
losslessly for every value in ``[0, 2^63 - 1]`` (the existing range,
which is every value that could have been inserted pre-migration —
values > 2^63 were UNABLE to be inserted).

Downgrade is NOT lossless: ``ALTER COLUMN ... TYPE BIGINT`` raises
``NUMERIC VALUE OUT OF RANGE`` for any row with ``agent_id >= 2^63``.
The downgrade is therefore best-effort and may require a manual
drain first.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_agent_id_numeric"
down_revision: str | None = "0009_webhook_secret_at_rest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The PK index ``pk_fight_agents`` (on (fight_id, agent_id)) is
    # rebuilt automatically by ALTER COLUMN TYPE; no explicit DROP
    # INDEX / CREATE INDEX needed. Postgres takes an ACCESS EXCLUSIVE
    # lock on ``fight_agents`` for the duration of the ALTER (a few
    # seconds in practice for the dataset size). The 3 fight_agents
    # indexes (``pk_fight_agents`` plus any future secondary indexes
    # on agent_id) are rebuilt in the same transaction.
    op.alter_column(
        "fight_agents",
        "agent_id",
        existing_type=sa.BigInteger(),
        type_=sa.Numeric(20, 0),
        existing_nullable=False,
        # The USING clause is REQUIRED for BIGINT → NUMERIC; without
        # it, Postgres refuses the cast (the type families are
        # distinct). The cast is value-preserving for every input
        # in the BIGINT range.
        postgresql_using="agent_id::numeric(20,0)",
    )


def downgrade() -> None:
    # NOT lossless: rows with agent_id >= 2^63 will fail the
    # downcast with ``NUMERIC VALUE OUT OF RANGE``. Operators
    # downgrading must drain the offending rows first (manual
    # DELETE; see the v0.10.2 CHANGELOG entry's "Downgrade
    # safety" section).
    op.alter_column(
        "fight_agents",
        "agent_id",
        existing_type=sa.Numeric(20, 0),
        type_=sa.BigInteger(),
        existing_nullable=False,
        postgresql_using="agent_id::bigint",
    )
