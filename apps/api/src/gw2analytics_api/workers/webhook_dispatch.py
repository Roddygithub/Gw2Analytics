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
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid as uuid_lib
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from gw2analytics_api.models import (
    UPLOAD_STATUS_COMPLETED,
    OrmWebhookDelivery,
    OrmWebhookSubscription,
    Upload,
)

logger = logging.getLogger(__name__)

# Per design doc \xa75: 10s timeout per outbound POST.
_REQUEST_TIMEOUT_S = 10.0

# Single supported filter kind for v0.9.0. Future kinds
# (per-encounter, per-result) are v0.9.1 vocabulary expansion.
_FILTER_KIND_UPLOAD_COMPLETED = "upload_completed"

_USER_AGENT = "Gw2Analytics-Webhook/0.9.0"


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _generate_delivery_id() -> str:
    """Discriminator on the integration-side per \xa73.4 (``dly_<uuid>``)."""
    return f"dly_{uuid_lib.uuid4()}"


def dispatch_for_upload(
    session_factory: Callable[[], Session],
    upload_id: uuid_lib.UUID,
) -> None:
    """Fire one signed POST per active subscription for a COMPLETED upload.

    Single-attempt: each delivery row records either the success
    (with ``delivered_at``) or the failure (non-2xx status OR
    network error). The 3-attempt retry schedule + DLQ promotion
    is a v0.9.1 followup (see CHANGELOG ``### Known followup``).

    Edge cases handled (in order, skip-with-log for each):

    - Upload row not found (race: hard-deleted between parse commit
      and dispatch) -- WARNING + return.
    - Upload status != COMPLETED (parse failed or hung) -- DEBUG +
      return (no deliveries on a failed parse).
    - Upload has no ``OrmFight`` relationship (parser yielded zero
      fights per ``process_parse`` failed invariant; defensive) --
      WARNING + return.
    - No active subscriptions -- DEBUG + commit + return.
    - Subscription with empty secret -- WARNING + skip that one
      (defensive; schema-layer POST 422 + route validator should
      prevent this from ever happening for newly-created subs).
    - Subscription ``filter_payload.kind`` != ``upload_completed``
      -- DEBUG + skip that one (forward-compat for future filter
      kinds; today ``POST /webhooks`` accepts any kind string).
    """
    with session_factory() as db:
        try:
            upload = db.get(Upload, upload_id)
            if upload is None:
                logger.warning(
                    "upload %s disappeared between parse commit and webhook dispatch; skipping",
                    upload_id,
                )
                return
            if upload.status != UPLOAD_STATUS_COMPLETED:
                logger.debug(
                    "upload %s status=%r (not COMPLETED); skipping webhook dispatch",
                    upload_id,
                    upload.status,
                )
                return
            if upload.fight is None:
                logger.warning(
                    "upload %s COMPLETED but no OrmFight row; skipping webhook dispatch",
                    upload_id,
                )
                return

            # Build the (constant) outbound payload -- same body to
            # every active subscriber per \xa73.4.
            payload = {
                "kind": _FILTER_KIND_UPLOAD_COMPLETED,
                "upload_id": str(upload.id),
                "fight_id": upload.fight.id,
                "sha256": upload.sha256,
                "started_at": upload.fight.started_at.isoformat(),
            }
            body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

            # Look up active subscriptions (revoked_at IS NULL).
            # Single round-trip; this joins into the dispatch loop
            # directly so we do not add a second ``.all()`` round-trip
            # inside the per-sub helper.
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
                logger.debug(
                    "no active webhook subscriptions; skipping dispatch for upload %s",
                    upload_id,
                )
                db.commit()
                return

            upload_id_str = str(upload.id)
            delivered_count = 0
            with httpx.Client(timeout=_REQUEST_TIMEOUT_S) as client:
                for sub in active_subs:
                    if _dispatch_single(
                        db,
                        client,
                        sub,
                        body_bytes,
                        upload_id_str,
                    ):
                        delivered_count += 1

            db.commit()
            logger.info(
                "webhook dispatch for upload %s: %d/%d subscriptions delivered",
                upload_id,
                delivered_count,
                len(active_subs),
            )
        except Exception:
            logger.exception(
                "webhook dispatch loop crashed for upload %s; rolling back",
                upload_id,
            )
            db.rollback()
            raise  # let FastAPI BG-task machinery log + record


def _dispatch_single(
    db: Session,
    client: httpx.Client,
    sub: OrmWebhookSubscription,
    body_bytes: bytes,
    upload_id_str: str,
) -> bool:
    """Create one delivery row, fire POST, record outcome. NO commit.

    Returns True if delivered (2xx), False otherwise. The caller
    commits atomically after the loop so all deliveries for a
    given upload commit together (or all roll back together if the
    loop crashes).
    """
    # Defensive: schema + route validator should prevent this, but
    # if a corrupt row slipped through (manual DB edit, migration
    # partial), we skip rather than crash the whole dispatch loop.
    if not sub.secret:
        logger.warning(
            "webhook subscription %s has empty secret; skipping delivery",
            sub.id,
        )
        return False

    # Filter match: today only ``kind=upload_completed``. Other
    # kind values are accepted by ``POST /webhooks`` (the schema
    # is permissive) but produce zero deliveries under the current
    # filter vocabulary. Future kinds are a v0.9.1 extension.
    if sub.filter_payload.get("kind") != _FILTER_KIND_UPLOAD_COMPLETED:
        logger.debug(
            "webhook subscription %s filter kind=%r; no match for upload_completed dispatch",
            sub.id,
            sub.filter_payload.get("kind"),
        )
        return False

    delivery_id = _generate_delivery_id()
    signature = hmac.new(
        sub.secret.encode("utf-8"),
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
    # v0.9.1/v0.9.2: persist the canonical body bytes + set the
    # retry instant. The scheduler reads ``next_attempt_at`` to gate
    # re-delivery; the first attempt is immediate (no backoff delay).
    # Post-plan-009 Step 1 the ``payload`` column is LargeBinary
    # (raw bytes), so we write ``body_bytes`` directly -- otherwise
    # JSONB key reordering would break the HMAC byte-for-byte
    # guarantee across retries + replays (the integrator's HMAC
    # verification would see a different digest each attempt).
    delivery.payload = body_bytes
    delivery.next_attempt_at = _utcnow()
    db.add(delivery)

    try:
        resp = client.post(sub.url, content=body_bytes, headers=headers)
    except httpx.HTTPError as exc:
        # Covers ConnectError, ReadTimeout, RemoteProtocolError,
        # etc. -- the entire httpx transport layer. The delivery
        # row stays at attempt=1 / status_code=NULL with the
        # exception class + message persisted to ``error``.
        delivery.error = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "webhook network error: delivery_id=%s subscription_id=%s error=%s",
            delivery_id,
            sub.id,
            delivery.error,
        )
        return False

    delivery.status_code = resp.status_code
    if resp.is_success:
        delivery.delivered_at = _utcnow()
        logger.info(
            "webhook delivered: delivery_id=%s subscription_id=%s status_code=%d",
            delivery_id,
            sub.id,
            resp.status_code,
        )
        return True
    delivery.error = f"non-2xx response: {resp.status_code}"
    logger.warning(
        "webhook non-2xx: delivery_id=%s subscription_id=%s status_code=%d",
        delivery_id,
        sub.id,
        resp.status_code,
    )
    return False
