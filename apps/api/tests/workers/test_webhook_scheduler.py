"""Coverage Package 3: webhook_scheduler.py unit tests (mocked DB).

Targets the 92 uncovered lines in webhook_scheduler.py (23.33% -> target 80%+).
"""

from __future__ import annotations

import asyncio
import hmac
import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, Mock

import httpx
import pytest

from gw2analytics_api.workers.webhook_scheduler import (
    _compute_next_attempt_at,
    _attempt_retry,
    _promote_to_dlq,
    process_scheduled_retries,
    lifespan_scheduler,
    _MAX_ATTEMPTS,
    _BACKOFF_BY_ATTEMPT,
    _POLL_INTERVAL_S,
)
from gw2analytics_api.crypto import encrypt_webhook_secret, decrypt_webhook_secret
from gw2analytics_api.models import (
    OrmWebhookDelivery,
    OrmWebhookDlq,
    OrmWebhookSubscription,
)


class TestComputeNextAttemptAt:
    def test_backoff_schedule(self):
        assert _compute_next_attempt_at(1) > datetime.now(UTC)
        assert _compute_next_attempt_at(2) > datetime.now(UTC)
        assert _compute_next_attempt_at(3) > datetime.now(UTC)
        assert _compute_next_attempt_at(4) > datetime.now(UTC)

    def test_backoff_values(self):
        base = datetime.now(UTC)
        t1 = _compute_next_attempt_at(1)
        t2 = _compute_next_attempt_at(2)
        t3 = _compute_next_attempt_at(3)
        
        assert (t1 - base).total_seconds() >= 1
        assert (t1 - base).total_seconds() <= 2
        assert (t2 - base).total_seconds() >= 10
        assert (t2 - base).total_seconds() <= 11
        assert (t3 - base).total_seconds() >= 100
        assert (t3 - base).total_seconds() <= 101


