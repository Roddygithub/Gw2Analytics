"""Tests for ``apps.api.config.Settings`` v0.10.9 plan 016 extras.

Locks down the parsing of 6 new Settings fields added by plan 016
(centralizing ``os.environ.get`` reads via ``Settings``). Mirrors
the ``test_config.py`` pattern: ``monkeypatch`` + cache_clear
+ ``Settings(_env_file=None)`` so the ``.env`` auto-load never
masks the test's explicit env.

The 6 new fields + their expected pydantic-settings parsing rules:

- ``arq_redis_host`` (str, default ``localhost``)
- ``arq_redis_port`` (int, default ``6379``)
- ``allow_inrequest_parse_fallback`` (bool, default ``False``;
  pydantic parses ``"1"`` / ``"true"`` / ``"yes"`` -> True,
  ``"0"`` / ``"false"`` / ``""`` -> False)
- ``skip_schema_guard`` (bool, default ``False``)
- ``gw2analytics_allow_private_webhook_urls`` (bool, default
  ``False``)
- ``secrets_kek_fallback`` (list[str], default ``[]``, custom
  comma-split validator mirroring cors_allowed_origins)
"""

from __future__ import annotations

import pytest

from gw2analytics_api.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    """Clear the lru_cache between tests so ``Settings()`` rebuilds.

    Without this, a test that monkeypatches an env var may see
    the cached instance from a prior test (with the prior env
    value baked in).
    """
    get_settings.cache_clear()


# --- arq_redis_host --------------------------------------------------
def test_arq_redis_host_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARQ_REDIS_HOST", raising=False)
    s = Settings(_env_file=None)
    assert s.arq_redis_host == "localhost"


def test_arq_redis_host_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARQ_REDIS_HOST", "redis.internal")
    s = Settings(_env_file=None)
    assert s.arq_redis_host == "redis.internal"


# --- arq_redis_port --------------------------------------------------
def test_arq_redis_port_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARQ_REDIS_PORT", raising=False)
    s = Settings(_env_file=None)
    assert s.arq_redis_port == 6379


def test_arq_redis_port_env_override_int(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARQ_REDIS_PORT", "6380")
    s = Settings(_env_file=None)
    assert s.arq_redis_port == 6380
    assert isinstance(s.arq_redis_port, int)


# --- allow_inrequest_parse_fallback ----------------------------------
def test_allow_inrequest_parse_fallback_default_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALLOW_INREQUEST_PARSE_FALLBACK", raising=False)
    s = Settings(_env_file=None)
    assert s.allow_inrequest_parse_fallback is False


def test_allow_inrequest_parse_fallback_truthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_INREQUEST_PARSE_FALLBACK", "1")
    s = Settings(_env_file=None)
    assert s.allow_inrequest_parse_fallback is True


def test_allow_inrequest_parse_fallback_falsy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_INREQUEST_PARSE_FALLBACK", "0")
    s = Settings(_env_file=None)
    assert s.allow_inrequest_parse_fallback is False


# --- skip_schema_guard ----------------------------------------------
def test_skip_schema_guard_default_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SKIP_SCHEMA_GUARD", raising=False)
    s = Settings(_env_file=None)
    assert s.skip_schema_guard is False


def test_skip_schema_guard_env_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SKIP_SCHEMA_GUARD", "true")
    s = Settings(_env_file=None)
    assert s.skip_schema_guard is True


# --- gw2analytics_allow_private_webhook_urls -------------------------
def test_gw2analytics_allow_private_webhook_urls_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS", raising=False)
    s = Settings(_env_file=None)
    assert s.gw2analytics_allow_private_webhook_urls is False


def test_gw2analytics_allow_private_webhook_urls_env_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS", "yes")
    s = Settings(_env_file=None)
    assert s.gw2analytics_allow_private_webhook_urls is True


# --- secrets_kek_fallback -------------------------------------------
def test_secrets_kek_fallback_default_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SECRETS_KEK_FALLBACK", raising=False)
    s = Settings(_env_file=None)
    assert s.secrets_kek_fallback == []


def test_secrets_kek_fallback_empty_string_yields_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SECRETS_KEK_FALLBACK=`` -> empty list (safe pre-v0.10.9
    default). Differs from cors_allowed_origins (wildcard) on
    purpose: an empty fallback list is the documented safe
    pre-v0.10.9 default, NOT the inverted-state default.
    """
    monkeypatch.setenv("SECRETS_KEK_FALLBACK", "")
    s = Settings(_env_file=None)
    assert s.secrets_kek_fallback == []


def test_secrets_kek_fallback_single_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SECRETS_KEK_FALLBACK",
        "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=",
    )
    s = Settings(_env_file=None)
    assert s.secrets_kek_fallback == ["YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="]


def test_secrets_kek_fallback_csv_two_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SECRETS_KEK_FALLBACK",
        "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=,YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=",
    )
    s = Settings(_env_file=None)
    assert s.secrets_kek_fallback == [
        "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=",
        "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=",
    ]


def test_secrets_kek_fallback_strips_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SECRETS_KEK_FALLBACK",
        "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE= , "
        "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=",
    )
    s = Settings(_env_file=None)
    # Both strip + drop empty between them.
    assert len(s.secrets_kek_fallback) == 2
    assert all(isinstance(v, str) for v in s.secrets_kek_fallback)
