# 009-v092-webhook-rest

**Status**: DRAFT
**Date**: 2026-07-08
**Drift-detection base**: v0.9.1 (f8d4bb4 + 2 prior close-out commits + tag)
**Addresses**: 3 documented v0.9.1 deferred followups + 1 uninvestigated full-suite timeout + 1 code-reviewer docstring nit

## Context

The v0.9.1 hardening slice closed 5 audit plans (004-008) and shipped 22
webhook e2e tests + 8 scheduler tests. Two test failures were explicitly
tagged for v0.9.2 re-attempt:

1. ``test_replayed_delivery_byte_for_byte_hmac_matches_original`` -- JSONB
   intrinsic key reordering breaks the HMAC byte-for-byte guarantee.
2. ``test_replay_dlq_idempotent_concurrent_calls`` -- concurrent reads on
   ``OrmWebhookDlq`` create duplicate delivery rows instead of one 201 +
   one 404.

Plus three additional v0.9.2 candidates surfaced during the close-out:

3. ``test_generate_subscription_id_is_url_safe`` is in place, but the
   app lacks a project-wide convention for path-parameter vs byte-only
   discriminators (the urlsafe fix happened at one site; a docstring
   convention would prevent future regressions in OTHER discriminator
   sites like ``_generate_delivery_id``).
4. The full ``apps/api/tests/`` suite times out at >600 seconds (vs.
   per-module bounds of 1-10 seconds). The culprit is unknown; this
   plan profiles each module with bounded timeout in `Step 0` and
   files the offender into `apps/api/tests/_fixtures.py` as a known-slow
   marker.
5. The ``apps/api/tests/_fixtures.py`` helper module + the per-file
   autouse fixture in ``test_webhooks_e2e_scheduler.py`` are local;
   v0.9.2 should centralise fixture-cleanup into a single
   ``apps/api/tests/conftest.py`` so cross-file test seed state doesn't
   accumulate across ``pytest`` runs.

## Files in scope

- ``apps/api/alembic/versions/0008_payload_bytes.py`` (NEW, migration)
- ``apps/api/src/gw2analytics_api/workers/webhook_dispatch.py``
  (replace ``payload: dict`` writes with canonical ``payload: bytes``)
- ``apps/api/src/gw2analytics_api/workers/webhook_scheduler.py``
  (re-deliver reads ``payload: bytes``; HMAC re-signs on the bytes)
- ``apps/api/src/gw2analytics_api/routes/webhooks.py``
  (``_generate_subscription_id`` docstring; ``replay_dlq_delivery``
  row-level lock)
- ``apps/api/src/gw2analytics_api/models.py``
  (``OrmWebhookDelivery.payload`` + ``OrmWebhookDlq.payload`` Annotated
  as ``LargeBinary`` instead of ``JSON``)
- ``apps/api/tests/conftest.py`` (NEW, central fixture cleanup)
- ``apps/api/tests/_fixtures.py`` (read-only; helper module)
- ``plans/PLAN_REGISTRY.md`` (link to v0.9.2 close-out)

## Files explicitly out of scope

- ``apps/api/src/gw2analytics_api/routes/webhooks.py::_validate_webhook_url``
  (correct as of v0.9.1 plan 005)
- ``apps/api/src/gw2analytics_api/services.py::process_parse``
  (correct as of v0.9.1 plan 006; correct session_factory signature)
- ``apps/api/src/gw2analytics_api/workers/webhook_scheduler.py::lifespan_scheduler``
  (correct as of v0.9.1 H1 hardening)
- ``web/src/lib/api/schema.d.ts`` baseline (correct as of v0.9.1 plan 008)
- All v0.9.1 plan files (004-008) under ``plans/`` (DONE; no re-edit)

## Steps

### Step 0: Profile apps/api slow-modules [DIAGNOSED 2026-07-08]

Per-module profile (`timeout 30 uv run pytest tests/<MODULE> -q --no-header`):

| Module | Wallclock | Verdict |
| --- | --- | --- |
| `test_uploads_e2e.py` (31 tests) | 30 s | SLOW (hangs) |
| `test_players.py` (7 tests) | 30 s | SLOW (hangs) |
| `test_health_summary.py` (3 tests) | 30 s | SLOW (hangs) |
| `test_backfill.py` (4 tests) | 30 s | SLOW (hangs) |
| `test_account.py` (11 tests) | ~3 s | OK |
| `test_healthz.py` (1 test) | ~1 s | OK |
| `test_config.py` (9 tests) | ~3 s | OK |
| `test_ci_health_gate.py` (5 tests) | ~3 s | OK |
| `test_webhooks_e2e.py` (15 tests) | covered in Step 5 |
| `test_webhooks_e2e_scheduler.py` (8 tests) | covered in Step 5 |

