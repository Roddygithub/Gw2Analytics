"""v0.9.0 backend: /api/v1/webhooks management routes.

Implements the subscription lifecycle per
``docs/v0.8.0-backend-design.md`` §4.

Endpoints
---------

- ``POST   /api/v1/webhooks`` -> 201, returns the secret ONE time
- ``GET    /api/v1/webhooks`` -> list of active subscriptions (no secret)
- ``GET    /api/v1/webhooks/{id}`` -> single active subscription (no secret)
- ``DELETE /api/v1/webhooks/{id}`` -> 204, idempotent soft-delete

The canonical deletion primitive is ``revoked_at`` (soft-delete). The
hard-delete path is an operator-only emergency action -- not exposed
through this route. Revoked subscriptions return 404 on GET and act
idempotently (204) on DELETE.
"""

from __future__ import annotations

import base64
import ipaddress
import logging
import os
import secrets
import socket
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from gw2analytics_api.database import get_session
from gw2analytics_api.models import (
    OrmWebhookDelivery,
    OrmWebhookDlq,
    OrmWebhookSubscription,
    Upload,
)
from gw2analytics_api.schemas import (
    WebhookDeliveryReplayOut,
    WebhookSubscriptionCreate,
    WebhookSubscriptionCreatedOut,
    WebhookSubscriptionOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _generate_subscription_id() -> str:
    # URL-safe base64 -- standard b64encode emits '/' / '+' which
    # break FastAPI path-param matching on DELETE /{subscription_id}.
    return "whsub_" + base64.urlsafe_b64encode(secrets.token_bytes(12)).decode()


def _generate_secret() -> str:
    return "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode()


def _validate_webhook_url(url: str) -> None:
    """HTTPS-or-localhost policy per design doc §7.3 + v0.9.1 plan 005
    universal SSRF block on resolved addresses.

    Pre-plan-005 the policy was: ``http://`` only for loopback,
    ``https://`` wide-open. Plan 005 closed the SSRF gap by adding
    a universal ``is_private | is_loopback | is_link_local |
    is_multicast`` check on the resolved address (for hostnames)
    OR on the literal IP (for IP-literal hostnames).

    Opt-out via ``GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS=1`` for
    trusted dev environments only. Production deployments MUST keep
    the env unset (= strict). The env is read on every call so a
    server restart is not required to flip the gate.
    """
    if any(ch.isspace() for ch in url):
        raise HTTPException(
            status_code=422,
            detail="webhook url must not contain whitespace",
        )
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            status_code=422,
            detail=f"webhook url scheme must be http or https (got {parsed.scheme!r})",
        )
    if not parsed.hostname:
        raise HTTPException(
            status_code=422,
            detail="webhook url must include a host (got empty hostname)",
        )
    if parsed.scheme == "http":
        hostname = (parsed.hostname or "").lower()
        if hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise HTTPException(
                status_code=422,
                detail="http scheme only allowed for loopback hosts (localhost / 127.0.0.1 / ::1)",
            )
    # v0.9.1 plan 005: universal SSRF defense for both schemes.
    # Without this, ``https://10.0.0.1/``, ``https://169.254.169.254/``
    # (AWS IMDS), ``https://[::1]/``, ``https://[fc00::deadbeef]/``
    # all pass the prior gate (the http:loopback carve-out applies
    # only to the ``http`` scheme). Direct IP literals are classified
    # without DNS lookup; hostnames are resolved via getaddrinfo
    # (handles IPv4 + IPv6 simultaneously). Fail-closed on DNS
    # errors to block DNS-rebind-style deferred attacks where the A
    # record resolves only later.
    if not os.environ.get(
        "GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS"
    ) and _resolved_address_is_blocked(parsed.hostname):
        raise HTTPException(
            status_code=422,
            detail=(
                "webhook url resolves to a private/loopback/"
                "link-local/multicast address "
                "(set GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS=1 "
                "to override in trusted dev only)"
            ),
        )


def _resolved_address_is_blocked(hostname: str) -> bool:
    """Return True if any resolved IP for ``hostname`` is private /
    loopback / link-local / multicast. Used to block SSRF against
    internal networks regardless of scheme.

    The helper is fail-closed on DNS errors (``socket.gaierror``,
    ``TimeoutError``) and on empty hostnames; an unresolvable
    hostname is treated as blocked, which blocks DNS-rebind-style
    deferred attacks where the A record resolves only later.
    """
    if not hostname:
        return True
    # Direct IP literal: classify in-process (no DNS lookup needed).
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        addr = None
    if addr is not None:
        return _ip_is_blocked(addr)
    # Hostname: resolve via getaddrinfo (handles IPv4 + IPv6).
    try:
        infos = socket.getaddrinfo(
            hostname,
            None,
            type=socket.SOCK_STREAM,
        )
    except (socket.gaierror, TimeoutError):
        return True  # fail-closed on DNS failure
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            addr = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _ip_is_blocked(addr):
            return True
    return False


