"""Strip leading colon from account_name columns.

Revision ID: 0014_strip_account_colon
Revises: 0013_drift_cleanup
Create Date: 2026-07-14 00:00:00

Why this migration exists
=========================
The EVTC parser surfaces player account names with a leading
``:`` (e.g. ``:synth.123``) to mirror the arcdps binary format.
The API persistence layer now stores the bare form
(``synth.123``) so that routes, tests, and cross-fight joins
use the canonical value without defensive ``lstrip(":")``
workarounds. This migration normalises any existing rows that
still carry the parser-side prefix.

Affected tables
---------------
- ``fight_agents.account_name`` (nullable)
- ``fight_player_summaries.account_name`` (part of composite PK)

Idempotency
-----------
Both UPDATE statements use ``WHERE account_name LIKE ':%'`` so
re-running the migration is a no-op once all prefixes are
stripped.

Downgrade
=========
Downgrade is intentionally unsupported. Re-adding the ``:``
prefix would require knowing whether each value originally came
from the EVTC parser (which warrants the prefix) or from a
manual insert (which does not). The persistence layer now
normalises on write, so the bare form is the canonical state.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_strip_account_colon"
down_revision: str | None = "0013_drift_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Strip a single leading ':' from account_name values. The
    # parser emits exactly one ':' prefix; SUBSTRING(... FROM 2)
    # removes only that first character (unlike LTRIM which
    # would strip every leading ':').
    #
    # Duplicate-PK guard: the EVTC parser guarantees that a single
    # fight never contains both ':name' and 'name' for the same
    # agent, so stripping the prefix cannot create a duplicate
    # (fight_id, account_name) composite key. If manual DB edits
    # have introduced such a collision, Postgres will raise a
    # unique-constraint violation and the operator must dedupe
    # before retrying.
    op.execute(
        "UPDATE fight_agents SET account_name = SUBSTRING(account_name FROM 2) "
        "WHERE account_name LIKE ':%';"
    )
    op.execute(
        "UPDATE fight_player_summaries SET account_name = SUBSTRING(account_name FROM 2) "
        "WHERE account_name LIKE ':%';"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrading 0014_strip_account_colon is intentionally "
        "not supported: re-adding the ':' prefix is not reliably reversible "
        "without knowing the original source of each account_name value."
    )