class TestAttemptRetry:
    def test_missing_subscription_marks_failed(self):
        from gw2analytics_api.workers.webhook_scheduler import _attempt_retry
        from gw2analytics_api.models import OrmWebhookDelivery
        
        delivery = MagicMock(spec=OrmWebhookDelivery)
        delivery.subscription_id = str(uuid.uuid4())
        delivery.id = str(uuid.uuid4())
        delivery.attempt = 1
        delivery.payload = b"{}"
        delivery.error = None
        delivery.next_attempt_at = None
        delivery.attempt = 1
        delivery.status_code = None
        delivery.delivered_at = None
        delivery.error = None
        
        result = _attempt_retry(MagicMock(), delivery, None)
        
        assert result is False
        assert delivery.attempt == 2
        assert delivery.error is not None
        assert "missing or revoked" in delivery.error

    def test_revoked_subscription_marks_failed(self):
        from gw2analytics_api.workers.webhook_scheduler import _attempt_retry
        from gw2analytics_api.models import OrmWebhookSubscription, OrmWebhookDelivery
        
        sub = MagicMock(spec=OrmWebhookSubscription)
        sub.revoked_at = datetime.now(UTC)
        
        delivery = MagicMock(spec=OrmWebhookDelivery)
        delivery.subscription_id = str(uuid.uuid4())
        delivery.id = str(uuid.uuid4())
        delivery.attempt = 1
        delivery.payload = b"{}"
        delivery.error = None
        delivery.next_attempt_at = None
        delivery.attempt = 1
        delivery.status_code = None
        delivery.delivered_at = None
        delivery.error = None
        
        result = _attempt_retry(MagicMock(), delivery, sub)
        
        assert result is False
        assert delivery.attempt == 2
        assert delivery.error is not None
        assert "revoked" in delivery.error

    def test_missing_ciphertext_marks_failed(self):
        from gw2analytics_api.workers.webhook_scheduler import _attempt_retry
        from gw2analytics_api.models import OrmWebhookSubscription, OrmWebhookDelivery
        
        sub = MagicMock(spec=OrmWebhookSubscription)
        sub.ciphertext = b""
        sub.revoked_at = None
        
        delivery = MagicMock(spec=OrmWebhookDelivery)
        delivery.subscription_id = str(uuid.uuid4())
        delivery.id = str(uuid.uuid4())
        delivery.attempt = 1
        delivery.payload = b"{}"
        delivery.error = None
        delivery.next_attempt_at = None
        delivery.attempt = 1
        delivery.status_code = None
        delivery.delivered_at = None
        delivery.error = None
        
        result = _attempt_retry(MagicMock(), delivery, sub)
        
        assert result is False
        assert delivery.attempt == 2
        assert delivery.error is not None
        assert "missing subscription ciphertext" in delivery.error

    def test_missing_payload_marks_failed(self):
        from gw2analytics_api.workers.webhook_scheduler import _attempt_retry
        from gw2analytics_api.models import OrmWebhookSubscription, OrmWebhookDelivery
        
        sub = MagicMock(spec=OrmWebhookSubscription)
        sub.ciphertext = b"test"
        sub.revoked_at = None
        
        delivery = MagicMock(spec=OrmWebhookDelivery)
        delivery.subscription_id = str(uuid.uuid4())
        delivery.id = str(uuid.uuid4())
        delivery.attempt = 1
        delivery.payload = None
        delivery.error = None
        delivery.next_attempt_at = None
        delivery.attempt = 1
        delivery.status_code = None
        delivery.delivered_at = None
        delivery.error = None
        
        result = _attempt_retry(MagicMock(), delivery, sub)
        
        assert result is False
        assert delivery.attempt == 2
        assert delivery.error is not None
        assert "missing subscription ciphertext or preserved payload" in delivery.error

    def test_fernet_invalid_token_marks_terminal(self):
        from gw2analytics_api.workers.webhook_scheduler import _attempt_retry
        from gw2analytics_api.crypto import FernetInvalidToken
        from gw2analytics_api.models import OrmWebhookSubscription, OrmWebhookDelivery
        
        def bad_decrypt(ciphertext):
            raise FernetInvalidToken("bad token")
        
        sub = MagicMock(spec=OrmWebhookSubscription)
        sub.ciphertext = b"bad"
        sub.revoked_at = None
        
        delivery = MagicMock(spec=OrmWebhookDelivery)
        delivery.subscription_id = str(uuid.uuid4())
        delivery.id = str(uuid.uuid4())
        delivery.attempt = 1
        delivery.payload = b"{}"
        delivery.error = None
        delivery.next_attempt_at = None
        delivery.attempt = 1
        delivery.status_code = None
        delivery.delivered_at = None
        delivery.error = None
        
        with patch("gw2analytics_api.workers.webhook_scheduler.decrypt_webhook_secret", bad_decrypt):
            result = _attempt_retry(MagicMock(), delivery, sub)
        
        assert result is False
        assert delivery.attempt == 3  # _MAX_ATTEMPTS
        assert delivery.error is not None
        assert "InvalidToken" in delivery.error
        assert delivery.next_attempt_at is None

    def test_network_error_schedules_next_attempt(self):
        from gw2analytics_api.workers.webhook_scheduler import _attempt_retry
        
        sub = MagicMock()
        sub.ciphertext = b"test"
        sub.revoked_at = None
        
        delivery = MagicMock()
        delivery.subscription_id = str(uuid.uuid4())
        delivery.id = str(uuid.uuid4())
        delivery.attempt = 1
        delivery.payload = b"{}"
        delivery.error = None
        delivery.next_attempt_at = None
        delivery.attempt = 1
        delivery.status_code = None
        delivery.delivered_at = None
        delivery.error = None
        
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectError("connection failed")
        
        with patch("gw2analytics_api.workers.webhook_scheduler.decrypt_webhook_secret", return_value="test"):
            result = _attempt_retry(mock_client, delivery, sub)
        
        assert result is False
        assert delivery.attempt == 2
        assert delivery.error is not None
        assert "ConnectError" in delivery.error
        assert delivery.next_attempt_at is not None

    def test_non_2xx_response_schedules_next_attempt(self):
        from gw2analytics_api.workers.webhook_scheduler import _attempt_retry
        
        sub = MagicMock()
        sub.ciphertext = b"test"
        sub.revoked_at = None
        
        delivery = MagicMock()
        delivery.subscription_id = str(uuid.uuid4())
        delivery.id = str(uuid.uuid4())
        delivery.attempt = 1
        delivery.payload = b"{}"
        delivery.error = None
        delivery.next_attempt_at = None
        delivery.attempt = 1
        delivery.status_code = None
        delivery.delivered_at = None
        delivery.error = None
        
        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.status_code = 500
        
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        
        with patch("gw2analytics_api.workers.webhook_scheduler.decrypt_webhook_secret", return_value="test"):
            result = _attempt_retry(mock_client, delivery, sub)
        
        assert result is False
        assert delivery.attempt == 2
        assert delivery.error is not None
        assert "non-2xx" in delivery.error
        assert delivery.status_code == 500
        assert delivery.next_attempt_at is not None

    def test_successful_retry_marks_delivered(self):
        from gw2analytics_api.workers.webhook_scheduler import _attempt_retry
        
        sub = MagicMock()
        sub.ciphertext = b"test"
        sub.revoked_at = None
        
        delivery = MagicMock()
        delivery.subscription_id = str(uuid.uuid4())
        delivery.id = str(uuid.uuid4())
        delivery.attempt = 1
        delivery.payload = b"{}"
        delivery.error = None
        delivery.next_attempt_at = None
        delivery.attempt = 1
        delivery.status_code = None
        delivery.delivered_at = None
        delivery.error = None
        
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        
        with patch("gw2analytics_api.workers.webhook_scheduler.decrypt_webhook_secret", return_value="test"):
            result = _attempt_retry(mock_client, delivery, sub)
        
        assert result is True
        assert delivery.attempt == 2
        assert delivery.delivered_at is not None
        assert delivery.error is None
        assert delivery.status_code == 200
        assert delivery.next_attempt_at is None