def _ip_is_blocked(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Return True if ``addr`` targets a private / loopback /
    link-local / multicast range.

    Covers RFC1918 (10/8, 172.16/12, 192.168/16) +
    shared address space (100.64/10) + 0.0.0.0/8 via ``is_private``,
    127.0.0.0/8 + ::1 via ``is_loopback``, 169.254/16 + fe80::/10
    via ``is_link_local``, 224.0.0.0/4 + ff00::/8 via
    ``is_multicast``. IPv6 ULA (fc00::/7) is covered by
    ``is_private`` in Python 3.11+.
    """
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast)


@router.post(
    "",
    response_model=WebhookSubscriptionCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
def create_webhook(
    payload: WebhookSubscriptionCreate,
    db: Session = Depends(get_session),  # noqa: B008
) -> WebhookSubscriptionCreatedOut:
    """Register a webhook subscription (returns secret ONE time)."""
    _validate_webhook_url(payload.url)

    new_sub = OrmWebhookSubscription(
        id=_generate_subscription_id(),
        url=payload.url,
        description=payload.description,
        secret=_generate_secret(),
    )
    # Use the Python attr name ``filter_payload`` (the SQL column is
    # ``filter`` -- we shadow it on the ORM class to avoid collision
    # with the Python builtin ``filter()``).
    new_sub.filter_payload = payload.filter
    new_sub.created_at = _utcnow()
    db.add(new_sub)
    db.commit()

    return WebhookSubscriptionCreatedOut(
        id=new_sub.id,
        url=new_sub.url,
        filter=new_sub.filter_payload,
        description=new_sub.description,
        secret=new_sub.secret,
        created_at=new_sub.created_at,
    )


@router.get("", response_model=list[WebhookSubscriptionOut])
def list_webhooks(
    db: Session = Depends(get_session),  # noqa: B008
) -> list[WebhookSubscriptionOut]:
    """List active (non-revoked) webhook subscriptions. Secrets never returned."""
    rows = (
        db.execute(
            select(OrmWebhookSubscription).where(OrmWebhookSubscription.revoked_at.is_(None))
        )
        .scalars()
        .all()
    )
    return [
        WebhookSubscriptionOut(
            id=r.id,
            url=r.url,
            filter=r.filter_payload,
            description=r.description,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/{subscription_id}", response_model=WebhookSubscriptionOut)
def get_webhook(
    subscription_id: str,
    db: Session = Depends(get_session),  # noqa: B008
) -> WebhookSubscriptionOut:
    """Look up one subscription by id (404 if revoked or missing)."""
    row = db.get(OrmWebhookSubscription, subscription_id)
    if row is None or row.revoked_at is not None:
        raise HTTPException(
            status_code=404,
            detail=f"webhook subscription {subscription_id} not found",
        )
    return WebhookSubscriptionOut(
        id=row.id,
        url=row.url,
        filter=row.filter_payload,
        description=row.description,
        created_at=row.created_at,
    )


@router.delete(
    "/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_webhook(
    subscription_id: str,
    db: Session = Depends(get_session),  # noqa: B008
) -> None:
    """Idempotent soft-delete (sets revoked_at). Already-revoked returns 204."""
    row = db.get(OrmWebhookSubscription, subscription_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"webhook subscription {subscription_id} not found",
        )
    if row.revoked_at is None:
        row.revoked_at = _utcnow()
        db.commit()


def _generate_delivery_id() -> str:
    """Discriminator on the integration-side per §3.4 (``dly_<uuid>``)."""
    return f"dly_{uuid.uuid4()}"


@router.post(
    "/dlq/{delivery_id}/replay",
    status_code=status.HTTP_201_CREATED,
    response_model=WebhookDeliveryReplayOut,
)
def replay_dlq_delivery(
    delivery_id: str,
    db: Session = Depends(get_session),  # noqa: B008
) -> WebhookDeliveryReplayOut:
    """Replay one DLQ entry: create a fresh delivery + delete the
    DLQ row atomically. ``delivery_id`` is the original DLQ
    entry's id (NOT a generation round -- the original id is
    retained in the dlq row).

    404 cases (the only failure paths):

    1. DLQ entry not found (the id is unknown).
    2. Original subscription missing OR revoked -- the DLQ row
       retains the original ``subscription_id``, but if the
       subscription is gone (hard-delete) or revoked
       (soft-delete via the v0.9.0 endpoint), replaying is unsafe
       (no HMAC secret + no URL).
    3. Original upload missing (hard-deleted between the parse+DLQ
       and the replay) -- defensive; the payload still references
       the upload's fight summary but a 404 here surfaces the
       orphaned-row case.
    """
    dlq = db.get(OrmWebhookDlq, delivery_id)
    if dlq is None:
        raise HTTPException(
            status_code=404,
            detail=f"webhook DLQ entry {delivery_id} not found",
        )
    subscription = db.get(OrmWebhookSubscription, dlq.subscription_id)
    if subscription is None or subscription.revoked_at is not None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"webhook subscription {dlq.subscription_id} "
                f"missing or revoked; cannot replay DLQ entry "
                f"{delivery_id}"
            ),
        )
    upload = db.get(Upload, dlq.upload_id)
    if upload is None:
        raise HTTPException(
            status_code=404,
            detail=(f"upload {dlq.upload_id} missing; cannot replay DLQ entry {delivery_id}"),
        )

    new_delivery = OrmWebhookDelivery(
        id=_generate_delivery_id(),
        subscription_id=subscription.id,
        upload_id=str(upload.id),
        attempt=1,
    )
    new_delivery.payload = dlq.payload
    new_delivery.next_attempt_at = _utcnow()

    db.add(new_delivery)
    db.delete(dlq)
    db.commit()

    logger.info(
        "replayed DLQ entry %s -> new delivery %s for subscription %s",
        delivery_id,
        new_delivery.id,
        subscription.id,
    )

    return WebhookDeliveryReplayOut(
        delivery_id=new_delivery.id,
        subscription_id=subscription.id,
        upload_id=new_delivery.upload_id,
        attempt=new_delivery.attempt,
        next_attempt_at=new_delivery.next_attempt_at,
        restart=True,
    )
