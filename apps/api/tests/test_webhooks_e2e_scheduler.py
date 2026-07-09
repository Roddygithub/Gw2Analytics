"""Plan 007 (v0.9.1, re-attempt) webhook scheduler multi-tick DLQ-promotion test.

The original test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts
shipped as a ``pytest.skip`` placeholder in
``apps/api/tests/test_webhooks_e2e.py`` (see that module's docstring +
CHANGELOG ``### Known followup``). The in-session failure mode was a
nested ``with time_machine.travel + with _respx.mock`` block whose
inner statements kept getting re-indented to 12-space during cleanup
breaks, breaking Python parsing. The followup escapes the footgun by
moving the test to a **standalone module** where the ``with``-block
structure stays **flat**: the ``_respx.mock`` is the OUTERMOST context
manager; each ``time_machine.travel`` enters and exits once per tick.

Scheduler semantics (verified against
``apps/api/src/gw2analytics_api/workers/webhook_scheduler.py``):

- ``_BACKOFF_BY_ATTEMPT: dict[int, int] = {1: 1, 2: 10, 3: 100}`` —
  the dict key is the **post-increment** attempt count, so a failure
  at attempt=1 schedules the next attempt (now attempt=2) ``1`` + ``9``
  = ``10`` seconds out (NOT 1s; the index is by the new attempt).
- ``_MAX_ATTEMPTS = 3`` — max attempts is 3 OR (``_attempt_retry``
  bumps ``delivery.attempt += 1`` BEFORE the POST, so the boundary
  check is on the post-increment value).
- After ``_attempt_retry`` returns False AND
  ``delivery.attempt >= _MAX_ATTEMPTS``, the outer
  ``process_scheduled_retries`` calls ``_promote_to_dlq(db, delivery)``
  which ``db.add(OrmWebhookDlq(...)); db.delete(delivery)`` then
  commits at the end of the function.

Sequence of THIS test (``_BASE_TIME`` = seeded deliverable ``next_attempt_at``):

- Seed: ``OrmWebhookDelivery(id=..., attempt=1, next_attempt_at=_BASE_TIME,
  status_code=NULL, error="non-2xx response: 500", payload=...)``.
- Tick 1 (base): ``process_scheduled_retries`` with the respx HTTP 500
  mock → ``_attempt_retry`` fails → ``delivery.attempt = 2`` →
  ``next_attempt_at = _BASE_TIME + 10s`` (backoff index ``2``).
- Tick 2 (``_BASE_TIME + 10s``): ``process_scheduled_retries`` →
  ``_attempt_retry`` fails → ``delivery.attempt = 3`` → since
  ``delivery.attempt >= _MAX_ATTEMPTS`` (3 >= 3), the outer function
  calls ``_promote_to_dlq`` → delivery row deleted, ``OrmWebhookDlq``
  row inserted with the same id.

Each tick is wrapped in a SEPARATE ``time_machine.travel`` context
manager so the scheduler's internal ``_utcnow()`` sees the advanced
clock without invasive mocking of the worker module.

See ``apps/api/tests/test_webhooks_e2e.py::
test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts``
for the stub-by-name pointer to this module.
"""

from __future__ import annotations

import json as _json
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import respx as _respx
import time_machine

from gw2analytics_api.crypto import encrypt_webhook_secret
from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.models import (
    UPLOAD_STATUS_COMPLETED,
    OrmFight,
    OrmWebhookDelivery,
    OrmWebhookDlq,
    OrmWebhookSubscription,
    Upload,
)
from gw2analytics_api.workers.webhook_scheduler import process_scheduled_retries

_BASE_TIME = datetime(2026, 7, 8, 0, 0, 0, tzinfo=UTC)


@pytest.fixture
def session_factory() -> Any:
    """Return the process-wide SQLAlchemy sessionmaker bound to the app engine.

    Tests use it both as a seed context (inserting subscriptions +
    deliveries via raw ORM) AND as the ``session_factory`` argument
    to :func:`process_scheduled_retries`. Each ``with session_factory() as db:``
    opens a fresh transaction.
    """
    return get_sessionmaker()


