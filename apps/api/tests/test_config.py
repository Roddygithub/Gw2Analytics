"""Tests for ``apps.api.config.Settings``.

Locks down the ``cors_allowed_origins`` environment parser that
resolves the pydantic-settings ``SettingsError`` crash observed
when ``CORS_ALLOWED_ORIGINS=*`` was set in the gateway env (the
default ``pydantic-settings`` JSON-decode path rejected the raw
``*`` string even though no JSON was intended).

The validator must accept:

- env unset -> default ``['*']``
- env = ``*`` -> wildcard (preserved as a single ``'*'`` entry)
- env = ``''`` -> falls back to default ``['*']`` (via pydantic-settings'
  ``env_ignore_empty=True`` short-circuit; the validator never sees the
  empty string)
- env = ``https://a.com,https://b.com`` -> 2 entries (stripped)
- env = ``https://a.com, https://b.com`` (whitespace) -> 2 entries
- env = ``https://a.com,`` (trailing comma) -> 1 entry
- Python constructor call -> the value flows through unchanged.

Each test mocks ``os.environ`` via ``monkeypatch`` + ``get_settings.cache_clear()``
so the lru_cache does not stale-handle across tests.
"""

from __future__ import annotations

import pytest

from gw2analytics_api.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    """Clear the lru_cache between tests so each runs with a fresh ``Settings()``.

    The lru_cache on ``get_settings`` freezes the constructed
    instance for the process lifetime; without clearing, a test that
    sets an env var would see the cached instance from a prior test.
    """
    get_settings.cache_clear()


def test_cors_default_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    s = Settings(_env_file=None)
    assert s.cors_allowed_origins == ["*"]


def test_cors_wildcard_string_preserves_glob(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    s = Settings(_env_file=None)
    assert s.cors_allowed_origins == ["*"]


def test_cors_empty_string_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_get_settings_caches_and_respects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_settings`` returns a cached instance that reflects the env at first call."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://cached.example.com")
    s1 = get_settings()
    assert s1.cors_allowed_origins == ["https://cached.example.com"]
    # Mutate env AFTER get_settings; cache holds the prior value.
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://other.example.com")
    s2 = get_settings()
    assert s2 is s1
    assert s2.cors_allowed_origins == ["https://cached.example.com"]
