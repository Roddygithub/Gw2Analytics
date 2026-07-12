# Plan 034 — v0.10.15: defensive collapse of empty `?subscription_id=` in `webhooks.py`

**Status:** open
**Priority:** P3
**Impact:** LOW
**Confidence:** 1.0

## Finding

`apps/api/src/gw2analytics_api/routes/webhooks.py:294` accepts
`subscription_id: str | None` but in practice FastAPI parses
`?subscription_id=` (no value) as the empty string `""`. The
route's runtime behavior is correct — `if subscription_id:`
treats `""` as falsy → unfiltered query → returns all DLQ rows.
**But the typed contract leaks:**

1. A future maintainer reading `subscription_id: str | None`
   without reading the URL semantics might assume the
   function signature enforces the `None` semantics.
2. An integration test asserting `subscription_id is None`
   would fail when `subscription_id == ""`.

## Fix

Normalize at function entry:

```diff
 @router.get("/dlq", response_model=list[WebhookDlqOut])
 def list_webhook_dlq(
     subscription_id: str | None = None,
     limit: int = Query(100, ge=1, le=1000),
     offset: int = Query(0, ge=0),
     db: Session = Depends(get_session),  # noqa: B008
 ) -> list[WebhookDlqOut]:
+    # Normalize empty query string (``?subscription_id=``)
+    # to ``None`` so the ``if subscription_id is not None:``
+    # check below is type-contract-correct. FastAPI parses the
+    # empty query string as ``""`` (NOT as a missing param);
+    # both should mean "no filter". Centralising the collapse
+    # here makes the type contract enforceable in tests
+    # (assert subscription_id is None on ?subscription_id=).
+    subscription_id = subscription_id or None
     stmt = select(OrmWebhookDlq).order_by(OrmWebhookDlq.moved_to_dlq_at.desc())
-    if subscription_id:
+    if subscription_id is not None:
         stmt = stmt.where(OrmWebhookDlq.subscription_id == subscription_id)
```

## Tests

| Test | File | Type |
|------|------|------|
| `test_list_webhook_dlq_empty_subscription_id_filter_returns_all_rows` (NEW) | `apps/api/tests/test_webhooks_dlq.py` | integration |
| `test_list_webhook_dlq_with_subscription_id_filter_returns_only_match` (existing — must still pass) | `apps/api/tests/test_webhooks_dlq.py` | integration |

## Out of scope

- Other FastAPI routes with similar `str | None` query params
  (none in the round-2026-07-12 audit scope; defer to a future
  sweep if surfaced).

## Done criteria

- `uv run ruff check apps/api/src` GREEN
- `uv run mypy apps/api/src` GREEN
- New test PASS
- Existing `test_list_webhook_dlq_with_subscription_id_filter_returns_only_match` PASS (regression of the matching case)

## Maintenance note

Pre-fix runtime behavior was correct (`if subscription_id`
short-circuits both `None` and `""`). The fix is a
type-contract clarification; no wire-level behaviour change.

## Escape hatches

- A future FastAPI version that natively collapses empty query
  strings to `None` would let us drop this normalization — but
  FastAPI has signalled no such change. The 1-line collapse
  here is the durable contract.

## Dependency graph

Standalone — no inter-plan deps.

## Cross-references

- Finding sourced from `plans/AUDIT-2026-07-12-5d0d4d4.md` §"Open
  findings" O3.
