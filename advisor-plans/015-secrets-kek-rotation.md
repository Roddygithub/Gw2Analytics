# advisor-plan 015 — SECRETS_KEK rotation migration (envelope re-encrypt)

## Problem

Webhook secrets are encrypted under a single Fernet KEK (`SECRETS_KEK` env var). The KEK is the SOLE decryption key — losing it = all webhook subscriptions permanently fail to dispatch. The operator must be able to rotate the KEK (compliance: GDPR right-to-rotation on secrets, OWASP A02:2021 Cryptographic Failures, team org-change handshake). No documented rotation migration exists today (`apps/api/.env.example:32-41` flags it as a planned future v0.10.0+ migration; no concrete plan). `apps/api/alembic/versions/0009_webhook_secret_at_rest.py:62-75` documents the same data-loss risk.

## Context

- `apps/api/src/gw2analytics_api/crypto.py:1-145` — verified. The `encrypt_webhook_secret(plaintext, *, kek)` and `decrypt_webhook_secret(ciphertext, *, kek)` helpers accept an explicit `kek=` parameter but it is never set externally (the cache KEK from env is used).
- `apps/api/alembic/versions/0009_webhook_secret_at_rest.py` — the migration that introduced the Fernet envelope; the KEK is referenced as the SOLE decryption key.
- `apps/api/src/gw2analytics_api/routes/webhooks.py:232` — on creation, `ciphertext=encrypt_webhook_secret(plaintext_secret)` (uses the cache KEK).
- `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py:200-220` — decrypts on every delivery with `FernetInvalidToken` graceful handling.

## Approach

Two-pronged migration:
1. **Read path**: extend `decrypt_webhook_secret` to try a list of KEKs (primary from `SECRETS_KEK`, then a fallback list from `SECRETS_KEK_FALLBACK=<kek1>,<kek2>` env). In-flight rotation doesn't break delivery while the migration is running.
2. **Write path**: a CLI migration `apps/api/scripts/rotate_kek.py` that:
   - Reads every row in `webhook_subscriptions` with `ciphertext IS NOT NULL`.
   - Decrypts with the OLD KEK (read from env `SECRETS_KEK_OLD`).
   - Re-encrypts with the NEW KEK (read from env `SECRETS_KEK`).
   - Writes the new ciphertext atomically per row.
   - Logs an audit JSON line per row: `{"subscription_id": "...", "status": "rotated" | "decrypt_failed"}`.

After the operator runs the migration, they remove `SECRETS_KEK_FALLBACK` + `SECRETS_KEK_OLD` from `.env` (decommissioning the OLD KEK).

## Files

**In scope**:
- MODIFIED `apps/api/src/gw2analytics_api/crypto.py` (decrypt with fallback list)
- ~~MODIFIED `apps/api/src/gw2analytics_api/config.py`~~ — removed: the `secrets_kek_fallback` Settings field is owned by **plan 016**. Plan 015 does NOT modify `config.py`.
- MODIFIED `apps/api/.env.example` (document the rotation env vars)
- NEW `apps/api/scripts/rotate_kek.py`
- NEW `apps/api/tests/test_kek_rotation.py` (round-trip + concurrent decryption)

**Out of scope**:
- The arq worker process (transparently uses the updated decrypt path).
- The webhook POST contract (plaintext secret does not change).

## Depends on

- **Plan 016 (settings env)**: the `secrets_kek_fallback: list[str]` Settings field in `apps/api/src/gw2analytics_api/config.py` is owned by plan 016's step 1. Plan 015 only modifies `crypto.py` (read-side fallback list handling) AND `apps/api/.env.example` (rotation flow docs). If plan 015 lands BEFORE plan 016, use a local fallback dict (`{"OLD_KEK": os.environ["SECRETS_KEK_OLD"]}`) inside `crypto.py`'s module-level scope as a temporary workaround until 016 ships.

## Steps

1. Modify `apps/api/src/gw2analytics_api/crypto.py`:
   ```python
   def decrypt_webhook_secret(ciphertext: bytes, *, kek: str | None = None) -> str:
       primary = kek or _env_kek()
       try:
           return _get_fernet(primary).decrypt(ciphertext).decode("utf-8")
       except FernetInvalidToken:
           for fallback in get_settings().secrets_kek_fallback or []:
               try:
                   return _get_fernet(fallback).decrypt(ciphertext).decode("utf-8")
               except FernetInvalidToken:
                   continue
           raise FernetInvalidToken(
               "no KEK in primary or fallback list decrypted this ciphertext"
           )
   ```
