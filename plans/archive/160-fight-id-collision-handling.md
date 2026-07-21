# Plan 160 — upload 500 on `fight_id` collision

**Source:** E2E journey finding #3 (`plans/E2E-JOURNEY-2026-07-11.md`). **Severity:** MED. **Effort:** S.

## Problem

`fight_id` is content-derived, so two DIFFERENT uploads (distinct upload `sha256`) that contain the SAME parsed fight (e.g. the same log re-zipped) both try to `INSERT` the same `fights` primary key → `sqlalchemy.exc.IntegrityError (UniqueViolation "fights_pkey")` → unhandled → **HTTP 500**. The existing sha256 dedup only covers the *same-bytes* re-upload, not same-fight-different-wrapper. Reproduced in the E2E (small + medium wrapped the same inner fight).

## Options

- **(a) Idempotent** — on `fight_id` collision, treat as success: link the new `Upload` row to the existing fight, return its id. Best UX (matches the "re-upload is harmless" model), but needs a decision on whether to overwrite the fight's blob/summaries.
- **(b) 409 Conflict** — catch the `IntegrityError`, return `409` + `{existing_fight_id}`. Simplest, honest, but the client must handle 409.

## Suggested fix

Wrap the fight insert in the parse/persist path (`services.py`) with a `try/except IntegrityError`; on collision, `rollback()` and resolve to the existing fight (option a) or raise `HTTPException(409, ...)` (option b). Add a regression test uploading the same fight via two distinct wrappers.

**Decision (Roddy, this PR):** Option **(a) idempotent, No-Alembic variant.**

Rationale:
1. **Async impossibility of (b)**: `services/parse.py` runs in the Arq worker AFTER the `POST /uploads` route has already returned `201 Created` with the new `Upload.id`. By the time the worker discovers the `fight_id` collision (via `sqlalchemy.exc.IntegrityError`), the HTTP context is gone — a `409` response is a no-op regardless of what the parse layer does. The client must poll `GET /uploads/{id}` to discover the outcome either way.
2. **Schema lockdown**: `OrmFight.upload_id` is a single FK (one fight can only point to one Upload row). A true many-to-many schema would require dropping `fights.upload_id` + adding `uploads.fight_id` via an Alembic migration (visible cascade risk on existing rows). The No-Alembic variant avoids that surface while preserving the UX benefit.
3. **Audit value**: every (a) variant creates a new `UploadRow`, providing audit history ("user X re-uploaded fight Y at time Z") without a schema change. The `upload.error_message` carries the existing `fight_id` so the analyst can pre-empt the second poll via a `GET /fights/{cf.id}` deep-link.

Implementation outline (`apps/api/src/gw2_analytics_api/services/fight_persistence.py` + `services/parse.py`):
- Wrap the `_save_fight()` + `_persist_event_blob()` calls in `try/except sqlalchemy.exc.IntegrityError`.
- On catch: `db.rollback()`, set `upload.status = "failed"`, `upload.error_message = f"Duplicate fight: existing fight_id = {cf.id} (same parsed fight, different wrapper)"`, `db.commit()`.
- Event-blob storage (`_persist_event_blob`) is naturally skipped on rollback — no orphaned blob in MinIO since the rollback nulls the `Upload` -> event-blob mapping.

Regression test (`apps/api/tests/routes/test_uploads_collision.py` NEW):
- Upload a parsed fight (`test_log.zevtc`) → poll until `status == "completed"` → capture `cf.id`.
- Re-zip the same log (different `sha256`, identical parsed `fight_id`) → upload → poll until terminal status.
- Assert: `status == "failed"` + `error_message.contains(cf.id)` + the test does NOT trigger `HTTPException(500)`.

Acknowledged tradeoff: client experiences a brief "why is this failed?" moment after the second upload. The `error_message` carrying the existing `fight_id` reduces friction (the analyst can deep-link to the canonical result). A future PR can switch to the True-Idempotency Alembic variant if audit log pain is larger than expected.

Cycle anchor: Wave 2 — v0.10.26 (per `plans/167-v01026-pre-cycle-anchor.md`). Depends on Phase 6 v2 parser-stream maturity (the collision path is parser-determined).
