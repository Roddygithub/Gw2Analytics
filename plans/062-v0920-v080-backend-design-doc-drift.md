# Plan 062 — v0.9.20: `docs/v0.8.0-backend-design.md` schema + version + future-work drift

## Drift base

`44ea862`. Docs cleanup only — no code changes, no migration.

## Surface

`docs/v0.8.0-backend-design.md` (the canonical webhook spec doc
that drove the v0.9.0 + v0.9.1 + v0.9.2 implementation),
`apps/api/src/gw2analytics_api/models.py` (for the current
`OrmWebhookDelivery` + `OrmWebhookDlq` shape),
`apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` (for
the canonical `USER_AGENT` + worker state transitions),
`apps/api/alembic/versions/0007_webhook_retry.py` (for the
2 added columns + the rationale).

## Finding

The design doc has 4 drift sub-issues vs the v0.9.2 code:

1. **§3.4 outbound POST User-Agent is `Gw2Analytics-Webhook/0.8.0`**
   (line ~95). The current `webhook_dispatch.py` + `webhook_scheduler.py`
   constants are `Gw2Analytics-Webhook/0.9.0` (per plan 052's
   canonical `USER_AGENT = "Gw2Analytics-Webhook/0.9.1"`). The
   wire contract is informational, but a new integrator who reads
   the doc and writes a User-Agent filter on their side will get
   the wrong version.

2. **§4 schema for `webhook_deliveries` is missing 2 columns**
   (`next_attempt_at` + `payload`) that were added in v0.9.1
   migration `0007_webhook_retry.py`. The doc lists only
   `id / subscription_id / upload_id / attempt / status_code /
   error / delivered_at`. The current `OrmWebhookDelivery` has
   all 7 + `next_attempt_at: datetime | None` (indexed for
   polling) + `payload: bytes | None` (LargeBinary for
   byte-for-byte HMAC fidelity).

3. **§4 schema has `delivered_at TIMESTAMPTZ NOT NULL DEFAULT now()`**
   but the current `OrmWebhookDelivery.delivered_at` is
   `Mapped[datetime | None]` (NULLable). The semantic changed
   during v0.9.1: `delivered_at` is now NULL until success (was
   previously "set on every attempt" per the v0.8.0 design).

