"""v0.9.5 plan 018: WebhookSubscriptionCreate filter.kind validator tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gw2analytics_api.schemas import WebhookSubscriptionCreate


def test_known_filter_kind_is_accepted() -> None:
    """A subscription with filter.kind=upload_completed is valid."""
    sub = WebhookSubscriptionCreate(
        url="https://example.com/webhook",
        filter={"kind": "upload_completed"},
    )
    assert sub.filter["kind"] == "upload_completed"


def test_unknown_filter_kind_is_rejected() -> None:
    """An unknown filter.kind surfaces as a 422 validation error."""
    with pytest.raises(ValidationError) as exc_info:
        WebhookSubscriptionCreate(
            url="https://example.com/webhook",
            filter={"kind": "fight_completed"},
        )
    assert "filter.kind" in str(exc_info.value) or "not supported" in str(exc_info.value)


def test_missing_filter_kind_is_rejected() -> None:
    """A subscription without filter.kind surfaces as a 422 validation error."""
    with pytest.raises(ValidationError) as exc_info:
        WebhookSubscriptionCreate(
            url="https://example.com/webhook",
            filter={"upload_id": "up-123"},
        )
    assert "filter.kind" in str(exc_info.value) or "required" in str(exc_info.value)
