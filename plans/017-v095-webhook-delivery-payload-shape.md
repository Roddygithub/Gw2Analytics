# Plan 017 — v0.9.5: `WebhookDeliveryOut.payload` shape matches post-0008 `LargeBinary` column

**Author:** senior-advisor audit (improve skill, standard effort) — v0.9.5 cleanup of the lowest-leverage deferred v0.9.3 findings.
**Drift base:** `44ea862`.
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** executor model with NO prior context.

---

## Why this matters

`apps/api/src/gw2analytics_api/schemas.py::WebhookDeliveryOut.payload` is declared as `dict[str, object] | None = None`. The underlying column `webhook_deliveries.payload` is `Mapped[bytes | None]` post-migration `0008_payload_bytes.py` (v0.9.2 plan 009 Step 1+2 — the dispatch worker writes canonical bytes; the scheduler reads them back; the DLQ also stores bytes). A future `GET /api/v1/webhooks/deliveries/{id}` route that returns `WebhookDeliveryOut` would crash on Pydantic v2 `ValidationError` because `bytes` is not assignable to `dict[str, object]`.

No GET-deliveries route exposes the field today, so impact is 0 right now. But the contract is wrong; a 5-line fix closes the future-bug.

---

## Files IN scope

- `apps/api/src/gw2analytics_api/schemas.py` (one field type change).
- `apps/api/tests/test_webhook_schemas.py` — **NEW** (1 regression test).

## Files NOT in scope

- `apps/api/src/gw2analytics_api/models.py` (the `Mapped[bytes]` is already correct post-0008).
- `apps/api/src/gw2analytics_api/workers/*` (the workers write `bytes` correctly).
- Any new route (this plan is a contract fix, not a feature).

---

## Current code (read from `44ea862`)

### `apps/api/src/gw2analytics_api/schemas.py::WebhookDeliveryOut` (around line 410-435)

```python
class WebhookDeliveryOut(BaseModel):
    """Response item for GET /api/v1/webhooks/deliveries/{id} (v0.9.1)."""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., min_length=1, max_length=64)
    subscription_id: str
    upload_id: str
    attempt: int
    status_code: int | None = None
    error: str | None = None
    delivered_at: datetime | None = None
    next_attempt_at: datetime | None = None
    payload: dict[str, object] | None = None  # ← wrong: column is bytes post-0008
```

---

## Step-by-step

### Step 1 — Change the field type to `bytes | None`

In `schemas.py::WebhookDeliveryOut`, REPLACE:

```python
    payload: dict[str, object] | None = None
```

WITH:

```python
    payload: bytes | None = None
```

### Step 2 — Add a regression test

`apps/api/tests/test_webhook_schemas.py` (NEW):

```python
"""v0.9.5 plan 017: WebhookDeliveryOut payload type matches the post-0008 column."""
from __future__ import annotations

from gw2analytics_api.schemas import WebhookDeliveryOut


def test_webhook_delivery_out_payload_is_bytes_optional():
    """The payload field accepts bytes (post-0008) or None; NOT a dict."""
    # Happy path: bytes payload
    d = WebhookDeliveryOut(
        id="dly_abc",
        subscription_id="whsub_xyz",
        upload_id="up-123",
        attempt=1,
        payload=b'{"kind":"upload_completed","upload_id":"up-123"}',
    )
    assert d.payload == b'{"kind":"upload_completed","upload_id":"up-123"}'

    # Happy path: None
    d2 = WebhookDeliveryOut(
        id="dly_def",
        subscription_id="whsub_xyz",
        upload_id="up-456",
        attempt=1,
        payload=None,
    )
    assert d2.payload is None

    # Sad path: dict is no longer accepted (catches accidental regression)
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        WebhookDeliveryOut(
            id="dly_ghi",
            subscription_id="whsub_xyz",
            upload_id="up-789",
            attempt=1,
            payload={"kind": "upload_completed"},  # type: ignore[arg-type]
        )
```

---

## Verification commands

```bash
uv run ruff check apps/api
uv run mypy --no-incremental libs apps
uv run pytest apps/api/tests/test_webhook_schemas.py -v
```

A worktree `git diff` against `44ea862` must show ONLY:
- `apps/api/src/gw2analytics_api/schemas.py` (1 line: `dict[str, object] | None` → `bytes | None`).
- `apps/api/tests/test_webhook_schemas.py` (NEW, 1 test).

## Maintenance note

- The 1 test guards against future regressions (e.g. a refactor that re-introduces the `dict` type).
- The change is forward-looking: no current route returns `WebhookDeliveryOut`. The fix is purely a contract alignment.

## Escape hatches

- If a future feature needs to expose the payload as a parsed dict (e.g. for an operator dashboard), add a `payload_dict: dict[str, object] | None = None` field that hydrates from `payload` via `json.loads(...)` in a model_validator. Out of scope here.
