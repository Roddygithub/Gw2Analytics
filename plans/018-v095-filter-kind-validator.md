# Plan 018 — v0.9.5: `WebhookSubscriptionCreate.filter.kind` validator (422 on unknown kinds)

**Author:** senior-advisor audit (improve skill, standard effort) — v0.9.5 cleanup of the lowest-leverage deferred v0.9.3 findings.
**Drift base:** `44ea862`.
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** executor model with NO prior context.

---

## Why this matters

`apps/api/src/gw2analytics_api/schemas.py::WebhookSubscriptionCreate.filter: dict[str, object]` accepts ANY dict. The dispatcher at `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py:178` (`if sub.filter_payload.get("kind") != _FILTER_KIND_UPLOAD_COMPLETED: ... return False`) silently skips any subscription whose `kind` is not `"upload_completed"`. So an integrator who POSTs `{filter: {kind: "boop"}}` receives a 201 + a one-time secret, then **never** receives any webhook — the subscription is dead-on-arrival with no error feedback.

The fix: a `field_validator` on `WebhookSubscriptionCreate.filter` that checks `kind` membership in a known set (currently just `{"upload_completed"}`; future kinds add to the set). Unknown kinds return 422 with a clear remediation message.

---

## Files IN scope

- `apps/api/src/gw2analytics_api/schemas.py` (add 1 `field_validator`).
- `apps/api/tests/test_webhook_subscription_create.py` — **NEW** (2 tests).

## Files NOT in scope

