from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# v0.9.5 plan 018: closed set of filter kinds. The dispatcher only
# understands ``upload_completed`` today; accepting arbitrary kinds at
# creation leads to dead-on-arrival subscriptions (201 + secret +
# never-fires). Future kinds are added here and in the dispatcher in
# lockstep.
_WEBHOOK_KNOWN_KINDS = frozenset({"upload_completed"})


class WebhookSubscriptionCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    url: str
    filter: dict[str, object]
    description: str | None = None

    @field_validator("filter")
    @classmethod
    def _validate_filter_kind(cls, value: dict[str, object]) -> dict[str, object]:
        """Reject unknown or missing ``filter.kind`` at creation time.

        The dispatcher silently skips subscriptions whose
        ``filter.kind`` does not match the dispatched event kind.
        Validating at creation prevents integrators from creating
        subscriptions that will never fire.
        """
        kind = value.get("kind")
        if kind is None:
            raise ValueError("filter.kind is required")
        if kind not in _WEBHOOK_KNOWN_KINDS:
            raise ValueError(f"filter.kind={kind!r} is not supported")
        return value


class WebhookSubscriptionCreatedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    url: str
    filter: dict[str, object]
    description: str | None = None
    secret: str
    created_at: datetime


class WebhookSubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    url: str
    filter: dict[str, object]
    description: str | None = None
    created_at: datetime


class WebhookDeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., min_length=1, max_length=64)
    subscription_id: str
    upload_id: str
    attempt: int
    status_code: int | None = None
    error: str | None = None
    delivered_at: datetime | None = None
    next_attempt_at: datetime | None = None
    payload: bytes | None = None


class WebhookDeliveryReplayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    delivery_id: str = Field(..., min_length=1, max_length=64)
    subscription_id: str
    upload_id: str
    attempt: int
    next_attempt_at: datetime
    restart: bool


class WebhookDlqOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., min_length=1, max_length=64)
    subscription_id: str
    upload_id: str
    last_error: str | None = None
    moved_to_dlq_at: datetime
