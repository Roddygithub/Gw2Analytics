#!/usr/bin/env python3
"""SECRETS_KEK rotation script (plan 015).

Re-encrypts all webhook subscription ciphertext rows from the OLD KEK
to the NEW KEK. Run AFTER setting SECRETS_KEK=<new> and
SECRETS_KEK_OLD=<old> in the environment.

Usage:
    SECRETS_KEK_OLD=<old-kek> SECRETS_KEK=<new-kek> \
        uv run python apps/api/scripts/rotate_kek.py

The script:
1. Connects to Postgres via SQLAlchemy (sync session).
2. SELECTs every row in webhook_subscriptions with ciphertext IS NOT NULL.
3. For each row: decrypts with OLD KEK -> re-encrypts with NEW KEK.
4. Prints an audit JSON line per row (newline-delimited for log aggregators).
5. Prints a summary line with rotated/failed counts.

After the migration completes, remove SECRETS_KEK_OLD and
SECRETS_KEK_FALLBACK from .env (decommissioning the OLD KEK).
"""

from __future__ import annotations

import json
import os
import sys

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from gw2analytics_api.models import OrmWebhookSubscription


def _get_fernet(kek: str) -> Fernet:
    """Create a Fernet instance from a KEK string."""
    return Fernet(kek.encode("ascii"))


def _load_settings() -> tuple[str, str, str]:
    """Load required env vars. Fail fast if missing."""
    old_kek = os.environ.get("SECRETS_KEK_OLD", "")
    new_kek = os.environ.get("SECRETS_KEK", "")
    database_url = os.environ.get("DATABASE_URL", "")

    errors: list[str] = []
    if not old_kek:
        errors.append("SECRETS_KEK_OLD is required (the current KEK to rotate FROM)")
    if not new_kek:
        errors.append("SECRETS_KEK is required (the new KEK to rotate TO)")
    if not database_url:
        errors.append("DATABASE_URL is required")

    if errors:
        for e in errors:
            print(json.dumps({"error": e}), file=sys.stderr)
        sys.exit(1)

    return old_kek, new_kek, database_url


def rotate_kek() -> int:
    """Main rotation logic. Returns 0 on success, 1 on failure."""
    old_kek, new_kek, database_url = _load_settings()

    # Validate KEKs are different
    if old_kek == new_kek:
        error_msg = "SECRETS_KEK_OLD and SECRETS_KEK are identical; nothing to rotate"
        print(json.dumps({"error": error_msg}), file=sys.stderr)
        return 1

    old_fernet = _get_fernet(old_kek)
    new_fernet = _get_fernet(new_kek)

    engine = create_engine(database_url)
    session_factory_local = sessionmaker(bind=engine)

    rotated_count = 0
    failed_count = 0

    with session_factory_local() as session:
        rows = (
            session.execute(
                select(OrmWebhookSubscription).where(OrmWebhookSubscription.ciphertext.isnot(None))
            )
            .scalars()
            .all()
        )

        total = len(rows)
        print(json.dumps({"status": "started", "total_rows": total}), file=sys.stderr)

        for sub in rows:
            try:
                # Decrypt with OLD KEK
                plaintext = old_fernet.decrypt(sub.ciphertext).decode("utf-8")
                # Re-encrypt with NEW KEK
                sub.ciphertext = new_fernet.encrypt(plaintext.encode("utf-8"))
                session.commit()
                rotated_count += 1
                audit_line = {"subscription_id": sub.id, "status": "rotated"}
                print(json.dumps(audit_line))
            except Exception as exc:
                session.rollback()
                failed_count += 1
                audit_line = {
                    "subscription_id": sub.id,
                    "status": "decrypt_failed",
                    "error": str(exc),
                }
                print(json.dumps(audit_line))

    engine.dispose()

    summary = {"status": "done", "rotated_count": rotated_count, "failed_count": failed_count}
    print(json.dumps(summary), file=sys.stderr)

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(rotate_kek())
