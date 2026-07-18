# Plan 160 — upload 500 on `fight_id` collision

**Source:** E2E journey finding #3 (`plans/E2E-JOURNEY-2026-07-11.md`). **Severity:** MED. **Effort:** S.

## Problem

`fight_id` is content-derived, so two DIFFERENT uploads (distinct upload `sha256`) that contain the SAME parsed fight (e.g. the same log re-zipped) both try to `INSERT` the same `fights` primary key → `sqlalchemy.exc.IntegrityError (UniqueViolation "fights_pkey")` → unhandled → **HTTP 500**. The existing sha256 dedup only covers the *same-bytes* re-upload, not same-fight-different-wrapper. Reproduced in the E2E (small + medium wrapped the same inner fight).

## Options

- **(a) Idempotent** — on `fight_id` collision, treat as success: link the new `Upload` row to the existing fight, return its id. Best UX (matches the "re-upload is harmless" model), but needs a decision on whether to overwrite the fight's blob/summaries.
- **(b) 409 Conflict** — catch the `IntegrityError`, return `409` + `{existing_fight_id}`. Simplest, honest, but the client must handle 409.

## Suggested fix

Wrap the fight insert in the parse/persist path (`services.py`) with a `try/except IntegrityError`; on collision, `rollback()` and resolve to the existing fight (option a) or raise `HTTPException(409, ...)` (option b). Add a regression test uploading the same fight via two distinct wrappers.

**Decision needed:** (a) vs (b) — Arthur/Roddy's call.