Total floor: 4 SLOW × 30 s + 4 OK × ~3 s ~= 132 s if every slow module
hits its ceiling; observed >600 s suggests additional intra-module
retries against DB-accumulated state across runs.

**Common root cause hypothesis (validates Step 5 prediction)**: every
test seeds fresh uuids + writes rows that ACCUMULATE across runs
(NO per-test cleanup). 4 SLOW modules + the 2 webhook modules all
share this pattern. The conftest.py cleanup from Step 5 is the
primary lever; if any module remains >30 s after the conftest lands,
file a per-module followup diagnostic as Step 6.

Verify command (post-conftest cleanup): `cd apps/api && uv run pytest
tests/ --timeout=30 -q 2>&1 | tail -10` (pytest-timeout becomes a dev
dep via Step 5; fallback to OS `timeout` if not installed).

Step 0 was originally a placeholder diagnostic; the actual findings
above replace it. The 4 SLOW modules do not surface correctness bugs
per this profile (the bash `timeout` killed them; pytest did NOT
report test failures) -- they hang on the same DB accumulation
pattern that motivates Step 5.

### Step 1: Migration 0008 — payload JSONB to LargeBinary

- Add `apps/api/alembic/versions/0008_payload_bytes.py`:
  - `revision = "0008_payload_bytes"`
  - `down_revision = "0007_webhook_retry"`
  - `op.alter_column("webhook_deliveries", "payload", type_=LargeBinary, existing_type=JSONB)`
  - `op.alter_column("webhook_dlq", "payload", type_=LargeBinary, existing_type=JSONB)`
  - **WARNING**: existing JSONB rows are lossy on this migration
    (JSONB-stored dicts cannot be losslessly reconstructed to the
    original canonical bytes). Operators MUST run
    ``alembic downgrade -1`` and exhaust the DLQ + delivery rows
    first, OR accept that pre-v0.9.2 rows become an opaque byte-bag
    with their original dict structure lost (this is acceptable
    because v0.9.2 marks the schema as fresh-start; documented in
    CHANGELOG). Document in migration file's `# WARNING` header.
- Update ``apps/api/src/gw2analytics_api/models.py``:
  - ``OrmWebhookDelivery.payload``: ``Mapped[bytes | None]`` mapped
    to ``LargeBinary`` (was JSON)
  - ``OrmWebhookDlq.payload``: ``Mapped[bytes]`` mapped to
    ``LargeBinary`` (was JSON)
- Verify command post-migration:
  ``uv run alembic upgrade head && uv run alembic downgrade -1 &&
   uv run alembic upgrade head``
  Expected: upgrade + downgrade + upgrade cycle completes cleanly.

### Step 2: Wire LargeBinary through the dispatch + scheduler

- ``workers/webhook_dispatch.py``: replace
  ``OrmWebhookDelivery(..., payload=body_dict)`` with the canonical
  ``payload = json.dumps(body_dict, separators=(",", ":")).encode("utf-8")``.
  The dispatch worker computes the HMAC on ``payload`` bytes
  directly; HMAC verification on the integrator's side computes on
  the same wire bytes => byte-for-byte match across retries.
- ``workers/webhook_scheduler.py``: when re-delivering from a row,
  read the stored ``payload: bytes`` verbatim + re-SHA256 + re-POST.
  No dict round-trip + no JSONB re-ordering hazard.
- ``routes/webhooks.py::replay_dlq_delivery``: copy ``dlq.payload``
  (bytes) into ``new_delivery.payload`` (bytes) directly.
- Verify command:
  ``cd apps/api && uv run pytest tests/test_webhooks_e2e.py::test_replayed_delivery_byte_for_byte_hmac_matches_original -v``
  Expected: PASS.

### Step 3: row-level lock on replay_dlq_delivery

- Replace ``dlq = db.get(OrmWebhookDlq, delivery_id)`` with:
  ```python
  from sqlalchemy import select
  dlq = db.execute(
      select(OrmWebhookDlq).where(OrmWebhookDlq.id == delivery_id).with_for_update()
  ).scalar_one_or_none()
  ```