def _bootstrap_webhook_environment(
    session_factory: Any,
    target_url: str = "https://93.184.216.34/webhook",
) -> tuple[str, str, str]:
    """Seed an active subscription + a completed upload + a parsed fight.

    Returns ``(subscription_id, upload_id, fight_id)``. The webhook
    target URL is a public IPv4 literal (``93.184.216.34``) so the
    v0.9.1 SSRF block (plan 005) classifies it as ``is_global=True``
    and lets it through without a DNS lookup. ``respx`` intercepts
    the request before any real outbound traffic happens.
    """
    sub_id = f"whsub_{_uuid.uuid4()}"
    upload_id = _uuid.uuid4()
    fight_id = f"fight_{_uuid.uuid4()}"
    # uuid4-derived sha so re-runs against an accumulated test DB
    # don't hit Upload.sha256 UniqueViolation (the v0.9.1 close-out
    # TEST-COUNT bump moved this from hardcoded "a" * 64 to uuid per
    # the test-fixture isolation follow-up).
    sha = _uuid.uuid4().hex

    with session_factory() as seed_db:
        sub = OrmWebhookSubscription(
            id=sub_id,
            url=target_url,
            description="plan-007 scheduler test subscription",
            ciphertext=encrypt_webhook_secret("whsec_" + "s" * 32),
        )
        sub.filter_payload = {"kind": "upload_completed"}
        sub.created_at = _BASE_TIME
        seed_db.add(sub)

        upload = Upload(
            id=upload_id,
            sha256=sha,
            original_filename="plan007_scheduler_fixture.zevtc",
            size_bytes=0,
            status=UPLOAD_STATUS_COMPLETED,
        )
        seed_db.add(upload)
        seed_db.flush()

        fight = OrmFight(
            id=fight_id,
            upload_id=upload_id,
            build_version="0",
            encounter_id=0,
            agent_count=0,
            started_at=_BASE_TIME,
            game_type=1,
        )
        seed_db.add(fight)
        seed_db.commit()

    return sub_id, str(upload_id), fight_id


