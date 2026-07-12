# KEK Rotation Walkthrough (Plan 015)

This document describes the procedure for rotating the `SECRETS_KEK`
used to encrypt webhook subscription secrets at rest.

## Overview

Webhook subscription secrets are encrypted with Fernet envelope
encryption under a Key Encryption Key (KEK) stored in the
`SECRETS_KEK` environment variable. This procedure rotates the
KEK to a new value while maintaining zero-downtime decryption
capability.

## Prerequisites

- Access to the production environment variables
- Access to the database
- The `cryptography` Python package installed
- The `apps/api/scripts/rotate_kek.py` script

## Rotation Procedure

### Step 1: Generate a new KEK

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Save this value securely (e.g., in your secrets manager).

### Step 2: Configure the environment

Add the following to your `.env` file:

```bash
# Set the NEW KEK (write-time encryption kicks in immediately)
SECRETS_KEK=<new-kek>

# Set the OLD KEK for the migration script
SECRETS_KEK_OLD=<old-kek>

# Set the OLD KEK as fallback for zero-downtime decryption
SECRETS_KEK_FALLBACK=<old-kek>
```

**Important:** The `SECRETS_KEK_FALLBACK` allows the application
to decrypt secrets encrypted with the OLD KEK while the migration
runs. This ensures zero-downtime during rotation.

### Step 3: Restart the application

The application will now:
- Encrypt new webhook secrets with the NEW KEK
- Decrypt existing secrets using the NEW KEK first, then
  fallback to the OLD KEK if the primary fails

### Step 4: Run the migration script

```bash
SECRETS_KEK_OLD=<old-kek> SECRETS_KEK=<new-kek> \
    DATABASE_URL=<database-url> \
    uv run python apps/api/scripts/rotate_kek.py
```

The script will:
1. Connect to the database
2. Find all webhook subscriptions with encrypted secrets
3. Decrypt each secret with the OLD KEK
4. Re-encrypt with the NEW KEK
5. Print audit JSON lines for each row

### Step 5: Verify the migration

Check the script output for:
- `"status": "done"` in the summary line
- `"failed_count": 0` in the summary line
- Each row has `"status": "rotated"` (not `"decrypt_failed"`)

### Step 6: Clean up the environment

Remove the following from `.env`:

```bash
# Remove the OLD KEK
SECRETS_KEK_OLD=

# Remove the fallback
SECRETS_KEK_FALLBACK=
```

Restart the application to apply the changes.

## Verification

After rotation, verify that:
1. New webhook subscriptions work correctly
2. Existing webhook deliveries succeed
3. No errors in the application logs related to `FernetInvalidToken`

## Rollback

If the migration fails or you need to rollback:

1. Restore `SECRETS_KEK` to the OLD value
2. Remove `SECRETS_KEK_OLD` and `SECRETS_KEK_FALLBACK`
3. Restart the application

**Warning:** Any secrets encrypted with the NEW KEK during the
partial migration will be unreadable with the OLD KEK. You may
need to re-create those webhook subscriptions.

## Security Considerations

- **NEVER** commit KEK values to version control
- Store KEKs in a secrets manager (Vault, AWS Secrets Manager, etc.)
- Rotate KEKs periodically as part of your security policy
- The migration script outputs audit JSON lines for compliance logging
- The script is idempotent: running it multiple times is safe
  (already-rotated rows will be re-encrypted with the same NEW KEK)

## Troubleshooting

### "decrypt_failed" errors

If the script reports `decrypt_failed` for some rows:
1. Check that `SECRETS_KEK_OLD` is the correct OLD KEK
2. Verify the KEK hasn't been corrupted
3. Check if the ciphertext column has been manually modified

### Application errors after rotation

If the application fails to decrypt after rotation:
1. Verify `SECRETS_KEK` is set to the NEW KEK
2. Check `SECRETS_KEK_FALLBACK` includes the OLD KEK (if migration
   is still running)
3. Check application logs for `FernetInvalidToken` errors
