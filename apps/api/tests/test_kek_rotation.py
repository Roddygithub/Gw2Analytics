"""Tests for KEK rotation support (plan 015)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken as FernetInvalidToken

from gw2analytics_api.crypto import (
    decrypt_webhook_secret,
    encrypt_webhook_secret,
)


@pytest.fixture()
def kek_a() -> str:
    """Generate a Fernet KEK for testing."""
    return Fernet.generate_key().decode()


@pytest.fixture()
def kek_b() -> str:
    """Generate a second Fernet KEK for testing."""
    return Fernet.generate_key().decode()


def test_decrypt_with_fallback_kek(kek_a: str, kek_b: str) -> None:
    """Decrypt succeeds when primary fails but fallback matches."""
    # Encrypt with KEK_A
    plaintext = "whsec_test-secret-12345"
    ciphertext = encrypt_webhook_secret(plaintext, kek=kek_a)

    # Set KEK_B as primary (will fail), KEK_A as fallback (will succeed)
    with patch("gw2analytics_api.crypto.get_settings") as mock_settings:
        mock_settings.return_value.secrets_kek.get_secret_value.return_value = kek_b
        mock_settings.return_value.secrets_kek_fallback = [kek_a]

        # Should succeed via fallback
        result = decrypt_webhook_secret(ciphertext)
        assert result == plaintext


def test_decrypt_with_primary_kek(kek_a: str, kek_b: str) -> None:
    """Decrypt succeeds with primary KEK (no fallback needed)."""
    plaintext = "whsec_primary-keok-test"
    ciphertext = encrypt_webhook_secret(plaintext, kek=kek_a)

    with patch("gw2analytics_api.crypto.get_settings") as mock_settings:
        mock_settings.return_value.secrets_kek.get_secret_value.return_value = kek_a
        mock_settings.return_value.secrets_kek_fallback = [kek_b]

        result = decrypt_webhook_secret(ciphertext)
        assert result == plaintext


def test_decrypt_fails_all_keks(kek_a: str, kek_b: str) -> None:
    """Decrypt fails when neither primary nor fallback KEK works."""
    # Encrypt with a third KEK that is not in the fallback list
    kek_c = Fernet.generate_key().decode()
    plaintext = "whsec_no-match-test"
    ciphertext = encrypt_webhook_secret(plaintext, kek=kek_c)

    with patch("gw2analytics_api.crypto.get_settings") as mock_settings:
        mock_settings.return_value.secrets_kek.get_secret_value.return_value = kek_a
        mock_settings.return_value.secrets_kek_fallback = [kek_b]

        with pytest.raises(FernetInvalidToken):
            decrypt_webhook_secret(ciphertext)


def test_decrypt_with_empty_fallback_list(kek_a: str) -> None:
    """Decrypt works with empty fallback list (primary only)."""
    plaintext = "whsec_no-fallback-test"
    ciphertext = encrypt_webhook_secret(plaintext, kek=kek_a)

    with patch("gw2analytics_api.crypto.get_settings") as mock_settings:
        mock_settings.return_value.secrets_kek.get_secret_value.return_value = kek_a
        mock_settings.return_value.secrets_kek_fallback = []

        result = decrypt_webhook_secret(ciphertext)
        assert result == plaintext


def test_fallback_order_matters(kek_a: str, kek_b: str) -> None:
    """First matching fallback is used (order matters)."""
    plaintext = "whsec order matters"
    ciphertext = encrypt_webhook_secret(plaintext, kek=kek_a)

    # Use a valid Fernet key format but different from kek_a
    kek_c = Fernet.generate_key().decode()
    with patch("gw2analytics_api.crypto.get_settings") as mock_settings:
        mock_settings.return_value.secrets_kek.get_secret_value.return_value = kek_c
        # KEK_B first (won't match), then KEK_A (will match)
        mock_settings.return_value.secrets_kek_fallback = [kek_b, kek_a]

        result = decrypt_webhook_secret(ciphertext)
        assert result == plaintext
