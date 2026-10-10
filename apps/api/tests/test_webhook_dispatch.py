"""Unit tests for the webhook worker's delivery and failure boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from gw2analytics_api.workers import webhook_dispatch


def _request() -> webhook_dispatch._DeliveryRequest:
    return webhook_dispatch._DeliveryRequest(
        delivery_id="dly_test",
        subscription_id="sub_test",
        url="https://subscriber.example.test/webhook",
        headers={"X-Gw2Analytics-Delivery": "dly_test"},
        body_bytes=b'{"kind":"upload_completed"}',
    )


def _session_factory() -> object:
    return object()


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[object]:
        return self.rows


class _Session:
    def __init__(self, upload: object | None, rows: list[object]) -> None:
        self.upload = upload
        self.rows = rows
        self.added: list[object] = []
        self.commits = 0

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, _model: object, _upload_id: object) -> object | None:
        return self.upload

    def execute(self, _query: object) -> _Result:
        return _Result(self.rows)

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1


class _Delivery:
    def __init__(self, **values: object) -> None:
        self.__dict__.update(values)


@pytest.mark.asyncio
async def test_dispatch_single_records_success_non_2xx_and_network_error() -> None:
    request = _request()

    async def success_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(success_handler)) as client:
        success = await webhook_dispatch._dispatch_single_async(client, request)
    assert success.status_code == 204
    assert success.error is None
    assert success.delivered_at is not None

    async def rejected_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(rejected_handler)) as client:
        rejected = await webhook_dispatch._dispatch_single_async(client, request)
    assert rejected.status_code == 503
    assert rejected.error == "non-2xx response: 503"

    async def offline_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(offline_handler)) as client:
        offline = await webhook_dispatch._dispatch_single_async(client, request)
    assert offline.status_code is None
    assert offline.error == "ConnectError: offline"


@pytest.mark.asyncio
async def test_dispatch_for_upload_skips_when_prepare_has_no_deliveries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def to_thread(func: object, *_args: object) -> object:
        assert func is webhook_dispatch._prepare_deliveries
        return webhook_dispatch._NoDispatchReason("nothing to send")

    monkeypatch.setattr(webhook_dispatch.asyncio, "to_thread", to_thread)

    await webhook_dispatch.dispatch_for_upload(_session_factory, uuid4())


@pytest.mark.asyncio
async def test_dispatch_for_upload_finalizes_success_and_ignores_worker_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    finalized: list[list[webhook_dispatch._DeliveryOutcome]] = []

    async def to_thread(func: object, *_args: object) -> object:
        if func is webhook_dispatch._prepare_deliveries:
            return [request, request]
        if func is webhook_dispatch._finalize_deliveries:
            finalized.append(_args[1])  # type: ignore[arg-type]
            return None
        raise AssertionError(f"unexpected thread target: {func}")

    calls = 0

    async def dispatch_single(
        _client: httpx.AsyncClient,
        _request: webhook_dispatch._DeliveryRequest,
    ) -> webhook_dispatch._DeliveryOutcome:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("subscriber bug")
        return webhook_dispatch._DeliveryOutcome(
            delivery_id="dly_test",
            status_code=200,
            error=None,
            delivered_at=webhook_dispatch.utcnow(),
        )

    monkeypatch.setattr(webhook_dispatch.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(webhook_dispatch, "_dispatch_single_async", dispatch_single)
    monkeypatch.setattr(
        webhook_dispatch,
        "get_settings",
        lambda: SimpleNamespace(webhook_dispatch_timeout_s=1),
    )

    await webhook_dispatch.dispatch_for_upload(_session_factory, uuid4())

    assert len(finalized) == 1
    assert finalized[0][0].status_code == 200


@pytest.mark.asyncio
async def test_dispatch_for_upload_reraises_database_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def prepare_failure(_func: object, *_args: object) -> object:
        raise SQLAlchemyError("prepare failed")

    monkeypatch.setattr(webhook_dispatch.asyncio, "to_thread", prepare_failure)
    with pytest.raises(SQLAlchemyError, match="prepare failed"):
        await webhook_dispatch.dispatch_for_upload(_session_factory, uuid4())

    request = _request()

    async def finalize_failure(func: object, *_args: object) -> object:
        if func is webhook_dispatch._prepare_deliveries:
            return [request]
        raise SQLAlchemyError("finalize failed")

    async def dispatch_single(
        _client: httpx.AsyncClient,
        _request: webhook_dispatch._DeliveryRequest,
    ) -> webhook_dispatch._DeliveryOutcome:
        return webhook_dispatch._DeliveryOutcome("dly_test", 200, None, webhook_dispatch.utcnow())

    monkeypatch.setattr(webhook_dispatch.asyncio, "to_thread", finalize_failure)
    monkeypatch.setattr(webhook_dispatch, "_dispatch_single_async", dispatch_single)
    monkeypatch.setattr(
        webhook_dispatch,
        "get_settings",
        lambda: SimpleNamespace(webhook_dispatch_timeout_s=1),
    )
    with pytest.raises(SQLAlchemyError, match="finalize failed"):
        await webhook_dispatch.dispatch_for_upload(_session_factory, uuid4())


def test_prepare_deliveries_handles_non_dispatchable_uploads() -> None:
    upload_id = uuid4()
    missing = _Session(None, [])
    assert isinstance(
        webhook_dispatch._prepare_deliveries(lambda: missing, upload_id),
        webhook_dispatch._NoDispatchReason,
    )

    incomplete = _Session(SimpleNamespace(status="PENDING", fight=None), [])
    assert isinstance(
        webhook_dispatch._prepare_deliveries(lambda: incomplete, upload_id),
        webhook_dispatch._NoDispatchReason,
    )

    without_fight = _Session(
        SimpleNamespace(status=webhook_dispatch.UPLOAD_STATUS_COMPLETED, fight=None),
        [],
    )
    assert isinstance(
        webhook_dispatch._prepare_deliveries(lambda: without_fight, upload_id),
        webhook_dispatch._NoDispatchReason,
    )


def test_prepare_deliveries_records_corruption_and_builds_signed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_id = uuid4()
    upload = SimpleNamespace(
        id=upload_id,
        status=webhook_dispatch.UPLOAD_STATUS_COMPLETED,
        sha256="digest",
        fight=SimpleNamespace(id="fight-1", started_at=datetime(2026, 1, 1, tzinfo=UTC)),
    )
    valid = SimpleNamespace(
        id="sub-valid",
        ciphertext="valid",
        filter_payload={"kind": "upload_completed"},
        url="https://subscriber.example.test/webhook",
    )
    corrupt = SimpleNamespace(
        id="sub-corrupt",
        ciphertext="corrupt",
        filter_payload={"kind": "upload_completed"},
        url="https://subscriber.example.test/webhook",
    )
    ignored = SimpleNamespace(
        id="sub-ignored",
        ciphertext="ignored",
        filter_payload={"kind": "other"},
        url="https://subscriber.example.test/webhook",
    )
    session = _Session(upload, [valid, corrupt, ignored])
    monkeypatch.setattr(webhook_dispatch, "OrmWebhookDelivery", _Delivery)
    monkeypatch.setattr(webhook_dispatch, "_generate_delivery_id", lambda: "dly_fixed")

    def decrypt(ciphertext: str) -> str:
        if ciphertext == "corrupt":
            raise webhook_dispatch.FernetInvalidToken("bad ciphertext")
        return "secret"

    monkeypatch.setattr(webhook_dispatch, "decrypt_webhook_secret", decrypt)

    requests = webhook_dispatch._prepare_deliveries(lambda: session, upload_id)

    assert len(requests) == 1
    assert requests[0].headers["X-Gw2Analytics-Signature"].startswith("sha256=")
    assert requests[0].body_bytes == (
        b'{"kind":"upload_completed","upload_id":"' + str(upload_id).encode() + b'"'
        b',"fight_id":"fight-1","sha256":"digest","started_at":"2026-01-01T00:00:00+00:00"}'
    )
    assert len(session.added) == 2
    assert session.commits == 1


def test_finalize_deliveries_updates_existing_rows_and_ignores_missing() -> None:
    delivery = SimpleNamespace(id="dly-present", status_code=None, error=None, delivered_at=None)
    session = _Session(None, [delivery])
    delivered_at = webhook_dispatch.utcnow()

    webhook_dispatch._finalize_deliveries(lambda: session, [])
    assert session.commits == 0

    webhook_dispatch._finalize_deliveries(
        lambda: session,
        [
            webhook_dispatch._DeliveryOutcome("dly-present", 202, None, delivered_at),
            webhook_dispatch._DeliveryOutcome("dly-missing", None, "offline", None),
        ],
    )

    assert (delivery.status_code, delivery.error, delivery.delivered_at) == (
        202,
        None,
        delivered_at,
    )
    assert session.commits == 1