- `apps/api/src/gw2analytics_api/routes/webhooks.py` (no route change; the schema-level validator fires before the route body).
- `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` (the dispatcher's silent-skip is a defense-in-depth fallback for OLD rows that landed before the validator; new rows always have valid kinds).

---

## Current code (read from `44ea862`)

### `apps/api/src/gw2analytics_api/schemas.py::WebhookSubscriptionCreate` (around line 360-385)

```python
class WebhookSubscriptionCreate(BaseModel):
    """POST /api/v1/webhooks request body (v0.9.0 backend).

    The integrator does NOT supply a ``secret`` on create -- the
    gateway generates a fresh ``whsec_<base64(32bytes)>`` and
    returns it ONCE in the 201 response.

    The ``filter`` field is ``dict[str, object]`` (matches the
    JSONB column on ``webhook_subscriptions``). The integrator
    pins a subset of keys today (``upload_status``,
    ``fight_result``); v0.9.1 will add a ``field_validator`` to
    enforce string-valued filters if the spec decides to lock
    the contract.
    """

    url: str
    filter: dict[str, object]
    description: str | None = None
```

### `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` (line 178, the silent skip)

```python
if sub.filter_payload.get("kind") != _FILTER_KIND_UPLOAD_COMPLETED:
    logger.debug(
        "webhook subscription %s filter kind=%r; no match for upload_completed dispatch",
        sub.id,
        sub.filter_payload.get("kind"),
    )
    return False
```

---

## Step-by-step

### Step 1 — Define the known-kinds constant + add the field_validator

In `apps/api/src/gw2analytics_api/schemas.py`, near the top of the webhook-schemas section (just before `class WebhookSubscriptionCreate`):

```python
from pydantic import field_validator

# v0.9.5 plan 018: the set of accepted filter.kind values for
# POST /api/v1/webhooks. Today only ``upload_completed`` is
# dispatched (see ``webhook_dispatch._FILTER_KIND_UPLOAD_COMPLETED``).
# Future kinds (per-encounter, per-result) add here + in the
# dispatcher's match table. Integrators who POST a kind NOT in
# this set receive a 422 with a clear remediation message;
# the dead-on-arrival subscription pattern (201 + secret +
# never-fires) is closed.
_WEBHOOK_KNOWN_KINDS: frozenset[str] = frozenset({"upload_completed"})
```

### Step 2 — Add the `field_validator` on `WebhookSubscriptionCreate`

REPLACE the `filter: dict[str, object]` line + add the validator method:

```python
class WebhookSubscriptionCreate(BaseModel):
    """POST /api/v1/webhooks request body (v0.9.0 backend).

    The integrator does NOT supply a ``secret`` on create -- the
    gateway generates a fresh ``whsec_<base64(32bytes)>`` and
    returns it ONCE in the 201 response (see
    :class:`WebhookSubscriptionCreatedOut`).

    The ``filter`` field is ``dict[str, object]`` (matches the
    JSONB column). The integrator MUST include a ``kind`` key;
    v0.9.5 plan 018 adds the ``field_validator`` to enforce
    known-kind membership at creation so the integrators don't
    silently get a dead-on-arrival subscription.
    """

    url: str
    filter: dict[str, object]
    description: str | None = None

    @field_validator("filter")
    @classmethod
    def _validate_filter_kind(cls, v: dict[str, object]) -> dict[str, object]:
        kind = v.get("kind")
        if not isinstance(kind, str):
            raise ValueError(
                "filter.kind is required and must be a string "
                f"(one of {sorted(_WEBHOOK_KNOWN_KINDS)})"
            )
        if kind not in _WEBHOOK_KNOWN_KINDS:
            raise ValueError(
                f"unknown webhook filter.kind={kind!r}; "
                f"expected one of {sorted(_WEBHOOK_KNOWN_KINDS)}"
            )
        return v
```

### Step 3 — Add 2 regression tests

`apps/api/tests/test_webhook_subscription_create.py` (NEW):

```python
"""v0.9.5 plan 018: filter.kind validator on WebhookSubscriptionCreate."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from gw2analytics_api.schemas import WebhookSubscriptionCreate


def test_create_accepts_known_kind():
    """``upload_completed`` is accepted."""
    payload = WebhookSubscriptionCreate(
        url="https://example.com/hook",
        filter={"kind": "upload_completed"},
    )
    assert payload.filter["kind"] == "upload_completed"


def test_create_rejects_unknown_kind():
    """Unknown kinds surface as 422 (close the dead-on-arrival pattern)."""
    with pytest.raises(ValidationError) as exc:
        WebhookSubscriptionCreate(
            url="https://example.com/hook",
            filter={"kind": "boop"},  # type: ignore[arg-type]
        )
    assert "unknown webhook filter.kind" in str(exc.value)
    assert "'boop'" in str(exc.value)


def test_create_rejects_missing_kind():
    """Missing ``kind`` key surfaces as 422 (integrator must be explicit)."""
    with pytest.raises(ValidationError) as exc:
        WebhookSubscriptionCreate(
            url="https://example.com/hook",
            filter={},  # type: ignore[arg-type]
        )
    assert "filter.kind is required" in str(exc.value)
```

---

## Verification commands

```bash
uv run ruff check apps/api
uv run mypy --no-incremental libs apps
uv run pytest apps/api/tests/test_webhook_subscription_create.py -v
uv run pytest apps/api/tests/test_webhooks_e2e.py -v
# Expected: existing webhook e2e tests still pass (they all use kind=upload_completed).
```

A worktree `git diff` against `44ea862` must show ONLY:
- `apps/api/src/gw2analytics_api/schemas.py` (add `_WEBHOOK_KNOWN_KINDS` + `_validate_filter_kind` method).
- `apps/api/tests/test_webhook_subscription_create.py` (NEW, 3 tests).
- `CONTRIBUTING.md` (1 short subsection on the kind validator).

## Maintenance note

- Future kinds (per-encounter, per-result) add to `_WEBHOOK_KNOWN_KINDS` + to the dispatcher's match table in `webhook_dispatch.py`. The 2-place pattern is the canonical "kind vocabulary" contract.
- The validator accepts ONLY the `kind` key for membership checking. Other filter keys (e.g. `upload_status`, `fight_result`) are accepted as-is for now; future plans can add per-key validators if the spec locks the contract.
- Pre-plan-018 subscriptions (those that landed before the validator) are NOT retroactively rejected. They keep their (potentially bogus) kind and the dispatcher's silent-skip continues to apply for them. This is the backward-compat contract: the validator is at CREATE time only.

## Escape hatches

- If a future plan needs to allow arbitrary `kind` values (e.g. for `is_development=true` deployments), gate the validator on a Settings flag (e.g. `Settings.allow_arbitrary_webhook_kind`). Out of scope here.
- If a future plan adds per-key validation (e.g. `upload_status` must be a known enum value), extend `_validate_filter_kind` into a `_validate_filter` that checks each key. Out of scope here.
