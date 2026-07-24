"""v0.9.0 backend: webhook delivery worker (single-attempt dispatch).

Implements the dispatch-for-upload side of the design in
``docs/v0.8.0-backend-design.md`` \xa73.4 (wire format) + \xa75 (worker
design), scoped to a single delivery attempt per subscription.

The 3-attempt retry schedule with exponential backoff (1s / 10s / 100s)
plus the dead-letter promotion to ``webhook_dlq`` are deferred to
v0.9.1 -- this v0.9.0 close-out ships the **data-plane** (rows +
HMAC signing + filter match + delivery persistence) so integrators
can build against the API end-to-end. The retry/DLQ substance lands
in the v0.9.1 hardening slice. The omission is documented in
CHANGELOG [Unreleased] under a ``### Known followup`` sub-block.

Session lifecycle
-----------------

The worker opens a **fresh, worker-scoped** session via the injected
``session_factory`` so it does NOT reuse the request session that
``process_parse`` consumed (the request session is closed by the
time this BG task runs and the database dependency generator's
``finally`` block has fired). The factory pattern is the same one
the production migration toward a dedicated Arq worker process will
reuse -- see the trade-off note in ``services.process_parse``.

Async architecture
------------------

v0.10.21 followup: the dispatch loop is split into three phases so
that synchronous SQLAlchemy work never blocks the asyncio event loop
while outbound HTTP requests are still concurrent:

1. **Prepare** (sync, in thread): load the upload, fetch active
   subscriptions, create ``OrmWebhookDelivery`` rows, compute HMAC
   signatures, commit.
2. **HTTP** (async): fire all POSTs concurrently via
   ``httpx.AsyncClient`` + ``asyncio.gather``.
3. **Finalize** (sync, in thread): open a new session, update each
   delivery row with status code / delivered_at / error, commit.

This keeps the concurrent-HTTP win while avoiding event-loop blocking
and keeping the SQLAlchemy ``Session`` usage single-threaded.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import uuid as uuid_lib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from gw2analytics_api.config import get_settings
from gw2analytics_api.crypto import FernetInvalidToken, decrypt_webhook_secret
from gw2analytics_api.models import (
    UPLOAD_STATUS_COMPLETED,
    OrmWebhookDelivery,
    OrmWebhookSubscription,
    Upload,
)

logger = logging.getLogger(__name__)

# Single supported filter kind for v0.9.0. Future kinds
# (per-encounter, per-result) are v0.9.1 vocabulary expansion.
_FILTER_KIND_UPLOAD_COMPLETED = "upload_completed"

_USER_AGENT = "Gw2Analytics-Webhook/0.9.0"


class _NoDispatchReason:
    """Sentinel returned by the prepare phase when no deliveries should be made."""

    def __init__(self, log_message: str) -> None:
        self.log_message = log_message


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _generate_delivery_id() -> str:
    """Discriminator on the integration-side per \xa73.4 (``dly_<uuid>``)."""
    return f"dly_{uuid_lib.uuid4()}"


@dataclass(frozen=True, slots=True)
class _DeliveryRequest:
    """Pure data needed to fire one outbound webhook POST.

    No SQLAlchemy objects or decrypted secrets cross the thread/async
    boundary -- only the already-computed headers and payload bytes.
    """

    delivery_id: str
    subscription_id: str
    url: str
    headers: dict[str, str]
    body_bytes: bytes


@dataclass(frozen=True, slots=True)
class _DeliveryOutcome:
    """Result of one outbound webhook POST, ready to be persisted."""

    delivery_id: str
    status_code: int | None
    error: str | None
    delivered_at: datetime | None


def _prepare_deliveries(
    session_factory: Callable[[], Session],
    upload_id: uuid_lib.UUID,
) -> list[_DeliveryRequest] | _NoDispatchReason:
    """Load upload + subscriptions, create delivery rows, return request data.

    This function runs synchronously in a worker thread so the
    SQLAlchemy session never touches the asyncio event loop.
    """
    with session_factory() as db:
        upload = db.get(Upload, upload_id)
        if upload is None:
            return _NoDispatchReason(
                f"upload {upload_id} disappeared between parse commit "
                "and webhook dispatch; skipping",
            )
        if upload.status != UPLOAD_STATUS_COMPLETED:
            return _NoDispatchReason(
                f"upload {upload_id} status={upload.status!r} "
                "(not COMPLETED); skipping webhook dispatch",
            )
        if upload.fight is None:
            return _NoDispatchReason(
                f"upload {upload_id} COMPLETED but no OrmFight row; skipping webhook dispatch",
            )

        payload = {
            "kind": _FILTER_KIND_UPLOAD_COMPLETED,
            "upload_id": str(upload.id),
            "fight_id": upload.fight.id,
            "sha256": upload.sha256,
            "started_at": upload.fight.started_at.isoformat(),
        }
        body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        active_subs = (
            db.execute(
                select(OrmWebhookSubscription).where(
                    OrmWebhookSubscription.revoked_at.is_(None),
                ),
            )
            .scalars()
            .all()
        )

        if not active_subs:
            return _NoDispatchReason(
                f"no active webhook subscriptions; skipping dispatch for upload {upload_id}",
            )

        upload_id_str = str(upload.id)
        requests: list[_DeliveryRequest] = []

        for sub in active_subs:
            # v0.10.0 plan 031: decrypt the ciphertext BEFORE HMAC signing.
            try:
                plaintext_secret = decrypt_webhook_secret(sub.ciphertext)
            except FernetInvalidToken as exc:
                # One corrupt row MUST NOT crash the whole dispatch loop.
                # Record a delivery row with the error and continue.
                delivery_id = _generate_delivery_id()
                delivery = OrmWebhookDelivery(
                    id=delivery_id,
                    subscription_id=sub.id,
                    upload_id=upload_id_str,
                    attempt=1,
                    error=f"ciphertext corrupt: {FernetInvalidToken.__name__}: {exc}",
                )
                delivery.payload = body_bytes
                delivery.next_attempt_at = utcnow()
                db.add(delivery)
                logger.error(
                    "webhook subscription %s ciphertext corrupt "
                    "(FernetInvalidToken); one corrupt row must NOT crash "
                    "the entire dispatch loop -- recording delivery row + "
                    "skipping; message=%s",
                    sub.id,
                    exc,
                )
                continue

            # Filter match: today only ``kind=upload_completed``.
            if sub.filter_payload.get("kind") != _FILTER_KIND_UPLOAD_COMPLETED:
                logger.debug(
                    "webhook subscription %s filter kind=%r; "
                    "no match for upload_completed dispatch",
                    sub.id,
                    sub.filter_payload.get("kind"),
                )
                continue

            delivery_id = _generate_delivery_id()
            signature = hmac.new(
                plaintext_secret.encode("utf-8"),
                body_bytes,
                hashlib.sha256,
            ).hexdigest()
            headers = {
                "Content-Type": "application/json",
                "X-Gw2Analytics-Signature": f"sha256={signature}",
                "X-Gw2Analytics-Delivery": delivery_id,
                "User-Agent": _USER_AGENT,
            }

            delivery = OrmWebhookDelivery(
                id=delivery_id,
                subscription_id=sub.id,
                upload_id=upload_id_str,
                attempt=1,
            )
            delivery.payload = body_bytes
            delivery.next_attempt_at = utcnow()
            db.add(delivery)

            requests.append(
                _DeliveryRequest(
                    delivery_id=delivery_id,
                    subscription_id=sub.id,
                    url=sub.url,
                    headers=headers,
                    body_bytes=body_bytes,
                )
            )

        db.commit()
        return requests


def _finalize_deliveries(
    session_factory: Callable[[], Session],
    outcomes: list[_DeliveryOutcome],
) -> None:
    """Persist the outcomes of the concurrent HTTP phase.

    Runs synchronously in a worker thread.
    """
    if not outcomes:
        return

    with session_factory() as db:
        delivery_ids = [o.delivery_id for o in outcomes]
        deliveries = {
            d.id: d
            for d in db.execute(
                select(OrmWebhookDelivery).where(
                    OrmWebhookDelivery.id.in_(delivery_ids),
                ),
            )
            .scalars()
            .all()
        }

        for outcome in outcomes:
            delivery = deliveries.get(outcome.delivery_id)
            if delivery is None:
                logger.warning(
                    "delivery %s vanished between HTTP phase and finalize; skipping",
                    outcome.delivery_id,
                )
                continue
            delivery.status_code = outcome.status_code
            delivery.error = outcome.error
            delivery.delivered_at = outcome.delivered_at

        db.commit()


async def _dispatch_single_async(
    client: httpx.AsyncClient,
    request: _DeliveryRequest,
) -> _DeliveryOutcome:
    """Fire one POST and return a pure outcome dataclass (no DB work)."""
    try:
        resp = await client.post(
            request.url,
            content=request.body_bytes,
            headers=request.headers,
        )
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "webhook network error: delivery_id=%s subscription_id=%s error=%s",
            request.delivery_id,
            request.subscription_id,
            error,
        )
        return _DeliveryOutcome(
            delivery_id=request.delivery_id,
            status_code=None,
            error=error,
            delivered_at=None,
        )

    if resp.is_success:
        logger.info(
            "webhook delivered: delivery_id=%s subscription_id=%s status_code=%d",
            request.delivery_id,
            request.subscription_id,
            resp.status_code,
        )
        return _DeliveryOutcome(
            delivery_id=request.delivery_id,
            status_code=resp.status_code,
            error=None,
            delivered_at=utcnow(),
        )

    error = f"non-2xx response: {resp.status_code}"
    logger.warning(
        "webhook non-2xx: delivery_id=%s subscription_id=%s status_code=%d",
        request.delivery_id,
        request.subscription_id,
        resp.status_code,
    )
    return _DeliveryOutcome(
        delivery_id=request.delivery_id,
        status_code=resp.status_code,
        error=error,
        delivered_at=None,
    )


async def dispatch_for_upload(
    session_factory: Callable[[], Session],
    upload_id: uuid_lib.UUID,
) -> None:
    """Fire one signed POST per active subscription for a COMPLETED upload.

    Single-attempt: each delivery row records either the success
    (with ``delivered_at``) or the failure (non-2xx status OR
    network error). The 3-attempt retry schedule + DLQ promotion
    is a v0.9.1 followup (see CHANGELOG ``### Known followup``).

    Outbound POSTs are issued concurrently via ``httpx.AsyncClient``
    so a slow subscriber cannot serially block deliveries to the
    remaining subscribers. Database work is kept in worker threads
    to avoid blocking the asyncio event loop.
    """
    try:
        prepare_result = await asyncio.to_thread(
            _prepare_deliveries,
            session_factory,
            upload_id,
        )
    except SQLAlchemyError:
        logger.exception(
            "webhook dispatch prepare phase crashed for upload %s",
            upload_id,
        )
        raise

    if isinstance(prepare_result, _NoDispatchReason):
        logger.debug(prepare_result.log_message)
        return

    requests = prepare_result
    delivered_count = 0

    timeout_s = get_settings().webhook_dispatch_timeout_s
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        results = await asyncio.gather(
            *(_dispatch_single_async(client, req) for req in requests),
            return_exceptions=True,
        )

    outcomes: list[_DeliveryOutcome] = []
    for result in results:
        if isinstance(result, _DeliveryOutcome):
            outcomes.append(result)
            if result.status_code is not None and 200 <= result.status_code < 300:
                delivered_count += 1
        elif isinstance(result, BaseException):
            logger.exception(
                "unexpected error during webhook dispatch for upload %s: %s",
                upload_id,
                result,
            )

    try:
        await asyncio.to_thread(_finalize_deliveries, session_factory, outcomes)
    except SQLAlchemyError:
        logger.exception(
            "webhook dispatch finalize phase crashed for upload %s; "
            "delivery rows may be left in an incomplete state",
            upload_id,
        )
        raise

    logger.info(
        "webhook dispatch for upload %s: %d/%d subscriptions delivered",
        upload_id,
        delivered_count,
        len(requests),
    )


__all__ = ["dispatch_for_upload"]