4. **§5 worker design conflates success + failure state
   transitions** ("increments `attempt` and `delivered_at = now() +
   exponential_backoff(attempt)`"). The current code on failure:
   - increments `delivery.attempt`
   - sets `next_attempt_at = now() + backoff[attempt]`
   - leaves `delivered_at = NULL` (it's NULL until success)
   - on success: sets `delivered_at = utcnow()`

5. **§6 future-work list marks 3 items as "v0.9.0+ enhancements"**
   that have shipped in v0.9.1 + v0.9.2:
   - "Webhook replay / redelivery UI" — shipped as
     `POST /api/v1/webhooks/dlq/{delivery_id}/replay` in v0.9.1.
   - "GraphQL subscription channel" — NOT shipped (this one is
     still future).
   - "Per-event-kind filtering" — NOT shipped (still future).

## Fix

The design doc is a SPEC doc (it has §3 API contract + §4 schema
+ §5 worker design). New implementers who read it to understand
the current behavior would get WRONG information. The 4 drift
issues are real and need to be fixed.

1. **§3.4 User-Agent**: change `Gw2Analytics-Webhook/0.8.0` to
   `Gw2Analytics-Webhook/0.9.2` (the current code's canonical
   value per plan 052's `_pool.USER_AGENT` + the
   `apps/api/src/gw2analytics_api/_version.py` post-plan-042
   import).

2. **§4 schema**: add 2 new columns to the `webhook_deliveries`
   CREATE TABLE statement. Update the `delivered_at` column to
   be NULLable (no NOT NULL constraint). Add a footnote to the
   schema table:
   ```
   -- v0.9.1: added ``next_attempt_at`` (wall-clock instant the
   -- scheduler re-attempts a failed delivery) + ``payload``
   -- (canonical outbound body bytes for byte-for-byte HMAC
   -- fidelity across retries + replays). See migration 0007.
   ```

3. **§5 worker design**: split the bullet "On non-2xx / network
   error" into 2 sub-bullets (one for the row update, one for
   the attempt counter). Add the explicit "leaves `delivered_at`
   NULL until success" semantic.

4. **§6 future-work list**: mark the 2 shipped items with "✅
   shipped in v0.9.1" annotations. Keep the "GraphQL
   subscription channel" as "future" (the v0.9.x does not ship
   this).

5. **Add a "Last refreshed at v0.9.2" footer** at the bottom of
   the doc so a future reader knows the doc is current.

## Risks

- The User-Agent value `Gw2Analytics-Webhook/0.9.2` is the
  plan-052 canonical value, but the current code (pre-plan-052)
  uses `Gw2Analytics-Webhook/0.9.0` (per `webhook_dispatch.py`).
  After plan 052 lands, the code's `USER_AGENT` constant is
  `Gw2Analytics-Webhook/0.9.1` (the canonical central value).
  The doc's "0.9.2" matches the version in `pyproject.toml`,
  not the code's literal `0.9.1` constant. The discrepancy is
  fine (the code's `0.9.1` is the post-plan-052 canonical
  value; the `0.9.2` is the release version). The doc could
  use either; `0.9.2` is the version a new integrator sees
  when they read the package metadata.
- The schema doc is a "design AS-WRITTEN at v0.8.0" — the v0.9.x
  additions are documented in the v0.9.1 close-out CHANGELOG.
  A future audit may argue the doc should be FROZEN at v0.8.0
  (with a banner saying "see current code for v0.9.x additions")
  rather than refreshed. The plan picks the refresh option
  because the spec doc is the canonical reference for new
  implementers; freezing it would force implementers to read
  both the doc + the CHANGELOG to understand the current
  behavior.

## Tests

1. `test_doc_user_agent_is_0_9_2` — read the doc; assert the
   User-Agent header value is `Gw2Analytics-Webhook/0.9.2`.
2. `test_doc_schema_has_next_attempt_at` — read the doc's §4
   schema; assert the `next_attempt_at` column is documented.
3. `test_doc_schema_has_payload` — read the doc's §4 schema;
   assert the `payload` column is documented.
4. `test_doc_schema_delivered_at_is_nullable` — read the doc's
   §4 schema; assert the `delivered_at` column is NULLable
   (no `NOT NULL` constraint).
5. `test_doc_worker_failure_uses_next_attempt_at` — read §5;
   assert the failure path mentions `next_attempt_at` (not
   `delivered_at`).
6. `test_doc_future_work_marks_replay_shipped` — read §6; assert
   the "Webhook replay / redelivery UI" entry has a
   "shipped in v0.9.1" annotation.
7. `test_doc_has_last_refreshed_footer` — read the doc; assert
   the "Last refreshed at v0.9.2" footer is present.

## Rejected alternatives

- **Freeze the doc as "v0.8.0 design AS-WRITTEN"** with a banner
  saying "see current code for v0.9.x additions": tempting
  (preserves history). The doc is a SPEC doc (§3 API + §4
  schema + §5 worker); freezing it would force new implementers
  to read both the doc + the CHANGELOG to understand the current
  behavior. The refresh option is the canonical fix.
- **Delete the doc + consolidate into CHANGELOG**: out of scope
  (the CHANGELOG is a release log, not a spec). The spec doc
  has independent value (API contract + schema + worker design
  in one place).
- **Move the schema doc to a separate `docs/v0.9.x-webhook-schema.md`**
  + add a "see also" pointer: out of scope. The schema is
  tightly coupled to the API contract (§3) + the worker design
  (§5); a split would scatter the related material.
- **Document the `next_attempt_at` + `payload` columns in the
  CHANGELOG only (no doc update)**: the CHANGELOG entry already
  exists (per the ROADMAP §2.1 archival note). The spec doc
  is the canonical reference for new implementers; the
  CHANGELOG is for historical context. Both are needed.
- **Add the "Last refreshed at" footer in a CI drift check**:
  out of scope (the footer is a human-curated marker, not a
  machine-checkable property).