2. Update `crypto.py._resolve_kek` to plumb the settings fallback list for reads (does NOT add a new Settings field — that's plan 016).
3. Create `apps/api/scripts/rotate_kek.py` (~120 lines):
   - Reads env: `SECRETS_KEK_OLD`, `SECRETS_KEK`, `DATABASE_URL`.
   - Connects to Postgres via SQLAlchemy (`sync` session — simpler for CLI; alembic-style).
   - SELECT every row in `webhook_subscriptions` with `ciphertext IS NOT NULL`.
   - For each row: decrypt with `_get_fernet(os.environ["SECRETS_KEK_OLD"])` → re-encrypt with `_get_fernet(os.environ["SECRETS_KEK"])` → UPDATE the row inside an explicit transaction.
   - Print audit JSON line per row: `{"id": "...", "status": "rotated" | "decrypt_failed"}` (newline-delimited JSON for log-aggregator ingestion).
   - Final print: `{"status": "done", "rotated_count": N, "failed_count": M}`.
4. Update `apps/api/.env.example`:
   ```
   # SECRETS_KEK rotation flow (USE WITH CARE; data loss risk if misapplied):
   # 1. Generate new KEK:
   #    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   # 2. Set SECRETS_KEK_OLD=<current> SECRETS_KEK_FALLBACK=<current> in env
   # 3. Set SECRETS_KEK=<new> (write-time kicks in immediately)
   # 4. Run: uv run python apps/api/scripts/rotate_kek.py
   # (The script lives at `apps/api/scripts/rotate_kek.py` — invoked directly,
   # NOT as `python -m gw2analytics_api.scripts.rotate_kek`. The pyproject
   # package name is `gw2analytics_api` but the rotation script is shipped
   # under `apps/api/scripts/` as a thin CLI, not as a package module.)
   # 5. After migration completes, remove SECRETS_KEK_OLD + SECRETS_KEK_FALLBACK
   ```
5. Add `apps/api/tests/test_kek_rotation.py`:
   - Round-trip: encrypt with KEK_A → decrypt with primary KEK_B + fallback KEK_A → succeeds.
   - Migration: pre-populate 3 rows encrypted with KEK_A; run script logic in-process; assert all 3 rows decrypt with KEK_B alone (no fallback).

## Verification

- `find apps/api/scripts -name 'rotate_kek.py'` → 1 file.
- `uv run pytest apps/api/tests/test_kek_rotation.py -v` → all green.
- `uv run pytest` (full suite) → all green (no regression).
- Manual smoke (operator): pre-populate a webhook subscription; run the rotation on dev creds; assert HMAC bytes match before and after (byte-for-byte HMAC contract preserved by `0008_payload_bytes.py` migration).

## Test plan

- 1 new pytest with 2 KEKs + round-trip + concurrent decrypt under fallback list.
- The migration script is CLI-tested manually (no E2E pytest — too slow + side-effectful for CI; the in-process test in `test_kek_rotation.py` covers the LOGIC).

## Done criteria

- `crypto.py` accepts a fallback list.
- `rotate_kek.py` CLI exists.
- New + existing tests pass.
- Lint + mypy + ruff all green.

## Maintenance note

- The fallback list is in-process config. A future plan could move it to Postgres (`key_version` column on `webhook_subscriptions`), but that's L-effort — keep in env for v0.x.
- The migration script is FRESH per-domain — do NOT chain multiple KEKs in fallback forever; the operator MUST decommission the OLD KEK after `rotate_kek` completes.
- If a future Fernet spec adds a `max_age` parameter (Fernet timestamp freshness), layer it on top of the fallback list — DO NOT remove the list during a Fernet upgrade.

## Escape hatch

- If the operator is on a single-KEK setup with no compliance pressure, skip plan 015. The .env.example warning is sufficient.
- If a future Postgres version adds native KEK handling in `pgcrypto`, consider migrating off Fernet to that — but only as a post-1.0 refactor (read paths expand dramatically).
