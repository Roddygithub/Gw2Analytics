"""v0.10.3 plan 083: add detected_role + detected_tags columns to fight_player_summaries.

Revision ID: 0011_player_role_detection
Revises: 0010_agent_id_numeric
Create Date: 2026-07-09

Why
---
The v0.10.3 plan 083 ports the heuristic role-detection from
an upstream reference parser (``(non-public reference).py``) into
Gw2Analytics. The an upstream reference parser algorithm consumes a ``PlayerStats``
ORM with 80+ fields (DPS, healing out, barrier, strips, cleanses,
boon uptimes, ...). Gw2Analytics's ``OrmFightPlayerSummary`` only
tracks the 3 magnitudes (``total_damage`` / ``total_healing`` /
``total_buff_removal``), so the FULL algorithm cannot run 1:1.

The v1 lite port (``libs/gw2_analytics/role_detection.py``) uses
ONLY the 3 magnitudes + ``profession`` (int) + ``elite_spec`` (int)
+ the spec/profession hint tables ported verbatim from
an upstream reference parser. The output is ``(detected_role, detected_tags)``:

- ``detected_role``: a single string (e.g. ``"DPS"`` / ``"HEAL"`` /
  ``"STRIP"`` / ``"BOON"`` / ``"MIXED"`` / ``"UNKNOWN"``). Stored
  in ``String(30)`` -- the upper bound covers every role name
  + a generous future-proofing margin (``"MIXED"`` is 5 chars, so
  30 is 6x the longest current name).
- ``detected_tags``: a list of strings (e.g. ``["high_dps"]``,
  ``["off_meta"]``, ``["foreign_badges:HEAL"]``). Stored as a
  Postgres ``JSON`` column (not ``ARRAY(String)``) so the list
  shape is flexible without an Alembic type change on every
  future tag addition.

Data loss on upgrade
--------------------
None. Both columns are ``nullable=True`` with no ``default`` --
existing rows land with ``detected_role = NULL`` /
``detected_tags = NULL``. The frontend treats ``NULL`` as
"unknown" (the pre-migration semantic). The v0.10.3 ingestion
path populates both columns for every new fight; a v0.10.3+
backfill (out of scope for this migration) can re-process
existing fights to populate the columns without re-parsing the
EVTC (the 3 magnitudes are already on the row, so the heuristic
can run on the materialised table directly).

Why ``detected_tags`` is JSON and not ``ARRAY(String)``
-------------------------------------------------------
- an upstream reference parser uses ``ARRAY(String)`` for ``detected_tags``.
  The list shape is open-ended (e.g. ``"foreign_badges:HEAL"``
  embeds a role name in the tag value); future tag additions
  would require a schema migration.
- JSON keeps the list shape flexible (a future
  ``"boon_strip_efficiency:0.85"`` numeric tag fits without a
  migration; only the application-side decoder needs updating).
- The trade-off is a per-row JSONB parse cost on read. The
  player routes already JOIN the table; a single
  ``jsonb_array_elements_text`` GIN index on the column would
  accelerate tag-based filters, but no current route filters
  by tag. The trade-off is acceptable for v0.10.3 (v0.11 can
  add the GIN index if tag-based filtering lands).

Why no backfill
---------------
The migration is purely additive. A backfill would require
re-running the heuristic on every existing
``OrmFightPlayerSummary`` row, which is a non-trivial CPU
cost (the heuristic is pure Python; 1k rows = ~100ms on a
modern CPU; 10k rows = ~1s; the v0.10.3 production dataset
is in the low thousands so the cost is acceptable but
NOT in scope for this migration). The ``_persist_player_summaries``
helper populates both columns for every new fight; a followup
v0.10.3 backfill can be added later if the operator needs
the data on pre-existing rows.

Forward contract for the 2 columns
----------------------------------
- **Pre-migration rows** (uploaded before the v0.10.3
  deployment): ``detected_role IS NULL`` and
  ``detected_tags IS NULL``. The route layer treats
  ``NULL`` as "unknown" (the pre-migration semantic) --
  the frontend can show a generic "N/A" badge.
- **Post-migration rows** (uploaded after the v0.10.3
  deployment): ``detected_role`` is a non-NULL string
  (DPS / HEAL / STRIP / BOON / MIXED / UNKNOWN) and
  ``detected_tags`` is a non-NULL JSON list (possibly
  empty ``[]`` for the UNKNOWN case). The
  ``_persist_player_summaries`` helper populates both
  fields on every INSERT; the heuristic never returns
  ``None`` for the role. The asymmetry (pre-migration =
  NULL, post-migration = concrete values) is the canonical
  "additive migration" contract -- ``nullable=True`` on
  the column lets the pre-migration rows land without
  a backfill.
"""  # noqa: E501

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_player_role_detection"
down_revision: str | None = "0010_agent_id_numeric"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``detected_role``: the primary role. ``String(30)`` covers
    # every current role name (longest = ``"UNKNOWN"`` = 7 chars)
    # with a generous margin for future role additions.
    op.add_column(
        "fight_player_summaries",
        sa.Column(
            "detected_role",
            sa.String(length=30),
            nullable=True,
        ),
    )
    # ``detected_tags``: open-ended list of downstream-UX signals.
    # JSON (not ARRAY(String)) for forward-compat with future
    # structured tag values (e.g. ``"boon_strip_efficiency:0.85"``).
    # ``nullable=True`` matches the forward contract documented
    # in the module docstring (pre-migration rows = NULL,
    # post-migration rows = concrete values; the
    # ``_persist_player_summaries`` helper populates both
    # fields on every INSERT for new fights).
    op.add_column(
        "fight_player_summaries",
        sa.Column(
            "detected_tags",
            sa.JSON(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("fight_player_summaries", "detected_tags")
    op.drop_column("fight_player_summaries", "detected_role")