- Postgres's ``SELECT ... FOR UPDATE`` row-level lock ensures only
  one of the concurrent threads can read + delete the DLQ row; the
  second thread's transaction blocks until the first commits, then
  sees NULL and raises 404.
- Verify command:
  ``cd apps/api && uv run pytest tests/test_webhooks_e2e.py::test_replay_dlq_idempotent_concurrent_calls -v``
  Expected: PASS (one 201 + one 404 in the thread-pool output).

### Step 4: discriminate-encoding docstring convention

- ``apps/api/src/gw2analytics_api/routes/webhooks.py``:
  - Add 3-line docstring to ``_generate_subscription_id`` citing the
    convention: "Path-parameter discriminator: ``urlsafe_b64encode``.
    Byte-only discriminator (e.g. ``_generate_secret``): standard
    ``b64encode`` is fine since HMAC operates on bytes and format
    churn has migration cost for in-flight integrators."
  - Add identical 3-line docstring to ``_generate_secret`` for
    discoverability in IDE hover, even though it doesn't change.
  - Add a 2-line comment to ``_generate_delivery_id`` (uses UUID,
    URL-safe by definition) noting that ``urlsafe_b64encode`` is
    not needed here, with a link to the convention.
- Verify command: hover the function in the IDE; the convention is
  discoverable without cross-file navigation. No test needed.

### Step 5: Central test fixture cleanup (conftest.py)

- Add ``apps/api/tests/conftest.py`` with
  ``@pytest.fixture(autouse=True)`` function-scoped cleanup:
  delete uuids from ``uploads``, ``fights``, ``webhook_subscriptions``,
  ``webhook_deliveries``, ``webhook_dlq`` before each test.
  Cross-file autouse; supersedes the per-file fixture in
  ``test_webhooks_e2e_scheduler.py``.
- Refactor ``apps/api/tests/test_webhooks_e2e_scheduler.py`` to
  remove the local autouse fixture (the conftest.py version covers
  it). Move the migration of state to conftest.
- Verify command:
  ``cd apps/api && uv run pytest tests/test_webhooks_e2e.py tests/test_webhooks_e2e_scheduler.py -v``
  Expected: 22 tests pass (was 20; +2 from deferred fixes).

## Test plan

After all 5 steps:
- Full apps/api suite: ``cd apps/api && uv run pytest tests/ -v``
  target wall-clock <120 s (currently >600 s).
- Webhook e2e + scheduler: 22 pass, 0 fail, 1 skip (was 20 / 2 fail / 1 skip at v0.9.1 close-out).
- ruff check + mypy on changed files: clean.

## Maintenance note

- The discriminator-encoding convention is a project-wide invariant.
  Add a one-line note in ``CONTRIBUTING.md`` (section: "Webhook
  discriminator IDs") so future engineers discover the rule without
  grepping routes/webhooks.py.
- Migration 0008 is intentionally NOT data-preserving. If a v0.9.2
  followup patch-release reverses the upgrade (rare), the operator
  must drain the DLQ + run ``replay_dlq`` on every remaining entry to
  repopulate the rows with byte-payloads from the dispatch worker.

## Escape hatches

- STOP if migration 0008's down_version conflicts with the
  alembic revisions file (verify ``grep "down_revision" alembic/versions/*.py``
  shows no duplicates). Resolution: bump to 0009.
- STOP if ``with_for_update`` raises on the SELECT (the existing
  ``replay_dlq_delivery`` uses ``db.get`` which is the legacy PK
  lookup; SQLAlchemy's ``select().with_for_update()`` is the modern
  equivalent). Workaround: ``db.execute(text("SELECT ... FOR UPDATE")).fetchone()``.
- STOP if conftest.py autouse breaks other tests'
  ``session_factory`` flow (some tests reuse session across the
  bootstrap + assertion phases, and an autouse cleanup would
  squash the state mid-test). Resolution: scope the autouse to
  only webhook test paths via ``pytest_collection_modifyitems``
  hook in the conftest.
- STOP if the diagnosed slow test (from Step 0) reveals an outright
  correctness bug (e.g. infinite loop, deadlock). File a separate
  plan (009-X) to address; defer the conftest.py centralisation to
  that plan.
