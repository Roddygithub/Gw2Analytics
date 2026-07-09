"""v0.9.1 backend: webhook retry + DLQ scheduler.

Polling worker that picks up failed deliveries (attempt < 3) and
either retries them with exponential backoff (1s / 10s / 100s
per design doc §5) or promotes them to ``OrmWebhookDlq`` on
the third failure. The replay endpoint
(:func:`gw2analytics_api.routes.webhooks.replay_dlq_delivery`)
reverses a DLQ promotion by creating a fresh delivery row +
deleting the DLQ row in one transaction.

Mirrors :func:`gw2analytics_api.workers.webhook_dispatch.dispatch_for_upload`'s
session-DI discipline (the worker opens a FRESH worker-scoped
session per invocation via the injected ``session_factory``).

Lifecycle
---------

The scheduler runs as a background asyncio task started by
:mod:`gw2analytics_api.main`'s ``lifespan`` handler. The 5s poll
interval matches the design doc §5 contract -- retries are
NOT sub-second-critical (the first delivery attempt is
synchronous via FastAPI BG-tasks in ``routes/uploads``; the retry
only fires when that initial POST failed). DB-blocking calls
inside the polling tick are wrapped in ``asyncio.to_thread`` so
the FastAPI main event loop is NOT stalled.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from gw2analytics_api.crypto import FernetInvalidToken, decrypt_webhook_secret
from gw2analytics_api.models import (
    OrmWebhookDelivery,
    OrmWebhookDlq,
    OrmWebhookSubscription,
)

logger = logging.getLogger(__name__)

# Per design doc §5: 5s poll interval for the scheduler.
_POLL_INTERVAL_S = 5.0

# Exponential backoff schedule: {attempt -> seconds}. The attempt
# value in the schedule is the post-attempt number: after the second
# failed attempt, schedule at attempt=2 (10s wait before trying
# attempt=3 -- the final one before DLQ promotion).
_BACKOFF_BY_ATTEMPT: dict[int, int] = {1: 1, 2: 10, 3: 100}

# Per design doc §5: 10s timeout per outbound POST (mirrors
# ``webhook_dispatch.py``'s policy).
_REQUEST_TIMEOUT_S = 10.0

# Maximum retry attempts before DLQ promotion. attempt=3 is the
# final attempt; if it also fails, the row is promoted.
_MAX_ATTEMPTS = 3

_USER_AGENT = "Gw2Analytics-Webhook/0.9.1"


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _compute_next_attempt_at(attempt: int) -> datetime:
    """``now + backoff[attempt]`` for the post-attempt delay.

    ``attempt`` is the (about-to-be-incremented) attempt count;
    e.g. if the first attempt failed and we are about to retry
    as attempt=2, the next attempt should be 1s from now.
    """
    backoff_s = _BACKOFF_BY_ATTEMPT.get(attempt, _BACKOFF_BY_ATTEMPT[_MAX_ATTEMPTS])
    return datetime.now(tz=UTC) + timedelta(seconds=backoff_s)


def process_scheduled_retries(session_factory: Callable[[], Session]) -> int:
    """One poll cycle: pick up failed deliveries, retry them, or
    promote to DLQ on the third failure.

    Returns the number of deliveries processed (success + failure).
    DB-blocking; caller (the asyncio lifespan) wraps this in
    ``asyncio.to_thread`` so FastAPI's event loop is not stalled.

    Edge cases handled:
    - No rows ready to retry -> returns 0 quickly.
    - Subscription missing (hard-deleted between attempt 1 and
      attempt 2/3) -> marked failed + ``error`` annotated; the
      :func:`_attempt_retry` path will see ``attempt >= max`` and
      the caller promotes to DLQ with the missing-subscription
      annotation in ``last_error``.
    - Subscription or payload missing (corrupt row) -> an immediate
      failed-attempt + ``error`` annotated.
    - ``httpx.HTTPError`` raised by the retry POST -> ``error`` set;
      ``next_attempt_at`` scheduled for the next retry if
      ``attempt < max``.
    - ``attempt >= max`` after a failure -> caller promotes to DLQ.
    """
    now = _utcnow()
    delivered_count = 0
    failed_count = 0
    with session_factory() as db:
        try:
            rows = (
                db.execute(
                    select(OrmWebhookDelivery).where(
                        OrmWebhookDelivery.attempt < _MAX_ATTEMPTS,
                        OrmWebhookDelivery.delivered_at.is_(None),
                        (
                            OrmWebhookDelivery.next_attempt_at.is_(None)
                            | (OrmWebhookDelivery.next_attempt_at <= now)
                        ),
                        (
                            OrmWebhookDelivery.status_code.is_(None)
                            | (OrmWebhookDelivery.status_code >= 300)
                        ),
                    ),
                )
                .scalars()
                .all()
            )
            if not rows:
                return 0

            with httpx.Client(timeout=_REQUEST_TIMEOUT_S) as client:
                for delivery in rows:
                    if _attempt_retry(db, client, delivery):
                        delivered_count += 1
                    else:
                        failed_count += 1
                        if delivery.attempt >= _MAX_ATTEMPTS:
                            _promote_to_dlq(db, delivery)

            db.commit()
            return delivered_count + failed_count
        except Exception:
            logger.exception("scheduled-retries tick crashed; rolling back the cycle")
            db.rollback()
            raise


def _attempt_retry(
    db: Session,
    client: httpx.Client,
    delivery: OrmWebhookDelivery,
) -> bool:
    """Retry one delivery; increment attempt; record success/failure.

    Returns True if delivered (2xx), False otherwise. After
    increment, if ``attempt >= max`` AND still failed, the caller
    (:func:`process_scheduled_retries`) promotes to DLQ.

    The body bytes are reconstructed from ``delivery.payload`` so
    the HMAC-SHA256 signature is byte-for-byte identical to the
    original POST -- the integrator's HMAC verification sees the
    same digest across all retry attempts.
    """
    subscription = db.get(OrmWebhookSubscription, delivery.subscription_id)
    if subscription is None or subscription.revoked_at is not None:
        logger.warning(
            "retry: subscription %s missing or revoked for delivery %s; "
            "marking failed (will be promoted to DLQ)",
            delivery.subscription_id,
            delivery.id,
        )
        delivery.attempt += 1
        delivery.error = f"subscription {delivery.subscription_id} missing or revoked at retry time"
        delivery.next_attempt_at = _utcnow()
        return False

    if not subscription.ciphertext or delivery.payload is None:
        logger.warning(
            "retry: missing ciphertext or payload for delivery %s; marking failed",
            delivery.id,
        )
        delivery.attempt += 1
        delivery.error = "missing subscription ciphertext or preserved payload"
        delivery.next_attempt_at = _utcnow()
        return False

    # Post-plan-009 Step 1: ``delivery.payload`` is LargeBinary (raw
    # bytes). The dispatch worker wrote the canonical ``body_bytes``
    # verbatim; re-using the bytes directly (rather than a JSON
    # round-trip via JSONB) preserves byte-for-byte HMAC integrity
    # across retries + replays.
    body_bytes = delivery.payload

    # Post-plan-031: decrypt the envelope ciphertext on demand.
    # The KEK is held in the gateway process memory (never crosses
    # the SQL wire). One bad row MUST NOT crash the whole retry
    # loop -- catch FernetInvalidToken per-delivery, mark the
    # delivery failed, and continue with the next one (mirrors
    # ``webhook_dispatch.py``'s cross-subscriber isolation
    # discipline).
    try:
        secret = decrypt_webhook_secret(subscription.ciphertext)
    except FernetInvalidToken as exc:
        logger.warning(
            "retry: ciphertext corrupt for delivery %s (KEK rotated OR "
            "manual DB edit?); marking failed AT TERMINAL attempt "
            "(no further retry to avoid scheduler-spam on a "
            "structurally-unfixable row)",
            delivery.id,
        )
        delivery.attempt = _MAX_ATTEMPTS
        delivery.error = (
            f"ciphertext corrupt: {FernetInvalidToken.__name__}: {exc} "
            f"(terminal on attempt={delivery.attempt}, no retry)"
        )
        delivery.next_attempt_at = None
        return False

    signature = hmac.new(
        secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Gw2Analytics-Signature": f"sha256={signature}",
        "X-Gw2Analytics-Delivery": delivery.id,
        "User-Agent": _USER_AGENT,
    }

    delivery.attempt += 1
    delivery.next_attempt_at = None

    try:
        resp = client.post(subscription.url, content=body_bytes, headers=headers)
    except httpx.HTTPError as exc:
        delivery.error = f"{type(exc).__name__}: {exc}"
        if delivery.attempt < _MAX_ATTEMPTS:
            delivery.next_attempt_at = _compute_next_attempt_at(delivery.attempt)
        logger.warning(
            "retry network error: delivery_id=%s attempt=%d error=%s",
            delivery.id,
            delivery.attempt,
            delivery.error,
        )
        return False

    delivery.status_code = resp.status_code
    if resp.is_success:
        delivery.delivered_at = _utcnow()
        delivery.error = None
        logger.info(
            "retry success: delivery_id=%s attempt=%d status_code=%d",
            delivery.id,
            delivery.attempt,
            resp.status_code,
        )
        return True
    delivery.error = f"non-2xx response: {resp.status_code}"
    if delivery.attempt < _MAX_ATTEMPTS:
        delivery.next_attempt_at = _compute_next_attempt_at(delivery.attempt)
    logger.warning(
        "retry non-2xx: delivery_id=%s attempt=%d status_code=%d",
        delivery.id,
        delivery.attempt,
        resp.status_code,
    )
    return False


def _promote_to_dlq(db: Session, delivery: OrmWebhookDelivery) -> OrmWebhookDlq:
    """Move a failed delivery to the DLQ table atomically.

    The DLQ row keeps the original delivery id (so a replay can
    ``db.get(OrmWebhookDlq, delivery_id)`` to find it) + the
    original subscription_id (NO FK; the original subscription
    may be hard-deleted) + upload_id + the canonical payload (so
    the replay can re-emit byte-for-byte).

    Caller's outer ``db.commit()`` finalises the atomic promotion.
    """
    # Post-plan-009 Step 1: ``OrmWebhookDlq.payload`` is LargeBinary
    # (raw bytes); the dispatch worker computed the canonical bytes
    # once and the scheduler re-uses them across retries. We copy the
    # bytes verbatim so a subsequent ``replay_dlq_delivery`` can
    # re-emit the canonical body without a JSONB round-trip (which
    # would re-order keys and break the HMAC verification).
    dlq = OrmWebhookDlq(
        id=delivery.id,
        subscription_id=delivery.subscription_id,
        upload_id=delivery.upload_id,
        payload=delivery.payload if delivery.payload is not None else b"",
        last_error=delivery.error,
        moved_to_dlq_at=_utcnow(),
    )
    db.add(dlq)
    db.delete(delivery)
    return dlq


async def lifespan_scheduler(
    session_factory: Callable[[], Session],
) -> None:
    """Async background task; runs forever (or until app shutdown).

    Wraps the DB-blocking :func:`process_scheduled_retries` in
    ``asyncio.to_thread`` so the FastAPI event loop is not stalled
    on Postgres round-trips. The 5s ``asyncio.sleep`` between
    ticks yields to the event loop.

    Crash-loop resilience: the per-tick ``try/except`` inside
    :func:`process_scheduled_retries` rolls back any partial
    state, and the outer ``except Exception`` here catches any
    exception that escapes (e.g. process killed mid-rollback). The
    loop simply waits for the next interval and re-tries -- the
    scheduler NEVER dies on a transient failure.
    """
    logger.info(
        "webhook scheduler lifespan starting (poll interval: %.1fs, max attempts: %d)",
        _POLL_INTERVAL_S,
        _MAX_ATTEMPTS,
    )
    try:
        while True:
            try:
                await asyncio.to_thread(process_scheduled_retries, session_factory)
            except Exception:
                logger.exception(
                    "scheduled-retries tick failed; continuing to "
                    "next interval (resilience: scheduler does "
                    "NOT die on transient failures)"
                )
            await asyncio.sleep(_POLL_INTERVAL_S)
    except asyncio.CancelledError:
        logger.info("webhook scheduler lifespan cancelled; shutting down cleanly")
        raise
