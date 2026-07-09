"""v0.10.0 plan 031: webhook secret at rest envelope encryption (Fernet; CWE-256 closure).

Revision ID: 0009_webhook_secret_at_rest
Revises: 0008_payload_bytes
Create Date: 2026-07-09

Why
----
Pre-v0.10.0: ``OrmWebhookSubscription.secret`` is a plaintext VARCHAR(64)
column. A stolen DB snapshot OR a flawed SELECT-leak surfaces the
plaintext HMAC secret directly, which lets an attacker forge
``X-Gw2Analytics-Signature: sha256=...`` headers against every
registered subscriber. The classification is CWE-256 (plaintext
storage of a password) -- relevant because integrators treat the
``whsec_<base64>`` secret as a long-lived bearer token.

Post-v0.10.0: ``secret`` column is replaced with ``ciphertext`` of
type ``LargeBinary`` holding the Fernet envelope
(``Fernet(key).encrypt(plaintext.encode("utf-8"))``). The KEK
(key encryption key) is held in the ``SECRETS_KEK`` environment
variable; a stolen DB snapshot is NOT enough to forge signatures --
the attacker must ALSO have access to the gateway process
environment.

NOTE: pgcrypto was REJECTED for this implementation despite being a
natural-looking choice; see ``apps/api/.env.example`` and the
design rationale below.

Design rationale (pgcrypto REJECTED)
-----------------------------------
Post-v0.10.0 plan 031 design review: ``pgp_sym_encrypt`` from
Postgres' ``pgcrypto`` extension was the natural-looking choice
but it has a critical defect: the KEK is a SQL parameter, so the
plaintext KEK crosses the wire every time ``encrypt_webhook_secret``
or ``decrypt_webhook_secret`` fires. Postgres' default
``log_statement='none'`` masks this for non-error cases but a
verbose ``log_min_duration_statement`` configuration + a SQL-level
``pg_stat_statements`` view would leak the KEK. Defense-in-depth
requires the KEK to stay inside the Python process memory.
Python's ``cryptography.fernet.Fernet`` provides the same envelope
without the SQL wire hazard.

Encryption contract
-------------------
- Ciphertext column type: ``LargeBinary`` (raw bytes).
- Plaintext encoding: ``utf-8`` (whsec_<base64> is already ASCII).
- Key format: 32 random bytes, URL-safe base64 encoded = exactly
  44 characters. Fernet's serializer wraps the
  AES-128-CBC + HMAC-SHA256 envelope so the ciphertext is
  timestamped + versioned (default TTL 0 = no expiry).
- KEK validation: ``apps/api/Settings.secrets_kek`` field
  validator (length-exactly-44 check) fails-fast at app startup,
  so a missing OR malformed KEK surfaces BEFORE the first webhook
  is created (no silent fallback to plaintext).
- KEK source: ``SECRETS_KEK`` environment variable (loaded via
  pydantic-settings; ``SecretStr`` field type so the value is
  masked in tracebacks / repr / debug logs).
- Generate new KEK:
  ``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``

WARNING: data loss risk
-----------------------
The KEK is the SOLE decryption key. If ``SECRETS_KEK`` is lost
or rotated without running a rotation migration, ALL existing
webhook subscriptions will PERMANENTLY fail to dispatch. HMAC
signatures will be silently wrong on every POST
(``cryptography.fernet.InvalidToken`` caught and logged but never
recovered). Operators MUST:

1. Store the KEK in a secrets manager (Vault / AWS Secrets Manager /
   sealed-secrets / etc.). DO NOT commit to git.
2. Test KEK recovery BEFORE relying on the encryption layer
   (e.g., ``Fernet(kek).decrypt(ciphertext_bytes)`` on a known row).
3. Route future KEK rotations through a v0.10.0+ dedicated
   rotation script that re-encrypts every ``ciphertext`` row in
   place (out of scope for plan 031).

Data migration
--------------
The migration is data-affecting. ``downgrade`` requires the SAME
``SECRETS_KEK`` used during ``upgrade``; a rollback without the
KEK produces ``InvalidToken`` exceptions mid-rollback (the
alembic exception path will surface them).

Migration execution contract:
  $ SECRETS_KEK=... uv run alembic upgrade head
  $ SECRETS_KEK=... uv run alembic downgrade -1

The migration encapsulates the KEK via ``os.environ['SECRETS_KEK']``
so the same env-with-KEK convention works for both alembic
invocations AND the running app (single source of truth).

Worker contract
---------------
``webhook_dispatch._dispatch_single`` now decrypts the secret
ON-DEMAND per subscription (Python-side Fernet; ~2us overhead
per decrypt vs ~50ms HTTP POST per delivery, so the latency
ceiling is unchanged). One corrupt ``ciphertext`` row (manual
DB edit OR KEK-rotation-without-migration) raises
``cryptography.fernet.InvalidToken``; the worker CATCHES this
exception per-sub, logs the failure, and CONTINUES the loop for
all other subscribers (one bad row MUST NOT crash the dispatch
loop -- that would silently freeze every other webhook).
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet

revision: str = "0009_webhook_secret_at_rest"
down_revision: str | None = "0008_payload_bytes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _kek() -> str:
    """Read ``SECRETS_KEK`` from :data:`os.environ` with a clear error.

    The migration is a SINGLE source of truth on the KEK; both
    ``upgrade`` and ``downgrade`` resolve the KEK the same way
    so an operator running an alembic roundtrip with a NEW
    :file:`.env` lands a consistent state.
    """
    kek = os.environ.get("SECRETS_KEK")
    if not kek:
        raise RuntimeError(
            "SECRETS_KEK env var is required to run migration 0009. "
            "Generate via `python -c \"from cryptography.fernet import "
            "Fernet; print(Fernet.generate_key().decode())\"` and store "
            "in a secrets manager; NEVER commit to git."
        )
    return kek


def upgrade() -> None:
    # 1. Add the ciphertext column with NOT NULL + server default
    #    ``''::bytea`` so the existing rows can be migrated in
    #    place without a CHECK constraint violation. The
    #    ``''::bytea`` cast is required because raw ``bytes``
    #    are not accepted as ``server_default`` by SQLAlchemy
    #    (``sqlalchemy.exc.ArgumentError``); the explicit cast
    #    delegates the literal-to-bytea conversion to Postgres.
    op.add_column(
        "webhook_subscriptions",
        sa.Column(
            "ciphertext",
            sa.LargeBinary(),
            nullable=False,
            server_default=sa.text("''::bytea"),
        ),
    )
    # 2. Data migration: Fernet-encrypt every existing plaintext
    #    secret (Python-side encryption; the KEK never crosses
    #    the SQL wire per the design rationale in the file
    #    docstring).
    kek = _kek()
    fernet = Fernet(kek.encode("ascii"))
    conn = op.get_bind()
    # Explicit ``''::bytea`` cast on the comparison side too:
    # Postgres can compare bytea to text via an implicit cast,
    # but the explicit cast locks in the contracts so the
    # migration is immune to future ``server_default`` /
    # ``standard_conforming_strings`` drift.
    sel = sa.text(
        "SELECT id, secret FROM webhook_subscriptions "
        "WHERE ciphertext = ''::bytea AND secret IS NOT NULL AND secret != ''"
    )
    upd = sa.text(
        "UPDATE webhook_subscriptions SET ciphertext = :ciphertext WHERE id = :id"
    )
    rows = conn.execute(sel).fetchall()
    for row_id, plaintext in rows:
        # Defensive: the SELECT filters ``secret IS NOT NULL AND
        # secret != ''`` but a manual DB edit OR a partial prior
        # migration could leave a NULL or non-string value in
        # the column. Skipping is cheaper than aborting the
        # whole migration mid-batch (which would leave half the
        # rows encrypted and the rest plaintext on disk).
        if plaintext is None or not isinstance(plaintext, str):
            continue
        encrypted = fernet.encrypt(plaintext.encode("utf-8"))
        conn.execute(upd, {"ciphertext": encrypted, "id": row_id})
    # 3. Drop the now-stale plaintext column. The replacement is
    #    atomic at the SQL level (no in-between state where
    #    some rows have ``secret`` and some have ``ciphertext``).
    op.drop_column("webhook_subscriptions", "secret")
    # 4. Drop the server_default so a future INSERT cannot
    #    silently land with an empty ``ciphertext`` (the type
    #    layer would otherwise accept ``''::bytea`` and the
    #    Fernet-decrypt path would raise ``InvalidToken`` on
    #    the next dispatch). The route handler ALWAYS writes a
    #    Fernet envelope on insert, so the default is purely a
    #    backfill helper -- once backfill is complete, the
    #    schema should reject any direct INSERT that omits an
    #    explicit ciphertext value.
    op.alter_column(
        "webhook_subscriptions", "ciphertext", server_default=None,
    )


def downgrade() -> None:
    # 1. Re-add the plaintext ``secret`` column with empty default
    #    so the backfill via the KEK has somewhere to write the
    #    restored value.
    op.add_column(
        "webhook_subscriptions",
        sa.Column(
            "secret",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    # 2. Restore the plaintext from each ciphertext via the SAME
    #    KEK. Without the KEK this raises
    #    ``cryptography.fernet.InvalidToken`` which alembic
    #    surfaces as a migration-level exception -- the rollback
    #    aborts rather than silently winding plaintext.
    kek = _kek()
    fernet = Fernet(kek.encode("ascii"))
    conn = op.get_bind()
    sel = sa.text(
        "SELECT id, ciphertext FROM webhook_subscriptions "
        "WHERE secret = '' AND ciphertext IS NOT NULL AND ciphertext != ''"
    )
    upd = sa.text(
        "UPDATE webhook_subscriptions SET secret = :plaintext WHERE id = :id"
    )
    rows = conn.execute(sel).fetchall()
    for row_id, ciphertext in rows:
        # Mirror the upgrade defensive check: skip non-bytes
        # rows (manual DB edit OR partial prior migration)
        # rather than abort the downgrade mid-batch.
        if not isinstance(ciphertext, (bytes, bytearray, memoryview)):
            continue
        plaintext = fernet.decrypt(bytes(ciphertext)).decode("utf-8")
        conn.execute(upd, {"plaintext": plaintext, "id": row_id})
    op.drop_column("webhook_subscriptions", "ciphertext")
    # Drop the server_default so the schema rejects future
    # INSERTs that omit a ``secret`` value (the type layer
    # would otherwise accept ``''`` and the route's HMAC
    # signing path would silently sign with an empty key).
    op.alter_column(
        "webhook_subscriptions", "secret", server_default=None,
    )
