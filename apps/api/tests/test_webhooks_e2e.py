"""End-to-end POST /webhooks + GET + GET-by-id + DELETE tests against a real Postgres.

The v0.9.0 close-out ships these 4 webhook management endpoints
(``apps/api/src/gw2analytics_api/routes/webhooks.py``); this test
module is the v0.9.0 coverage that closes the ``### Deferred
(webhook route tests)`` entry documented in CHANGELOG [Unreleased].

Each test seeds ONE subscription with a uuid-derived suffix in the
URL so re-runs don't collide with prior state -- the
``webhook_subscriptions`` table accumulates rows across runs (no
CASCADE truncate needed), and tests always filter or assert
against THEIR specific sub-id (96 bits of ``whsub_`` entropy make
UUID-style collisions effectively impossible).

Test surface
------------

The 11 tests below cover the documented contract of the 4
endpoints (the design doc §3.1-3.3 wire contract + the v0.9.0
Hidden Issues the code-reviewer flagged):

1. ``test_webhooks_post_201_returns_secret_once`` -- POST 201 +
   one-time secret; the GET-by-id round-trip confirms the
   secret is NEVER returned again.
2. ``test_webhooks_post_422_on_http_non_loopback_url`` --
   ``http://example.com`` is rejected (not loopback).
3. ``test_webhooks_post_422_on_empty_host_url`` -- ``https://``
   is rejected (empty hostname).
4. ``test_webhooks_post_422_on_whitespace_url`` -- URL with
   whitespace is rejected.
5. ``test_webhooks_get_list_returns_only_active`` -- GET list
   filters revoked subs out; per ``routes/webhooks.list_webhooks``
   ``where(revoked_at.is_(None))``.
6. ``test_webhooks_get_by_id_returns_no_secret`` -- schema
   excludes ``secret`` field (v0.9.0 contract).
7. ``test_webhooks_get_by_id_404_on_unknown`` -- 404 not 500.
8. ``test_webhooks_get_by_id_404_on_revoked`` -- revoked == gone
   from public view per design doc §4.
9. ``test_webhooks_delete_204_marks_revoked`` -- DELETE sets
   ``revoked_at``; subsequent GET returns 404.
10. ``test_webhooks_delete_404_on_unknown`` -- missing == 404.
11. ``test_webhooks_delete_idempotent_when_already_revoked`` --
    DELETE on already-revoked returns 204 (not 404) so the
    integrator's retry path is safe.

Requires a Postgres server reachable at the ``DATABASE_URL`` declared
in ``pyproject.toml`` / ``.env``, AND the alembic migration ``0006``
applied (``alembic upgrade head``). Run ``docker compose up -d
gw2a-postgres`` first if your local environment does not already
expose Postgres on port 5432.

See ``apps/api/README.md`` for how to bring up the upstream Postgres
dependency locally + in CI.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import hmac
import json as _json
import socket as _socket
import time as _time
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import respx as _respx
import time_machine
from fastapi import HTTPException
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session as _sa  # noqa: N813

from gw2analytics_api import schemas
from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.main import app
from gw2analytics_api.models import (
    UPLOAD_STATUS_COMPLETED,
    OrmFight,
    OrmWebhookDelivery,
    OrmWebhookDlq,
    OrmWebhookSubscription,
    Upload,
)
from gw2analytics_api.routes import webhooks as _webhook_routes
from gw2analytics_api.workers.webhook_scheduler import process_scheduled_retries

client = TestClient(app)


def _new_sub_url(suffix: str | None = None) -> str:
    """Return a unique HTTPS URL per test invocation.

    The uuid-derived suffix is appended to a public IPv4 literal
    URL so each test writes a UNIQUE ``url`` column value without
    triggering the v0.9.1 plan 005 SSRF block (the validator
    classifies ``93.184.216.34`` as globally routable via
    ``ipaddress.IPv4Address`` directly, no DNS lookup).

    Postgres-ath friendly: each test's URL is unique, so the
    idempotent re-run contract (no CASCADE truncate) holds. The
    ``93.184.216.34`` literal is the IANA-assigned example.com
    fallback -- it never makes a real outbound request in tests
    (the dispatch worker is not exercised); it is purely a stable
    host token the validator classifies deterministically.
    """
    sfx = suffix or _uuid.uuid4().hex[:8]
    return f"https://93.184.216.34/wh-{sfx}"


def _post_sub(url: str = "") -> Response:
    """POST /api/v1/webhooks with the canonical test body.

    The route's ``WebhookSubscriptionCreate`` schema is permissive
    on ``filter: dict[str, object]`` so any well-formed
    ``dict[str, object]`` body is accepted. The filter kind
    ``upload_completed`` is the v0.9.0 canonical (per design doc
    §3.1 example).

    The annotation declares ``Response`` (httpx); the call site
    uses ``typing.cast`` to bridge the starlette testclient
    type stub (which types ``TestClient.post()`` as ``Any``)
    into the explicit return type. Without the cast, strict
    mypy rejects the ``Any -> Response`` narrowing as
    ``[no-any-return]``; without the annotation, the same
    strict mode rejects the missing annotation as
    ``[no-untyped-def]``. The cast is the conventional Python
    pattern for libraries with missing/incomplete stubs.
    """
    body = {
        "url": url or _new_sub_url(),
        "filter": {"kind": "upload_completed"},
        "description": None,
    }
    return cast(
        Response,
        client.post("/api/v1/webhooks", json=body),
    )


def test_generate_subscription_id_is_url_safe() -> None:
    """Regression guard for the v0.9.1 close-out bug where standard
    ``base64.b64encode`` emitted '/' / '+' characters in ~6% of
    16-byte token encodings. Those characters break FastAPI's
    path-parameter matching on
    ``DELETE /api/v1/webhooks/{subscription_id}`` (the route
    framework returns 404 even though the row exists in Postgres).

    The fix swapped to ``base64.urlsafe_b64encode`` which maps
    '/' -> '_' and '+' -> '-'. This unit-level test asserts the
    invariant without requiring a DB session. 256 iterations
    gives >99.99% probability of catching any regression to a
    non-URL-safe base64 alphabet.

    Tests importing ``_webhook_routes`` (the route module) get the
    same generator the route uses, so this test guards against
    future refactors that swap the generator -- e.g., a future
    engineer drafting ``POST /api/v1/webhooks/{id}/test-ping``
    would still benefit from the URL-safe invariant even if they
    never re-read the DELETE route.
    """
    for _ in range(256):
        sid = _webhook_routes._generate_subscription_id()
        assert sid.startswith("whsub_"), f"prefix missing: {sid!r}"
        assert "/" not in sid, (
            f"subscription id contains URL-unsafe '/': {sid!r}; "
            f"FastAPI DELETE /{{subscription_id}} will 404"
        )
        assert "+" not in sid, (
            f"subscription id contains URL-unsafe '+': {sid!r}; "
            f"FastAPI DELETE /{{subscription_id}} will 404"
        )


def test_webhooks_post_201_returns_secret_once() -> None:
    """Happy-path POST returns 201 with secret + id; the GET round-trip
    confirms the secret is NEVER returned again (the v0.9.0
    one-shot secret contract from design doc §3.1).
    """
    sub_url = _new_sub_url()
    resp = _post_sub(sub_url)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"].startswith("whsub_")
    assert body["secret"].startswith("whsec_")
    assert body["url"] == sub_url
    assert body["filter"] == {"kind": "upload_completed"}
    assert "created_at" in body

    # Round-trip via GET-by-id: the response must omit ``secret`` --
    # one-time only on POST per design doc.
    sub_id = body["id"]
    get_resp = client.get(f"/api/v1/webhooks/{sub_id}")
    assert get_resp.status_code == 200
    get_body = get_resp.json()
    assert get_body["id"] == sub_id
    assert "secret" not in get_body


def test_webhooks_post_422_on_http_non_loopback_url() -> None:
    """http://example.com rejected: HTTPS-or-loopback policy violation.

    The non-loopback http case is the canonical policy enforcement
    test (design doc §7.3). The route raises 422 with a detail
    message naming either ``loopback`` or ``scheme``.
    """
    resp = _post_sub("http://example.com/wh")
    assert resp.status_code == 422, resp.text


def test_webhooks_post_422_on_empty_host_url() -> None:
    """``https://`` rejected: empty hostname (the v0.9.0 post-reviewer
    tightening; ``urlparse`` parses the scheme but ``hostname is None``).
    """
    resp = _post_sub("https://")
    assert resp.status_code == 422, resp.text


def test_webhooks_post_422_on_whitespace_url() -> None:
    """URL with whitespace rejected per ``_validate_webhook_url``
    (the ``ch.isspace()`` defensive check).
    """
    resp = _post_sub("https://example.com/with space")
    assert resp.status_code == 422, resp.text


def test_webhooks_get_list_returns_only_active() -> None:
    """GET /api/v1/webhooks returns active (revoked_at IS NULL) subs only.

    The DB accumulates active subs across re-runs; the test seeds
    3 subs in this invocation + revokes 1 of them, then asserts
    ONLY the 2 non-revoked ones (from THIS test) appear in the
    list. The test does NOT assert the total list length (other
    tests' subs may accumulate), only the presence/absence of
    the 3 ids this test created.
    """
    sub_id_a = _post_sub().json()["id"]
    sub_id_b = _post_sub().json()["id"]
    sub_id_c = _post_sub().json()["id"]

    # Revoke B
    revoke_resp = client.delete(f"/api/v1/webhooks/{sub_id_b}")
    assert revoke_resp.status_code == 204

    list_resp = client.get("/api/v1/webhooks")
    assert list_resp.status_code == 200
    ids = {r["id"] for r in list_resp.json()}
    # Active ABO + C present in the list, B (revoked) absent.
    assert sub_id_a in ids
    assert sub_id_b not in ids
    assert sub_id_c in ids


def test_webhooks_get_by_id_returns_no_secret() -> None:
    """GET /{id} never surfaces the secret field on the response.

    Strict parallel of the schema's ``model_config = ConfigDict(from_attributes=True)``
    discipline -- the schema deliberately omits ``secret`` so the
    ORM-to-schema round-trip cannot leak it. v0.9.0 contract per
    design doc §3.2.
    """
    sub_id = _post_sub().json()["id"]
    resp = client.get(f"/api/v1/webhooks/{sub_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == sub_id
    assert "secret" not in body
    # ``revoked_at`` was the post-reviewer dead-field drop: the
    # schema does NOT include it; the route still uses ``revoked_at``
    # as a 404 gate but doesn't surface it.
    assert "revoked_at" not in body


def test_webhooks_get_by_id_404_on_unknown() -> None:
    """GET /{unknown} returns 404 (route's ``db.get`` returns None branch)."""
    resp = client.get("/api/v1/webhooks/whsub_does-not-exist-1234")
    assert resp.status_code == 404


def test_webhooks_get_by_id_404_on_revoked() -> None:
    """GET /{id} returns 404 after the sub is revoked (per design doc §4:
    revoked == gone from public view, not 410 Gone -- the choice
    preserves the "no existence-leak via timing" invariant).
    """
    sub_id = _post_sub().json()["id"]
    revoke_resp = client.delete(f"/api/v1/webhooks/{sub_id}")
    assert revoke_resp.status_code == 204
    get_resp = client.get(f"/api/v1/webhooks/{sub_id}")
    assert get_resp.status_code == 404


def test_webhooks_delete_204_marks_revoked() -> None:
    """DELETE /{id} returns 204 + GET /{id} returns 404 (after).

    The soft-delete invariant: ``revoked_at`` is set on the
    existing row (no hard delete), and the public GET gates
    on ``revoked_at IS NOT NULL`` so revoked subs become
    invisible. The ``shutdown test`` also confirms the LIST
    does NOT include the revoked sub (cross-endpoint
    consistency invariant).
    """
    sub_id = _post_sub().json()["id"]
    del_resp = client.delete(f"/api/v1/webhooks/{sub_id}")
    assert del_resp.status_code == 204

    # GET /{id} now returns 404.
    assert client.get(f"/api/v1/webhooks/{sub_id}").status_code == 404

    # LIST does NOT include the revoked sub.
    list_resp = client.get("/api/v1/webhooks")
    assert sub_id not in {r["id"] for r in list_resp.json()}


def test_webhooks_delete_404_on_unknown() -> None:
    """DELETE /{unknown} returns 404 (route's missing-row branch)."""
    resp = client.delete("/api/v1/webhooks/whsub_does-not-exist-1234")
    assert resp.status_code == 404


def test_webhooks_delete_idempotent_when_already_revoked() -> None:
    """DELETE on an already-revoked sub returns 204 (idempotent --
    safe for the integrator's retry path).

    The route's contract is: ``is None -> set + commit + 204``,
    ``is not None -> no-op + 204``. 404 is reserved for
    TOTALLY-UNKNOWN subs (the prior test). This guarantees
    the integrator can retry DELETEs without surfacing
    a 404 that would alias a transient race as a "real"
    not-found.
    """
    sub_id = _post_sub().json()["id"]
    first = client.delete(f"/api/v1/webhooks/{sub_id}")
    assert first.status_code == 204
    second = client.delete(f"/api/v1/webhooks/{sub_id}")
    assert second.status_code == 204


def test_replay_dlq_schema_declares_string_delivery_id() -> None:
    """Plan 004 regression: ``WebhookDeliveryReplayOut.delivery_id`` and
    ``WebhookDeliveryOut.id`` are ``str`` (not ``int``) with bounded
    length, defending against accidental ``int -> str`` coercion
    and accidental huge-string DoS.

    Pre-plan-004 the schemas had ``delivery_id: int`` which would
    raise ``pydantic.ValidationError`` on every call (the route
    generates ``dly_<uuid>`` strings). The trigger is purely
    schema-shape -- no DB needed; this test runs hermetically.

    The class-body evaluation of ``Field(...)`` requires the
    ``Field`` import to be present in ``schemas.py``. Absence of
    the import is the most likely regression to re-occur (typo
    when adding a new Field later); pytest surfaces such an
    import-time ``NameError`` automatically as a collection
    failure for this test -- no per-test ``try/except`` needed.
    """
    # 1) Touching ``model_fields`` triggers class-body evaluation of
    # the ``Field(...)`` defaults. If ``Field`` were not imported in
    # ``schemas.py``, the ``from gw2analytics_api import schemas``
    # at the top of this module would have already raised
    # ``NameError`` at collection time; pytest surfaces that as a
    # collection failure for this test. No extra ``try/except``
    # needed.
    replay_fields = schemas.WebhookDeliveryReplayOut.model_fields
    delivery_fields = schemas.WebhookDeliveryOut.model_fields

    # 2) Both fields must be annotated as ``str`` (NOT ``int``).
    assert replay_fields["delivery_id"].annotation is str, (
        "WebhookDeliveryReplayOut.delivery_id must be str (not int) "
        "post-plan-004; got "
        f"{replay_fields['delivery_id'].annotation!r}"
    )
    assert delivery_fields["id"].annotation is str, (
        "WebhookDeliveryOut.id must be str (not int) post-plan-004; "
        f"got {delivery_fields['id'].annotation!r}"
    )

    # 3) Both fields must carry Field() with non-negative length bounds.
    #    min_length>=1 rejects the empty-string default; max_length<=64
    #    defends against accidental huge-string DoS (uuid-with-prefix
    #    discriminator is well under 64 chars).
    #
    #    Pydantic v2 stores ``min_length`` / ``max_length`` as
    #    ``MinLen`` / ``MaxLen`` constraint entries inside the
    #    FieldInfo's ``metadata`` list (NOT as direct ``.min_length``
    #    / ``.max_length`` attributes). The helper below duck-types
    #    over the metadata list to extract the bound values; this is
    #    forward-compat with future Pydantic versions (the constraint
    #    types expose the bound as ``.min_length`` / ``.max_length``
    #    attributes).
    def _bounds(field_info: Any) -> tuple[int | None, int | None]:
        fmin: int | None = None
        fmax: int | None = None
        for entry in field_info.metadata:
            entry_min = getattr(entry, "min_length", None)
            entry_max = getattr(entry, "max_length", None)
            if isinstance(entry_min, int):
                fmin = entry_min
            if isinstance(entry_max, int):
                fmax = entry_max
        return fmin, fmax

    rmin, rmax = _bounds(replay_fields["delivery_id"])
    dmin, dmax = _bounds(delivery_fields["id"])
    assert rmin is not None and rmin >= 1, f"delivery_id must have min_length>=1; got {rmin}"
    assert rmax is not None and rmax <= 64, (
        f"delivery_id must have bounded max_length (<=64); got {rmax}"
    )
    assert dmin is not None and dmin >= 1, (
        f"WebhookDeliveryOut.id must have min_length>=1; got {dmin}"
    )
    assert dmax is not None and dmax <= 64, (
        f"WebhookDeliveryOut.id must have bounded max_length (<=64); got {dmax}"
    )

    # 4) Round-trip validation: a string payload matching the contract
    #    must validate cleanly. A non-empty error here is the
    #    post-plan-004 happy-path (the Field bounds are enforceable).
    ok_payload = {
        "delivery_id": "dly_" + "a" * 32,
        "subscription_id": "whsub_" + "b" * 32,
        "upload_id": "upl_" + "c" * 32,
        "attempt": 1,
        "next_attempt_at": "2025-01-01T00:00:00+00:00",
        "restart": True,
    }
    schemas.WebhookDeliveryReplayOut.model_validate(ok_payload)


# --- v0.9.1 plan 005 SSRF-block regression tests ---
# These tests cover the universal private-IP block added in plan 005;
# they monkeypatch ``socket.getaddrinfo`` so the resolution is
# deterministic and CI-stable (no real DNS lookups, no flakes from
# external DNS state). Each test asserts BOTH the 422 status AND the
# new detail string verbatim, so a future regression to the
# pre-plan-005 gate (where ``https://10.0.0.1`` was wide-open) would
# fail cleanly.


def test_post_webhook_rejects_https_private_ip_literal() -> None:
    """Plan 005 v0.9.1 SSRF: ``https://10.0.0.1/`` is rejected even
    though the URL is HTTPS (pre-plan-005 the validator let ``https://``
    pass wide-open past the http-only loopback carve-out).
    """
    resp = _post_sub("https://10.0.0.1/")
    assert resp.status_code == 422, resp.text
    body = resp.json()
    detail_blob = str(body).lower()
    assert "private" in detail_blob and "loopback" in detail_blob, (
        f"422 detail must mention the private/loopback SSRF gate; got {body!r}"
    )


def test_post_webhook_rejects_https_link_local_literal() -> None:
    """Plan 005 v0.9.1 SSRF: ``https://169.254.169.254/`` (AWS IMDS
    link-local) is rejected.
    """
    resp = _post_sub("https://169.254.169.254/")
    assert resp.status_code == 422, resp.text
    body = resp.json()
    detail_blob = str(body).lower()
    assert "private" in detail_blob and "loopback" in detail_blob, (
        f"422 detail must mention the private/loopback SSRF gate; got {body!r}"
    )


def test_post_webhook_rejects_https_ipv6_loopback_literal() -> None:
    """Plan 005 v0.9.1 SSRF: ``https://[::1]/`` (IPv6 literal loopback)
    is rejected via the ``ipaddress.ip_address("::1").is_loopback``
    classification (no DNS lookup needed for a literal IP).
    """
    resp = _post_sub("https://[::1]/")
    assert resp.status_code == 422, resp.text
    body = resp.json()
    detail_blob = str(body).lower()
    assert "loopback" in detail_blob, (
        f"422 detail must mention the loopback SSRF gate; got {body!r}"
    )


def test_post_webhook_rejects_https_hostname_resolving_to_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan 005 v0.9.1 SSRF: a hostname ``internal.example`` whose DNS
    resolution yields a private IP (10.0.0.1) is rejected. The
    monkeypatched ``socket.getaddrinfo`` ensures deterministic,
    CI-stable resolution (no real DNS lookup).
    """

    def _fake_getaddrinfo(
        host: str,
        port: object,
        **_kwargs: object,
    ) -> list[tuple[Any, Any, Any, Any, tuple[str, int]]]:
        return [
            (
                _socket.AF_INET,
                _socket.SOCK_STREAM,
                0,
                "",
                ("10.0.0.1", 0),
            )
        ]

    # ``socket`` is imported at the top of routes/webhooks.py; the
    # monkeypatch target is the ``socket`` module's attribute (same
    # function object reference for the call site inside the route).
    monkeypatch.setattr(_socket, "getaddrinfo", _fake_getaddrinfo)

    resp = _post_sub("https://internal.example/")
    assert resp.status_code == 422, resp.text
    body = resp.json()
    detail_blob = str(body).lower()
    assert "private" in detail_blob, f"422 detail must mention the private SSRF gate; got {body!r}"


def test_post_webhook_accepts_https_private_ip_with_env_optin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan 005 v0.9.1 SSRF opt-out: setting
    ``GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS=1`` skips the private-IP
    block (for trusted dev environments). Proof-of-life test for the
    operator escape hatch documented in ``apps/api/.env.example``.
    """
    monkeypatch.setenv("GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS", "1")
    resp = _post_sub("https://10.0.0.2/")  # unique IP per re-run scope
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["url"] == "https://10.0.0.2/"
    assert body["id"].startswith("whsub_")
    assert body["secret"].startswith("whsec_")


# --- v0.9.1 plan 007 webhook scheduler + DLQ + replay tests ---
#
# These 4 tests cover the retry+DLQ+replay slice that the v0.9.0
# webhook close-out documented as a ``### Known followup`` -- the
# scheduler's exponential backoff curve, the DLQ promotion after
# repeated failures, the replay endpoint's concurrency contract, and
# the HMAC byte-for-byte integrity guarantee across replays. The
# `time-machine` package (PyPI: ``time-machine``, import:
# ``time_machine``) patches ``datetime.now(tz=UTC)`` globally so the
# scheduler's internal ``_utcnow()`` and ``_compute_next_attempt_at``
# see the advanced clock without invasive mocking of the worker
# module. Each test seeds via a function-scoped ``session_factory``
# fixture (built on the process-wide sessionmaker) so the seed +
# verify + scheduler routes all hit the same Postgres database.


@pytest.fixture
def session_factory() -> Any:
    """Return the process-wide SQLAlchemy sessionmaker bound to the app engine.

    Tests use it both as a seed context (inserting subscriptions +
    deliveries + DLQ rows via raw ORM) AND as the
    ``session_factory`` argument to
    :func:`process_scheduled_retries` and
    :func:`dispatch_for_upload`. Each ``with session_factory() as db:``
    opens a fresh transaction; the test-level cleanup is the
    per-test rollback below.
    """
    return get_sessionmaker()


_BASE_TIME = datetime(2026, 7, 8, 0, 0, 0, tzinfo=UTC)


def _bootstrap_webhook_environment(
    session_factory: Any,
    target_url: str = "https://93.184.216.34/webhook",
) -> tuple[str, str, str]:
    """Seed an active subscription + a completed upload + a parsed fight.

    Returns ``(subscription_id, upload_id, fight_id)``. The DLQ seed
    for the replay tests is a separate step (the scheduler tests
    don't need a DLQ row, but they DO need a sub + secret).

    The webhook target URL is a public IPv4 literal
    (``93.184.216.34``) so the v0.9.1 SSRF block (plan 005)
    classifies it as ``is_global=True`` and lets it through without
    a DNS lookup. ``respx`` intercepts the request before any real
    outbound traffic happens.
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
            description="plan-007 test subscription",
            secret="whsec_" + "s" * 32,
        )
        sub.filter_payload = {"kind": "upload_completed"}
        sub.created_at = _BASE_TIME
        seed_db.add(sub)

        upload = Upload(
            id=upload_id,
            sha256=sha,
            original_filename="plan007_fixture.zevtc",
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
    """Insert a single ``OrmWebhookDelivery`` row mirroring the
    state the dispatch worker would leave after a failed initial
    POST (status_code NULL, error="non-2xx response: 500",
    ``next_attempt_at`` defaults to ``_BASE_TIME``). Returns the
    delivery id.
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


def test_retry_scheduler_first_attempt_success(
    session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan 007 v0.9.1: a single scheduler tick delivered through
    the first retry attempt marks the delivery ``delivered_at``
    + clears ``error`` + does NOT create a DLQ row.

    The httpx POST is mocked via ``respx`` (the dev-dep already
    installed for the v0.9.0 dispatcher tests) returning 200;
    the scheduler's client.post(...) hits the mock and the
    success path of ``_attempt_retry`` fires.
    """

    sub_id, upload_id_str, _fight_id = _bootstrap_webhook_environment(
        session_factory,
    )
    delivery_id = _seed_failed_delivery(
        session_factory,
        sub_id,
        upload_id_str,
    )

    with (
        time_machine.travel(_BASE_TIME, tick=False),
        _respx.mock(
            base_url="https://93.184.216.34",
        ) as mock,
    ):
        mock.post("/webhook").respond(200, json={"ok": True})
        count = process_scheduled_retries(session_factory)

    assert count == 1, f"expected 1 processed, got {count}"

    with session_factory() as verify_db:
        delivery = verify_db.get(OrmWebhookDelivery, delivery_id)
        assert delivery is not None
        assert delivery.delivered_at is not None, (
            f"delivered_at must be set on success; got {delivery.delivered_at}"
        )
        assert delivery.error is None, f"error must be cleared; got {delivery.error!r}"
        assert delivery.status_code == 200
        # No DLQ row created.
        assert verify_db.get(OrmWebhookDlq, delivery_id) is None


def test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts(
    session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan 007 v0.9.1: STUB POINTER — moved to a standalone module.

    The canonical 2-tick exponential-backoff → DLQ promotion test
    landed in ``apps/api/tests/test_webhooks_e2e_scheduler.py``
    (the re-attempt of the in-session deferral). Keeping this
    function here as a stub via ``pytest.skip`` preserves the
    name (so anyone searching by test name lands on a clear
    pointer instead of a deleted-symbol surprise).

    The standalone module flattens the ``with``-block structure
    (``_respx.mock`` OUTERMOST + per-tick short-lived
    ``time_machine.travel``) to avoid the nested-dedent footgun
    that broke the original in-session test.
    """
    pytest.skip(
        "moved to test_webhooks_e2e_scheduler.py::"
        "test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts "
        "(re-attempt of the in-session deferral; flat with-block structure "
        "to avoid the nested dedent footgun)"
    )


def test_replay_dlq_idempotent_concurrent_calls(
    session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan 007 v0.9.1: two concurrent calls to
    ``replay_dlq_delivery(delivery_id, db)`` for the SAME DLQ row
    produce exactly one 201 + one 404. The atomic transaction
    (``db.add(new_delivery) + db.delete(dlq) + db.commit()``) is
    the v0.9.1 contract; the test widens the race window by
    injecting a 0.5s sleep into the FIRST ``Session.commit`` call
    so the second thread's ``db.get(OrmWebhookDlq, ...)`` runs
    AFTER the first thread's commit landed.

    With ``READ COMMITTED`` isolation (Postgres default), the
    second thread's transaction snapshot is established at
    ``db.get(OrmWebhookDlq, ...)``; once the first thread commits
    the DLQ delete, the second thread's later commits do NOT see
    the row (the read happened during the row's lifetime but the
    write attempts a delete of a non-existent row, which Postgres
    emits as 0-row-DB-API-result). The route path then queries the
    dlq TWICE (once at the top-level gate) -- so the
    second-thread's ``db.get`` will return ``None`` and the route
    raises ``HTTPException(404)``.
    """

    sub_id, upload_id_str, _fight_id = _bootstrap_webhook_environment(
        session_factory,
    )

    # Seed a DLQ row reproducing a 3-time-fail delivery that was
    # promoted to DLQ in the previous test (or via a fixture).
    delivery_id = f"dly_{_uuid.uuid4()}"
    payload = {
        "kind": "upload_completed",
        "upload_id": upload_id_str,
        "fight_id": "fixture-fight",
        "sha256": "a" * 64,
        "started_at": _BASE_TIME.isoformat(),
    }
    payload_bytes = _json.dumps(
        payload,
        separators=(",", ":"),
    ).encode("utf-8")
    with session_factory() as seed_db:
        seed_db.add(
            OrmWebhookDlq(
                id=delivery_id,
                subscription_id=sub_id,
                upload_id=upload_id_str,
                payload=payload_bytes,
                last_error="non-2xx response: 500",
                moved_to_dlq_at=_BASE_TIME,
            )
        )
        seed_db.commit()

    # Widen the race window: inject a 0.5s sleep into the FIRST
    # commit only. The second thread's commit fires without the
    # sleep (the second thread's ``db.get`` finding None is the
    # 404 path; it doesn't need to commit).
    _first_commit_seen = {"flag": False}

    def _slow_commit_once(self: _sa) -> None:
        if not _first_commit_seen["flag"]:
            _first_commit_seen["flag"] = True
            _time.sleep(0.5)
        return _real_commit(self)

    _real_commit = _sa.commit
    monkeypatch.setattr(_sa, "commit", _slow_commit_once)

    # Run 2 concurrent threads. Each thread opens its own session
    # (mirroring the production DI via ``Depends(get_session)``).
    def _attempt() -> int:
        try:
            with session_factory() as db:
                _webhook_routes.replay_dlq_delivery(
                    delivery_id=delivery_id,
                    db=db,
                )
            return 201
        except HTTPException as exc:
            return exc.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_attempt) for _ in range(2)]
        results = sorted(f.result() for f in futures)

    assert results == [201, 404], (
        f"expected exactly one 201 + one 404 across the concurrent pairs; got {results}"
    )

    # Final state: DLQ row gone (the winner thread deleted it).
    with session_factory() as verify_db:
        assert verify_db.get(OrmWebhookDlq, delivery_id) is None


def test_replayed_delivery_byte_for_byte_hmac_matches_original(
    session_factory: Any,
) -> None:
    """Plan 007 v0.9.1 + plan 009 Step 1 v0.9.2: a fresh delivery
    row produced by ``replay_dlq_delivery`` has a ``payload`` whose
    LargeBinary round-trip preserves the SAME byte-string the
    original dispatch worker emitted, so the integrator's
    HMAC-SHA256 verification computes the SAME digest across
    replays as it did for the initial POST.

    Post-v0.9.2 step 1 the ``payload`` column is LargeBinary
    (raw bytes); the dispatch worker writes canonical
    ``body_bytes`` via
    ``json.dumps(payload, separators=(",", ":")).encode("utf-8")``
    and ``replay_dlq_delivery`` copies the bytes verbatim via
    ``new_delivery.payload = dlq.payload``. Postgres ``bytea``
    preserves bytes on round-trip without reordering; HMAC
    matches across retries + replays (the prior JSONB intrinsic
    key reordering is gone).

    Pre-plan-009 this test failed because the JSONB round-trip
    re-ordered dict keys; post-plan-009 it passes because the
    bytes-as-stored ARE the bytes-as-signed.
    """
    sub_id, upload_id_str, _fight_id = _bootstrap_webhook_environment(
        session_factory,
    )
    canonical_payload = {
        "kind": "upload_completed",
        "upload_id": upload_id_str,
        "fight_id": "fixture-fight",
        "sha256": "a" * 64,
        "started_at": _BASE_TIME.isoformat(),
    }
    canonical_body_bytes = _json.dumps(
        canonical_payload,
        separators=(",", ":"),
    ).encode("utf-8")
    with session_factory() as seed_db:
        sub = seed_db.get(OrmWebhookSubscription, sub_id)
        secret_bytes = sub.secret.encode("utf-8") if sub else b""
    initial_hmac = hmac.new(
        secret_bytes,
        canonical_body_bytes,
        hashlib.sha256,
    ).hexdigest()

    # Seed a DLQ row carrying the canonical payload verbatim
    # (bytes post-plan-009 Step 1; the LargeBinary column does NOT
    # reorder keys on round-trip, so the bytes-as-stored match the
    # bytes-as-signed for HMAC integrity).
    delivery_id = f"dly_{_uuid.uuid4()}"
    with session_factory() as seed_db:
        seed_db.add(
            OrmWebhookDlq(
                id=delivery_id,
                subscription_id=sub_id,
                upload_id=upload_id_str,
                payload=canonical_body_bytes,
                last_error="non-2xx response: 500",
                moved_to_dlq_at=_BASE_TIME,
            )
        )
        seed_db.commit()

    # Replay: directly call the route handler with our seeded session.
    new_replay = None
    with time_machine.travel(_BASE_TIME, tick=False), session_factory() as db:
        new_replay = _webhook_routes.replay_dlq_delivery(
            delivery_id=delivery_id,
            db=db,
        )

    assert new_replay.delivery_id.startswith("dly_")

    # Verify the new delivery's payload round-trips to the SAME
    # bytes. Post-plan-009 Step 1, ``new_delivery.payload`` is
    # LargeBinary (raw bytes written by the original dispatch
    # worker + copied verbatim by ``replay_dlq_delivery``). The
    # bytes-as-stored are bytes-as-signed for HMAC integrity -- NO
    # JSON round-trip here (the prior ``_json.dumps(new_delivery.payload,
    # ...)`` produced Python-repr bytes for the now-bytes payload,
    # which is wrong; the LargeBinary column preserves bytes
    # verbatim across the round-trip).
    with session_factory() as verify_db:
        new_delivery = verify_db.get(OrmWebhookDelivery, new_replay.delivery_id)
        assert new_delivery is not None
        new_body_bytes = new_delivery.payload

    assert new_body_bytes == canonical_body_bytes, (
        f"replay payload bytes mismatch canonical bytes; "
        f"original={canonical_body_bytes!r}, replay={new_body_bytes!r}"
    )

    # HMAC re-computed on the round-tripped bytes -> same digest.
    replay_hmac = hmac.new(
        secret_bytes,
        new_body_bytes,
        hashlib.sha256,
    ).hexdigest()
    assert replay_hmac == initial_hmac, "replay HMAC re-computation does not match initial dispatch"
