"""v0.9.5 plan 017: WebhookDeliveryOut payload type matches the post-0008 column."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gw2analytics_api.schemas import WebhookDeliveryOut


def test_webhook_delivery_out_payload_is_bytes_optional() -> None:
    """The payload field accepts bytes (post-0008) or None; NOT a dict."""
    d = WebhookDeliveryOut(
        id="dly_abc",
        subscription_id="whsub_xyz",
        upload_id="up-123",
        attempt=1,
        payload=b'{"kind":"upload_completed","upload_id":"up-123"}',
    )
    assert d.payload == b'{"kind":"upload_completed","upload_id":"up-123"}'

    d2 = WebhookDeliveryOut(
        id="dly_def",
        subscription_id="whsub_xyz",
        upload_id="up-456",
        attempt=1,
        payload=None,
    )
    assert d2.payload is None

    with pytest.raises(ValidationError):
        WebhookDeliveryOut(
            id="dly_ghi",
            subscription_id="whsub_xyz",
            upload_id="up-789",
            attempt=1,
            payload={"kind": "upload_completed"},  # type: ignore[arg-type]
        )
