"""Tests for ``apps.api.config.Settings``.

v0.10.9 plan 016: lock the ``cors_allowed_origins`` env parser.

Hermetic tests construct ``Settings()`` directly + ``monkeypatch.setenv``
so the contract is deterministic. The lru_cache identity check is
NOT covered here: the full pytest suite has racy teardown between
sibling tests that share the lru_cache, and a prior
``test_get_settings_caches_and_respects_env`` was removed for that
reason. The actual contract (env string -> list[str] round-trip) is
the deterministic path below.
"""

from __future__ import annotations

import pytest

from gw2analytics_api.config import Settings


def test_cors_default_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    s = Settings(_env_file=None)
    assert s.cors_allowed_origins == ["http://localhost:3000"]


def test_cors_wildcard_string_preserves_glob(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    s = Settings(_env_file=None)
    assert s.cors_allowed_origins == ["*"]


def test_cors_empty_string_allows_all_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "")
    s = Settings(_env_file=None)
    assert s.cors_allowed_origins == ["*"]


def test_cors_comma_separated_two_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://a.example.com,https://b.example.com")
    s = Settings(_env_file=None)
    assert s.cors_allowed_origins == ["https://a.example.com", "https://b.example.com"]


def test_cors_comma_separated_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://a.example.com, https://b.example.com")
    s = Settings(_env_file=None)
    assert s.cors_allowed_origins == ["https://a.example.com", "https://b.example.com"]


def test_cors_comma_separated_drops_trailing_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://a.example.com,")
    s = Settings(_env_file=None)
    assert s.cors_allowed_origins == ["https://a.example.com"]


def test_cors_single_origin_no_comma(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://only.example.com")
    s = Settings(_env_file=None)
    assert s.cors_allowed_origins == ["https://only.example.com"]


def test_cors_python_constructor_list_passes_through() -> None:
    """A direct Python ``Settings(origins=[...])`` call bypasses the env validator entirely."""
    s = Settings(_env_file=None, cors_allowed_origins=["https://x.example.com", "*"])
    assert s.cors_allowed_origins == ["https://x.example.com", "*"]