class TestPromoteToDlq:
    @pytest.mark.skip(reason="Requires full settings config")
    def test_promote_creates_dlq_row_and_deletes_delivery(self):
        from gw2analytics_api.workers.webhook_scheduler import _promote_to_dlq
        from gw2analytics_api.models import OrmWebhookDelivery, OrmWebhookDlq
        
        db = MagicMock()
        delivery = MagicMock(spec=OrmWebhookDelivery)
        delivery.id = str(uuid.uuid4())
        delivery.subscription_id = str(uuid.uuid4())
        delivery.upload_id = str(uuid.uuid4())
        delivery.payload = b"{}"
        delivery.error = "failed"
        
        dlq = _promote_to_dlq(db, delivery)
        
        assert isinstance(dlq, MagicMock)
        db.add.assert_called_once()
        db.delete.assert_called_once_with(delivery)


class TestProcessScheduledRetries:
    def test_no_rows_returns_zero(self):
        from gw2analytics_api.workers.webhook_scheduler import process_scheduled_retries
        
        factory = MagicMock()
        mock_session = MagicMock()
        factory.return_value.__enter__.return_value = mock_session
        mock_session.execute.return_value.scalars.return_value.all.return_value = []
        
        count = process_scheduled_retries(factory)
        assert count == 0

    def test_no_rows_ready_returns_zero(self):
        from gw2analytics_api.workers.webhook_scheduler import process_scheduled_retries
        
        factory = MagicMock()
        mock_session = MagicMock()
        factory.return_value.__enter__.return_value = mock_session
        
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_session.execute.return_value.scalars.return_value = mock_scalars
        
        count = process_scheduled_retries(factory)
        assert count == 0


class TestLifespanScheduler:
    @pytest.mark.asyncio
    async def test_scheduler_runs_and_sleeps(self):
        from gw2analytics_api.workers.webhook_scheduler import lifespan_scheduler
        
        factory = MagicMock()
        
        call_count = 0
        
        def mock_process(factory):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError
            return 0
        
        with patch("gw2analytics_api.workers.webhook_scheduler.process_scheduled_retries", mock_process):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                mock_sleep.side_effect = [None, asyncio.CancelledError]
                
                try:
                    await lifespan_scheduler(factory)
                except asyncio.CancelledError:
                    pass
        
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_scheduler_handles_exception_and_continues(self):
        from gw2analytics_api.workers.webhook_scheduler import lifespan_scheduler
        
        factory = MagicMock()
        
        call_count = 0
        
        def mock_process(factory):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("DB error")
            elif call_count == 2:
                raise asyncio.CancelledError
            return 0
        
        with patch("gw2analytics_api.workers.webhook_scheduler.process_scheduled_retries", mock_process):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                mock_sleep.side_effect = [None, asyncio.CancelledError]
                
                try:
                    await lifespan_scheduler(factory)
                except asyncio.CancelledError:
                    pass
        
        assert call_count == 2


class TestSchedulerConfiguration:
    def test_constants_defined(self):
        from gw2analytics_api.workers.webhook_scheduler import (
            _MAX_ATTEMPTS, _POLL_INTERVAL_S, _BACKOFF_BY_ATTEMPT, _REQUEST_TIMEOUT_S
        )
        assert _MAX_ATTEMPTS == 3
        assert _POLL_INTERVAL_S == 5.0
        assert _BACKOFF_BY_ATTEMPT == {1: 1, 2: 10, 3: 100}
        assert _REQUEST_TIMEOUT_S == 10.0
