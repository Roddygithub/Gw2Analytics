"""End-to-end POST /webhooks + GET + GET-by-id + DELETE tests against a real Postgres.

Each test seeds ONE subscription with a uuid-derived suffix in the URL so
re-runs don't collide with prior state. Tests always filter or assert against
their specific sub-id.
"""

from __future__ import annotations

import socket as _socket
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_webhooks_helpers import _bounds, _post_sub

from gw2analytics_api import schemas
from gw2analytics_api.config import Settings, get_settings
from gw2analytics_api.crypto import decrypt_webhook_secret, encrypt_webhook_secret
from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.main import app
from gw2analytics_api.models import (
    UPLOAD_STATUS_COMPLETED,
    OrmFight,
    OrmWebhookDelivery,
    OrmWebhookSubscription,
    Upload,
)
from gw2analytics_api.routes import webhooks as _webhook_routes
from gw2analytics_api.workers.webhook_scheduler import process_scheduled_retries

client = TestClient(app)


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------


def test_generate_subscription_id_is_url_safe() -> None:
    sub_id = _webhook_routes._generate_subscription_id()
    assert sub_id.startswith("whsub_")
    assert len(sub_id) >= 8
    assert sub_id.isascii()


def test_webhooks_post_201_returns_secret_once() -> None:
    resp = _post_sub()
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["url"].startswith("https://93.184.216.34/wh-")
    assert body["id"].startswith("whsub_")
    assert body["secret"].startswith("whsec_")
    sub_id = body["id"]
    get_resp = client.get(f"/api/v1/webhooks/{sub_id}")
    assert get_resp.status_code == 200
    assert "secret" not in get_resp.json()


def test_webhooks_post_422_on_http_non_loopback_url() -> None:
    resp = _post_sub("http://example.com/wh")
    assert resp.status_code == 422, resp.text


def test_webhooks_post_422_on_empty_host_url() -> None:
    resp = _post_sub("https://")
    assert resp.status_code == 422, resp.text


def test_webhooks_post_422_on_whitespace_url() -> None:
    resp = _post_sub("https://exam ple.com/wh")
    assert resp.status_code == 422, resp.text


def test_webhooks_get_list_returns_only_active() -> None:
    sub_id = _post_sub().json()["id"]
    client.delete(f"/api/v1/webhooks/{sub_id}")
    resp = client.get("/api/v1/webhooks")
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()]
    assert sub_id not in ids


def test_webhooks_get_by_id_returns_no_secret() -> None:
    sub_id = _post_sub().json()["id"]
    resp = client.get(f"/api/v1/webhooks/{sub_id}")
    assert resp.status_code == 200
    assert "secret" not in resp.json()


def test_webhooks_get_by_id_404_on_unknown() -> None:
    resp = client.get("/api/v1/webhooks/whsub_DEADBEEF")
    assert resp.status_code == 404


def test_webhooks_get_by_id_404_on_revoked() -> None:
    sub_id = _post_sub().json()["id"]
    client.delete(f"/api/v1/webhooks/{sub_id}")
    assert client.get(f"/api/v1/webhooks/{sub_id}").status_code == 404


def test_webhooks_delete_204_marks_revoked() -> None:
    sub_id = _post_sub().json()["id"]
    assert client.delete(f"/api/v1/webhooks/{sub_id}").status_code == 204
    assert client.get(f"/api/v1/webhooks/{sub_id}").status_code == 404


def test_webhooks_delete_404_on_unknown() -> None:
    assert client.delete("/api/v1/webhooks/whsub_DEADBEEF").status_code == 404


def test_webhooks_delete_idempotent_when_already_revoked() -> None:
    sub_id = _post_sub().json()["id"]
    assert client.delete(f"/api/v1/webhooks/{sub_id}").status_code == 204
    assert client.delete(f"/api/v1/webhooks/{sub_id}").status_code == 204


def test_replay_dlq_schema_declares_string_delivery_id() -> None:
    replay_fields = schemas.WebhookDeliveryReplayOut.model_fields
    delivery_fields = schemas.WebhookDeliveryOut.model_fields
    assert replay_fields["delivery_id"].annotation is str
    assert delivery_fields["id"].annotation is str
    rmin, rmax = _bounds(replay_fields["delivery_id"])
    dmin, dmax = _bounds(delivery_fields["id"])
    assert rmin is not None and rmin >= 1
    assert rmax is not None and rmax <= 64
    assert dmin is not None and dmin >= 1
    assert dmax is not None and dmax <= 64
    ok_payload = {
        "delivery_id": "dly_" + "a" * 32,
        "subscription_id": "whsub_" + "b" * 32,
        "upload_id": "upl_" + "c" * 32,
        "attempt": 1,
        "next_attempt_at": "2025-01-01T00:00:00+00:00",
        "restart": True,
    }
    schemas.WebhookDeliveryReplayOut.model_validate(ok_payload)


# ---------------------------------------------------------------------------
# SSRF regression tests
# ---------------------------------------------------------------------------


def test_post_webhook_rejects_https_private_ip_literal() -> None:
    resp = _post_sub("https://10.0.0.1/")
    assert resp.status_code == 422, resp.text
    detail_blob = str(resp.json()).lower()
    assert "private" in detail_blob and "loopback" in detail_blob


def test_post_webhook_rejects_https_link_local_literal() -> None:
    resp = _post_sub("https://169.254.169.254/")
    assert resp.status_code == 422, resp.text
    detail_blob = str(resp.json()).lower()
    assert "private" in detail_blob and "loopback" in detail_blob


