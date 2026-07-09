# Plan 079 — v0.9.25 — `routes/webhooks.py` 3× bare `db.commit()` wrap with `try/except SQLAlchemyError`

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Addressed finding (MED reliability + DX):** `apps/api/src/gw2analytics_api/routes/webhooks.py` has **3 bare `db.commit()` calls** (no `try/except SQLAlchemyError`) — `create_webhook` + `revoke_webhook` + `replay_dlq_delivery`. The same pattern was flagged + fixed in `services.py::process_parse` (v0.9.14 plan 045) and in `backfill.py::run_backfill` (v0.9.10 plan 034). The `routes/webhooks.py` route layer was missed in those sweeps because plan 045 focused on `services.py` and plan 034 focused on `backfill.py`. Fix wraps each of the 3 commits with `try/except SQLAlchemyError`, on failure roll back + raise `HTTPException(503, ...)` with a clear `code="database_unavailable"` (matches the plan 045 contract for the BG task path).

The 3 commits and their failure-mode impact:

| # | Route | Commit target | Failure-mode impact (today) | Fix return |
|---|---|---|---|---|
| 1 | `POST /api/v1/webhooks` | `db.add(new_sub); db.commit()` | Transient commit failure (Postgres connection drop, serialisation failure, pool timeout) → 500 with no logged context → user thinks their webhook was created but it wasn't; retries with the same payload → 422 (URL already taken) only if the half-committed row is visible (transactional), or duplicated subscription if the row didn't commit | 503 `database_unavailable` + the `subscription_id` (the pre-commit row's discriminator) so the operator can replay deterministically |
| 2 | `DELETE /api/v1/webhooks/{subscription_id}` | `row.revoked_at = _utcnow(); db.commit()` | Transient commit failure → 204 returned (FastAPI doesn't realise the commit failed because the exception propagates) — operator believes the webhook is revoked but the subscription is still active → continues receiving deliveries against a URL the operator thought they killed | 503 `database_unavailable` + the `subscription_id` so the operator can retry deterministically |
| 3 | `POST /api/v1/webhooks/dlq/{delivery_id}/replay` | `db.add(new_delivery); db.delete(dlq); db.commit()` | Transient commit failure → 201 returned (the add + delete are queued in the UoW but the COMMIT failed) → the DLQ entry is rolled back AND the new delivery is rolled back; operator believes the replay happened but the DEAD delivery is still in DLQ + no fresh delivery was created → silent failure | 503 `database_unavailable` + `delivery_id` + the `subscription_id`; the operator can retry the DLQ-replay (the row-level lock from plan 009 Step 3 + the canonical 404-if-already-replayed invariant makes the retry idempotent) |

The pattern is identical to plan 045's `services.py::process_parse` (the BG task version) and plan 034's `backfill.py::run_backfill` (the per-fight-commit version). The route layer was the third place the pattern was used and the third place it needs to be hardened.

## File changes

### 1 file edited + 1 NEW test file

**`apps/api/src/gw2analytics_api/routes/webhooks.py`** — 3 surgical edits to the existing 3 routes. The shape of each edit:

```python
# Before (per the current file):
db.add(new_sub)
db.commit()
return WebhookSubscriptionCreatedOut(...)

# After (the plan 045 contract applied):
db.add(new_sub)
try:
    db.commit()
except SQLAlchemyError as exc:
    logger.exception("create_webhook commit failed: subscription_id=%s", new_sub.id)
    db.rollback()
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "database_unavailable",
            "message": "Transient database error during subscription create; please retry.",
            "subscription_id": new_sub.id,  # pre-commit row discriminator
        },
    ) from exc
return WebhookSubscriptionCreatedOut(...)
```

The `db.rollback()` defends against the case where the exception is post-flush-pre-commit (the half-staged row is on the UoW but not on the WAL); the rollback reverses any staged writes in this transaction.

Then a corresponding edit to `revoke_webhook` and `replay_dlq_delivery` with the same shape.

The `HTTPException(503, ...)` detail follows the canonical pattern from `apps/api/src/gw2analytics_api/routes/uploads.py` (which already uses `code="upload_too_large"`, `code="bad_zevtc"`, etc. via `HTTPException` detail dicts).

### Test changes

**NEW `apps/api/tests/test_webhooks_routes_e2e.py`** with 3 hermetic tests covering the 3 surfaces:

| # | Test | Asserts |
|---|---|---|
| 1 | `create_webhook` returns 503 + `code="database_unavailable"` when `db.commit()` raises `OperationalError` | The route catches the exception + DB rolls back + the response carries the pre-commit `subscription_id` |
| 2 | `revoke_webhook` returns 503 + `code="database_unavailable"` when `db.commit()` raises `OperationalError` | The route catches the exception + DB rolls back + the response carries the `subscription_id` + the row's `revoked_at` remains `None` (verified via `db.refresh(row)` after the rollback) |
| 3 | `replay_dlq_delivery` returns 503 + `code="database_unavailable"` when `db.commit()` raises `OperationalError` | The route catches the exception + DB rolls back + both `OrmWebhookDelivery` (new) and `OrmWebhookDlq` (deleted) are unchanged after the rollback (verified via `db.get(...)` for both) |

The pattern matches `test_uploads_e2e.py`'s monkeypatch-on-`db.commit` hermetic tests added in plan 045.

## Considered and rejected

- **Alternative: extend `_commit_with_rollback_and_log(...)` helper to all 3 commit sites** — DRY win (3 places share the same 5-line try/except boilerplate). Per plan 045 + plan 034 precedent, each commit site is inlined because the rollback semantics + the response shape differ per route (commit #1 has a `WebhookSubscriptionCreatedOut` to build; commits #2 + #3 return None / a different response). The plan inlines the pattern with a docstring pointer to plans 045 + 034 + 079 as the canonical places to consult.
- **Alternative: configure the SQLAlchemy engine with `pool_pre_ping=False` and rely on the next request to recover** — out of scope for the route layer; the plan 040 SQLAlchemy pool config already sets the canonical knobs (per-request session + `pool_pre_ping=True`).
- **Alternative: return 500 (the FastAPI default) instead of 503** — `503 Service Unavailable` is the canonical HTTP code for "the server is temporarily unable to handle the request" (RFC 9110 §15.6.4); `500 Internal Server Error` is for "the server encountered an unexpected condition" (RFC 9110 §15.6.1). A transient commit failure is the former, not the latter.
- **Alternative: catch the exception in a FastAPI exception handler** (an `app.add_exception_handler(SQLAlchemyError, ...)` registration in `main.py` per plan 042's hardening posture) — tempting (DRY across all 3 commit sites). The handler would need to know the per-route context (the `subscription_id` for #1, the `delivery_id` for #3) to build the response detail; the context is only available inside the route function. The plan inlines the try/except per site.
- **Alternative: re-raise the `SQLAlchemyError` and rely on FastAPI's default 500** — restates the status quo; the user-visible 500 has no context for the operator to diagnose.
- **Alternative: add a `try / finally db.rollback()` to abort the transaction in the failure path** — the rollback-on-exception is the canonical pattern; the `finally` would roll back even on SUCCESS (which would erase the just-committed write). The `except` is the right scope.

## Effort

`S` — 1 file edit (3 surgical try/except insertions in 3 routes) + 1 NEW test file (3 hermetic tests). All additive at the per-route level. Pattern matches plan 045 + plan 034. Backwards-compatible (the 3 commits still commit on success; only the failure path is hardened). Independent of plans 077 + 078.
