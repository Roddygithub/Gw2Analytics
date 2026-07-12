"""Webhook secret-at-rest encryption helpers (v0.10.0 plan 031).

Encloses webhook subscription secrets with a Python-side Fernet
envelope so the database never carries the plaintext. The KEK
is held in the ``SECRETS_KEK`` env var (loaded via pydantic at
startup; see :class:`gw2analytics_api.config.Settings.secrets_kek`).

Threat model
============
A stolen DB snapshot OR a flawed SQL-level data extract is NOT
enough to forge ``X-Gw2Analytics-Signature: sha256=...`` headers
against registered subscribers -- the attacker must ALSO have
access to the gateway process environment. (CWE-256 closure.)

Why Python-side Fernet (NOT pgcrypto)
-------------------------------------
``pgcrypto``'s ``pgp_sym_encrypt(plaintext, kek)`` IS the natural-
looking DB-side envelope BUT requires the plaintext KEK to cross
the SQL wire on every encrypt/decrypt fire. A
``log_min_duration_statement`` configuration + a
``pg_stat_statements`` snapshot would leak the KEK on every
dispatch under verbose logging. Python's
``cryptography.fernet.Fernet`` keeps the KEK inside the app
process memory and is functionally equivalent to
``pgp_sym_encrypt`` for our threat model.

The design rejection rationale
-------------------------------
The v0.10.0 plan 031 design review REJECTED the pgcrypto option
for this specific reason: threat-model defense-in-depth requires
the KEK to stay out of SQL query logs. Anyone proposing a future
refactor to ``pgcrypto`` MUST address this audit-log leak
explicitly in the PR description; the python-side Fernet
envelope is the locked-in pattern.
"""

from __future__ import annotations

import threading

from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken as FernetInvalidToken

from gw2analytics_api.config import get_settings

# Cache Fernet instances keyed by KEK string. Fernet construction is
# ~1ms; the hot path (webhook dispatch) decrypts once per sub per
# upload so the cache pays off for gateways with many active subs.
# The lock is conservative (Python dict GIL is sufficient for
# type-stable keys, but explicit Lock matches the v0.8.3
# best-practice convention for the role/auth checks already in
# the routes, so future readers find a familiar shape).
_FERNET_CACHE: dict[str, Fernet] = {}
_FERNET_LOCK = threading.Lock()


def _get_fernet(kek: str) -> Fernet:
    """Return a cached Fernet keyed by the URL-safe base64 KEK string."""
    with _FERNET_LOCK:
        f = _FERNET_CACHE.get(kek)
        if f is None:
            f = Fernet(kek.encode("ascii"))
            _FERNET_CACHE[kek] = f
        return f


def _resolve_kek(explicit: str | None) -> str:
    """Resolve the KEK from the explicit argument or ``SECRETS_KEK`` env.

    Raises a clear :class:`RuntimeError` when the env var is missing --
    a misconfigured deployment must surface loud at first use,
    NOT silently fall back to plaintext (which would defeat the
    whole CWE-256 closure). The error message names the canonical
    Python one-liner to generate a fresh KEK so the operator has
    the recovery path inline.
    """
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

    Returns the Fernet envelope bytes
    (:meth:`cryptography.fernet.Fernet.encrypt` returns ``bytes``).
    The envelope is timestamped + versioned per Fernet's
    serializer; the default TTL is 0 (no expiry).

    Reads ``SECRETS_KEK`` from :data:`os.environ` when ``kek`` is
    NOT given. The explicit-arg form is used by alembic migrations
    that read :data:`os.environ` themselves; runtime code (the
    ``POST /api/v1/webhooks`` route) lets the env resolution fire
    so the call sites stay one-line.
    """
    return _get_fernet(_resolve_kek(kek)).encrypt(plaintext.encode("utf-8"))


def decrypt_webhook_secret(ciphertext: bytes, *, kek: str | None = None) -> str:
    """Fernet-decode a webhook secret for HMAC signing.

    Returns the original plaintext (UTF-8 ``str``). Raises
    :class:`cryptography.fernet.InvalidToken` (re-exported as
    :data:`FernetInvalidToken`) when the ciphertext was encrypted
    under a different KEK OR is otherwise malformed (e.g., manual
    DB edit OR a KEK-rotation-without-migration). Worker
    callers should catch this exception per-row so one corrupt
    row does NOT crash the entire dispatch loop (one
    subscriber's misconfiguration must not freeze every other
    webhook).

    v0.10.12 plan 015: fallback KEK list. If the primary KEK
    fails to decrypt, try each KEK in ``SECRETS_KEK_FALLBACK``
    (comma-separated list in env). This enables zero-downtime
    KEK rotation: set the old KEK as fallback, rotate to a new
    primary, run the migration script, then remove the fallback.
    """
    primary = _resolve_kek(kek)
    try:
        return _get_fernet(primary).decrypt(ciphertext).decode("utf-8")
    except FernetInvalidToken:
        # Try fallback KEKs (plan 015: KEK rotation support)
        fallbacks = get_settings().secrets_kek_fallback
        for fallback_kek in fallbacks:
            try:
                return _get_fernet(fallback_kek).decrypt(ciphertext).decode("utf-8")
            except FernetInvalidToken:
                continue
        # All attempts failed
        raise


__all__ = [
    "FernetInvalidToken",
    "decrypt_webhook_secret",
    "encrypt_webhook_secret",
]