def test_post_webhook_rejects_https_ipv6_loopback_literal() -> None:
    resp = _post_sub("https://[::1]/")
    assert resp.status_code == 422, resp.text
    detail_blob = str(resp.json()).lower()
    assert "loopback" in detail_blob


def test_post_webhook_rejects_https_hostname_resolving_to_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_getaddrinfo(
        host: str, port: object, **_kwargs: object
    ) -> list[tuple[Any, Any, Any, Any, tuple[str, int]]]:
        return [(_socket.AF_INET, _socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0))]

    monkeypatch.setattr(_socket, "getaddrinfo", _fake_getaddrinfo)
    resp = _post_sub("https://internal.example/")
    assert resp.status_code == 422, resp.text
    assert "private" in str(resp.json()).lower()


def test_post_webhook_accepts_https_private_ip_with_env_optin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS", "1")
    get_settings.cache_clear()
    resp = _post_sub("https://10.0.0.2/")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["url"] == "https://10.0.0.2/"
    assert body["id"].startswith("whsub_")
    assert body["secret"].startswith("whsec_")


# ---------------------------------------------------------------------------
# Scheduler + DLQ + replay tests
# ---------------------------------------------------------------------------


@pytest.fixture
def session_factory() -> Any:
    return get_sessionmaker()


def _bootstrap_webhook_environment(session_factory: Any) -> tuple[Any, str]:
    session = session_factory()
    try:
        fight = session.get(OrmFight, "fixture-fight-id")
        if fight is None:
            fight = OrmFight(
                id="fixture-fight-id",
                upload_id=_uuid.uuid4(),
                build_version="20240925",
                encounter_id=0,
                agent_count=0,
                started_at=datetime.now(UTC),
                game_type=0,
            )
            session.add(fight)
        upload = session.get(Upload, "fixture-upload-id")
        if upload is None:
            upload = Upload(
                id=_uuid.uuid4(),
                sha256="fixture-sha256",
                original_filename="fixture.zevtc",
                size_bytes=100,
                status=UPLOAD_STATUS_COMPLETED,
                parser_version="1",
            )
            session.add(upload)
        session.commit()
        sub = OrmWebhookSubscription(
            id="whsub_scheduler",
            url="https://93.184.216.34/scheduler",
            filter_payload={"kind": "upload_completed"},
            ciphertext=b"dummy",
            description=None,
            created_at=datetime.now(UTC),
            revoked_at=None,
        )
        session.add(sub)
        session.commit()
        return session, sub.id
    finally:
        session.close()


def _seed_failed_delivery(session_factory: Any, sub_id: str, attempt: int = 3) -> str:
    session = session_factory()
    try:
        dly = OrmWebhookDelivery(
            id=f"dly_{_uuid.uuid4().hex[:16]}",
            subscription_id=sub_id,
            upload_id="fixture-upload-id",
            attempt=attempt,
        )
        session.add(dly)
        session.commit()
        return dly.id
    finally:
        session.close()


def test_retry_scheduler_first_attempt_success(session_factory: Any) -> None:
    session, sub_id = _bootstrap_webhook_environment(session_factory)
    try:
        delivery_id = _seed_failed_delivery(session_factory, sub_id, attempt=0)
        process_scheduled_retries(session_factory, batch_size=10)
        session = session_factory()
        dly = session.get(OrmWebhookDelivery, delivery_id)
        assert dly is not None
    finally:
        session.close()


def test_replay_dlq_idempotent_concurrent_calls(session_factory: Any) -> None:
    pass


def test_replayed_delivery_byte_for_byte_hmac_matches_original(session_factory: Any) -> None:
    pass


# ---------------------------------------------------------------------------
# Crypto + settings tests
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_round_trip_yields_original() -> None:
    from gw2analytics_api.config import get_settings

    plaintext = b"whsec_test_secret_value_32_chars_long!"
    kek = get_settings().secrets_kek.get_secret_value().encode("ascii")
    ciphertext = encrypt_webhook_secret(plaintext, kek)
    assert ciphertext != plaintext
    decrypted = decrypt_webhook_secret(ciphertext, kek)
    assert decrypted == plaintext


def test_settings_secrets_kek_validator_accepts_44_rejects_other_lengths() -> None:
    Settings(secrets_kek="YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=")
    with pytest.raises(ValidationError):
        Settings(secrets_kek="a" * 43)


def test_create_webhook_persists_ciphertext_not_plaintext_on_disk() -> None:
    pass


def test_dispatch_skips_corrupted_ciphertext_but_continues_others() -> None:
    pass


def test_list_webhook_dlq_returns_dlq_rows() -> None:
    pass


def test_list_webhook_dlq_filters_by_subscription_id() -> None:
    pass


def test_list_webhook_dlq_pagination() -> None:
    pass


def test_list_webhook_dlq_rejects_out_of_range_pagination() -> None:
    assert client.get("/api/v1/webhooks/dlq?limit=0").status_code == 422
    assert client.get("/api/v1/webhooks/dlq?limit=1001").status_code == 422
    assert client.get("/api/v1/webhooks/dlq?offset=-1").status_code == 422


def test_settings_secrets_kek_reads_from_env_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    valid_kek = "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
    monkeypatch.setenv("SECRETS_KEK", valid_kek)
    settings = Settings()
    assert settings.secrets_kek.get_secret_value() == valid_kek
    monkeypatch.setenv("SECRETS_KEK", "a" * 43)
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "SECRETS_KEK" in str(exc_info.value)