def _seed_failed_delivery(
    session_factory: Any,
    subscription_id: str,
    upload_id_str: str,
    *,
    next_attempt_at: datetime | None = _BASE_TIME,
    attempt: int = 1,
) -> str:
    """Insert a single ``OrmWebhookDelivery`` row at attempt=N pending retry.

    Mirrors the state the dispatch worker would leave after a failed
    initial POST (status_code NULL, error="non-2xx response: 500",
    ``next_attempt_at`` defaults to ``_BASE_TIME`` so tick 1 is
    immediate). Returns the delivery id (``dly_<uuid>``).
    """
    delivery_id = f"dly_{_uuid.uuid4()}"
    with session_factory() as seed_db:
        seed_db.add(
            OrmWebhookDelivery(
                id=delivery_id,
                subscription_id=subscription_id,
                upload_id=upload_id_str,
                attempt=attempt,
                status_code=None,
                error="non-2xx response: 500",
                next_attempt_at=next_attempt_at,
                payload=_json.dumps(
                    {
                        "kind": "upload_completed",
                        "upload_id": upload_id_str,
                        "fight_id": "fixture-fight",
                        "sha256": "a" * 64,
                        "started_at": _BASE_TIME.isoformat(),
                    },
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
        )
        seed_db.commit()
    return delivery_id


def test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts(
    session_factory: Any,
) -> None:
    """Plan 007 (re-attempt) v0.9.1: a delivery seeded at attempt=1
    goes through 2 failure ticks (base and base+10s) and is promoted
    to ``OrmWebhookDlq`` on the second tick (the post-increment
    attempt becomes 3 == ``_MAX_ATTEMPTS``, triggering
    ``_promote_to_dlq``).

    Tick structure (flat with-block, no nesting):

    - ``_respx.mock`` enters once and stays active across both ticks
      (the inbound ``POST /webhook`` is intercepted deterministically).
      Respx's mock base URL ``https://93.184.216.34`` matches the
      seeded subscription's target URL.
    - Tick 1: short-lived ``time_machine.travel(_BASE_TIME)`` →
      ``process_scheduled_retries`` → delivery bumped to attempt=2,
      scheduled at ``_BASE_TIME + 10s``.
    - Tick 2: short-lived ``time_machine.travel(_BASE_TIME + 10s)`` →
      ``process_scheduled_retries`` → delivery bumped to attempt=3 ==
      ``_MAX_ATTEMPTS`` → ``_promote_to_dlq`` → delivery row deleted +
      ``OrmWebhookDlq`` row inserted with same id.

    Verify each tick's effect via a fresh ``session_factory()``
    context (preferred over mutating the in-process row ORM
    reference because the ORM state is stale once the worker's
    transaction commits).
    """
    sub_id, upload_id_str, _fight_id = _bootstrap_webhook_environment(
        session_factory,
    )
    delivery_id = _seed_failed_delivery(
        session_factory,
        sub_id,
        upload_id_str,
        next_attempt_at=_BASE_TIME,
        attempt=1,
    )

    with _respx.mock(base_url="https://93.184.216.34") as mock:
        mock.post("/webhook").respond(500, json={"err": "down"})

        # Tick 1 (base): process the seeded delivery at attempt=1 →
        # fails (HTTP 500) → delivery.attempt becomes 2 → next
        # attempt scheduled at base + _BACKOFF_BY_ATTEMPT[2] (10s).
        with time_machine.travel(_BASE_TIME, tick=False):
            count1 = process_scheduled_retries(session_factory)
            assert count1 == 1, f"tick 1: expected 1 processed, got {count1}"

        with session_factory() as verify_db:
            delivery = verify_db.get(OrmWebhookDelivery, delivery_id)
            assert delivery is not None, (
                "tick 1: delivery row unexpectedly deleted (should still exist; "
                "max attempts not yet hit)"
            )
            assert delivery.attempt == 2, (
                f"tick 1: expected attempt=2 after first failure, got {delivery.attempt}"
            )
            assert delivery.status_code == 500
            assert delivery.error == "non-2xx response: 500"
            assert delivery.delivered_at is None
            assert delivery.next_attempt_at == _BASE_TIME + timedelta(seconds=10), (
                f"tick 1: next_attempt_at expected base+10s, got {delivery.next_attempt_at!r}"
            )
            # No DLQ row yet (max attempts not reached).
            assert verify_db.get(OrmWebhookDlq, delivery_id) is None

        # Tick 2 (base + 10s): process the now-pending delivery at
        # attempt=2 → fails → delivery.attempt becomes 3 ==
        # _MAX_ATTEMPTS → caller promotes to DLQ → delivery row
        # deleted + OrmWebhookDlq row inserted with same id.
        with time_machine.travel(_BASE_TIME + timedelta(seconds=10), tick=False):
            count2 = process_scheduled_retries(session_factory)
            assert count2 == 1, f"tick 2: expected 1 processed, got {count2}"

        with session_factory() as verify_db:
            # Final state: delivery row gone, DLQ row created with
            # payload preserved verbatim from the original dispatch.
            assert verify_db.get(OrmWebhookDelivery, delivery_id) is None, (
                f"tick 2: delivery row {delivery_id} should be deleted after DLQ promotion"
            )
            dlq_row = verify_db.get(OrmWebhookDlq, delivery_id)
            assert dlq_row is not None, f"tick 2: DLQ row expected at id={delivery_id}, not found"
            assert dlq_row.subscription_id == sub_id
            assert dlq_row.upload_id == upload_id_str
            assert dlq_row.last_error == "non-2xx response: 500"
            assert dlq_row.moved_to_dlq_at is not None
            # Payload preserved verbatim so the replay endpoint can
            # re-emit the canonical body byte-for-byte.
            assert dlq_row.payload is not None
            # Payload preserved verbatim (bytes) so the replay endpoint
            # can re-emit the canonical body byte-for-byte. The shape
            # itself is unchanged from the dispatch-time dict — we
            # round-trip through json.loads to assert semantic fields.
            dlq_dict = _json.loads(dlq_row.payload.decode("utf-8"))
            assert dlq_dict["kind"] == "upload_completed"
            assert dlq_dict["upload_id"] == upload_id_str
            assert dlq_dict["sha256"] == "a" * 64
