"""Webhook secret-at-rest encryption helpers (v0.10.0 plan 031).

Encloses webhook subscription secrets with a Python-side Fernet
envelope so the database never carries the plaintext. The KEK
is held in the ``SECRETS_KEK`` env var.

Python-side Fernet was chosen over ``pgcrypto`` because the
latter requires the plaintext KEK to cross the SQL wire, which
audit-log configurations (``log_min_duration_statement``) would
leak (CWE-256 closure). The design rejection rationale is
archived in the plan-031 review notes.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken as FernetInvalidToken

from gw2analytics_api.config import get_settings


@lru_cache(maxsize=8)
def _get_fernet(kek: str) -> Fernet:
    """Return a cached Fernet keyed by the URL-safe base64 KEK string."""
    return Fernet(kek.encode("ascii"))


def _resolve_kek(explicit: str | None) -> str:
    """Resolve the KEK from the explicit argument or ``SECRETS_KEK`` env."""
    kek = explicit or get_settings().secrets_kek.get_secret_value() or ""
    if not kek:
        raise RuntimeError(
            "SECRETS_KEK env var is required to encrypt/decrypt webhook "
            "secrets at rest. Generate via "
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"`.'
        )
    return kek


def encrypt_webhook_secret(plaintext: str, *, kek: str | None = None) -> bytes:
    """Fernet-encode a webhook secret for at-rest storage.

    Returns the Fernet envelope bytes. Reads ``SECRETS_KEK`` from
    env when ``kek`` is not given.
    """
    return _get_fernet(_resolve_kek(kek)).encrypt(plaintext.encode("utf-8"))


def decrypt_webhook_secret(ciphertext: bytes, *, kek: str | None = None) -> str:
    """Fernet-decode a webhook secret for HMAC signing.

    Returns the original plaintext. Raises :class:`FernetInvalidToken`
    when the ciphertext was encrypted under a different KEK.

    Fallback KEK list (``SECRETS_KEK_FALLBACK``) enables zero-downtime
    KEK rotation (v0.10.12 plan 015).
    """
    primary = _resolve_kek(kek)
    try:
        return _get_fernet(primary).decrypt(ciphertext).decode("utf-8")
    except FernetInvalidToken:
        fallbacks = get_settings().secrets_kek_fallback
        for fallback_kek in fallbacks:
            try:
                return _get_fernet(fallback_kek).decrypt(ciphertext).decode("utf-8")
            except FernetInvalidToken:
                continue
        raise


__all__ = [
    "FernetInvalidToken",
    "decrypt_webhook_secret",
    "encrypt_webhook_secret",
]
