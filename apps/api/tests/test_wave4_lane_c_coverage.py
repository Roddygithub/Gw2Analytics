"""Wave 4 lane C: security, API error, repository, and service coverage."""

from __future__ import annotations

import asyncio
import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request, UploadFile
from starlette.datastructures import Headers

from gw2analytics_api import auth, crypto
from gw2analytics_api.models import OrmFight, OrmWebhookSubscription, Upload
from gw2analytics_api.repositories import (
    FightRepository,
    GuildRepository,
    UploadRepository,
    WebhookRepository,
)
from gw2analytics_api.routes import uploads, webhooks
from gw2analytics_api.services import cache_service, guild_service


def _request(*, api_key: str | None = None, headers: dict[str, str] | None = None) -> Request:
    raw = {**(headers or {})}
    if api_key is not None:
        raw["x-api-key"] = api_key
    return Request({"type": "http", "method": "GET", "path": "/", "headers": Headers(raw).raw})


# auth (6)
def test_auth_disabled_calls_sync_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(api_key=None))
    handler = auth.require_auth(lambda: "ok")
    assert asyncio.run(handler()) == "ok"


def test_auth_disabled_awaits_async_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(api_key=None))

    async def handler() -> str:
        return "ok"

    assert asyncio.run(auth.require_auth(handler)()) == "ok"


def test_auth_configured_without_request_rejects_before_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(api_key="secret"))
    original_handler = MagicMock(return_value="ok")
    handler = auth.require_auth(original_handler)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(_request()))
    assert exc.value.status_code == 401
    original_handler.assert_not_called()


def test_auth_rejects_missing_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(api_key="secret"))
    handler = auth.require_auth(lambda request: "unreachable")
    with pytest.raises(HTTPException, match="Missing or invalid"):
        asyncio.run(handler(_request()))


def test_auth_rejects_wrong_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(api_key="secret"))
    handler = auth.require_auth(lambda request: "unreachable")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(_request(api_key="wrong")))
    assert exc.value.status_code == 401


def test_auth_accepts_matching_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(api_key="secret"))
    handler = auth.require_auth(lambda request: "ok")
    assert asyncio.run(handler(_request(api_key="secret"))) == "ok"


# crypto KEK (1)
def test_crypto_explicit_kek_round_trip_is_bytes_at_rest() -> None:
    kek = crypto.Fernet.generate_key().decode()
    ciphertext = crypto.encrypt_webhook_secret("secret", kek=kek)
    assert ciphertext != b"secret"
    assert crypto.decrypt_webhook_secret(ciphertext, kek=kek) == "secret"


# uploads (8)
@pytest.mark.asyncio
async def test_upload_reader_uses_small_file_fast_path() -> None:
    file = UploadFile(io.BytesIO(b"abc"), filename="a.zevtc")
    file.size = 3
    data, digest = await uploads._read_upload_streaming(file, 10)
    assert data == b"abc"
    assert len(digest) == 64


@pytest.mark.asyncio
async def test_upload_reader_streams_unknown_size() -> None:
    file = UploadFile(io.BytesIO(b"abc"), filename="a.zevtc")
    file.size = None
    data, _ = await uploads._read_upload_streaming(file, 10)
    assert data == b"abc"


@pytest.mark.asyncio
async def test_upload_reader_rejects_small_path_overflow() -> None:
    file = UploadFile(io.BytesIO(b"1234"), filename="a.zevtc")
    file.size = 4
    with pytest.raises(HTTPException) as exc:
        await uploads._read_upload_streaming(file, 3)
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_upload_reader_rejects_streamed_overflow() -> None:
    file = UploadFile(io.BytesIO(b"1234"), filename="a.zevtc")
    file.size = None
    with pytest.raises(HTTPException) as exc:
        await uploads._read_upload_streaming(file, 3)
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_enqueue_parse_uses_arq_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = MagicMock()
    pool.enqueue_job = AsyncMock()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq_pool=pool)))
    monkeypatch.setattr(
        uploads._config,
        "get_settings",
        lambda: SimpleNamespace(allow_inrequest_parse_fallback=False),
    )
    await uploads._enqueue_parse(request, uuid.uuid4(), b"raw")
    pool.enqueue_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_parse_rejects_unavailable_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq_pool=None)))
    monkeypatch.setattr(
        uploads._config,
        "get_settings",
        lambda: SimpleNamespace(allow_inrequest_parse_fallback=False),
    )
    with pytest.raises(HTTPException) as exc:
        await uploads._enqueue_parse(request, uuid.uuid4(), b"raw")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_enqueue_parse_fallback_runs_parse_and_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq_pool=None)))
    monkeypatch.setattr(
        uploads._config,
        "get_settings",
        lambda: SimpleNamespace(allow_inrequest_parse_fallback=True),
    )
    parse = MagicMock()
    dispatch = AsyncMock()
    monkeypatch.setattr(uploads, "process_parse", parse)
    monkeypatch.setattr(uploads, "dispatch_for_upload", dispatch)
    monkeypatch.setattr(uploads, "get_sessionmaker", lambda: "session-factory")
    upload_id = uuid.uuid4()
    await uploads._enqueue_parse(request, upload_id, b"raw")
    parse.assert_called_once_with("session-factory", upload_id, b"raw")
    dispatch.assert_awaited_once_with("session-factory", upload_id)


@pytest.mark.asyncio
async def test_create_upload_rejects_unsupported_media_type() -> None:
    request = _request(headers={"content-length": "3"})
    file = UploadFile(
        io.BytesIO(b"abc"),
        filename="x.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    with pytest.raises(HTTPException) as exc:
        await uploads.create_upload(request, file, MagicMock())
    assert exc.value.status_code == 415


# webhooks / SSRF (9)
def test_webhook_rejects_non_https_public_url() -> None:
    with pytest.raises(HTTPException, match="http scheme"):
        webhooks._validate_webhook_url("http://example.com/hook")


def test_webhook_rejects_missing_host() -> None:
    with pytest.raises(HTTPException):
        webhooks._validate_webhook_url("https:///hook")


def test_webhook_rejects_whitespace_url() -> None:
    with pytest.raises(HTTPException):
        webhooks._validate_webhook_url("   ")


def test_webhook_rejects_private_ipv4_literal() -> None:
    with pytest.raises(HTTPException):
        webhooks._validate_webhook_url("https://10.0.0.1/hook")


def test_webhook_rejects_link_local_literal() -> None:
    with pytest.raises(HTTPException):
        webhooks._validate_webhook_url("https://169.254.169.254/hook")


def test_webhook_rejects_ipv6_loopback_literal() -> None:
    with pytest.raises(HTTPException):
        webhooks._validate_webhook_url("https://[::1]/hook")


def test_webhook_rejects_hostname_resolving_to_private(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        webhooks.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(0, 0, 0, "", ("192.168.1.2", 443))],
    )
    with pytest.raises(HTTPException):
        webhooks._validate_webhook_url("https://internal.example/hook")


def test_webhook_dns_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> list[object]:
        raise webhooks.socket.gaierror("no DNS")

    monkeypatch.setattr(webhooks.socket, "getaddrinfo", fail)
    with pytest.raises(HTTPException):
        webhooks._validate_webhook_url("https://unknown.example/hook")


def test_webhook_private_literal_opt_out_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        webhooks,
        "get_settings",
        lambda: SimpleNamespace(gw2analytics_allow_private_webhook_urls=True),
    )
    webhooks._validate_webhook_url("https://127.0.0.1/hook")


# repositories (4)
def test_upload_repository_reads_by_id_and_sha() -> None:
    session = MagicMock()
    upload = object()
    upload_id = uuid.uuid4()
    session.get.return_value = upload
    session.execute.return_value.scalar_one_or_none.return_value = upload
    repo = UploadRepository(session)
    assert repo.get_by_id(upload_id) is upload
    session.get.assert_called_once_with(Upload, upload_id)

    assert repo.find_by_sha256("hash") is upload
    statement = session.execute.call_args.args[0]
    compiled = statement.compile(compile_kwargs={"literal_binds": True}).string
    assert "sha256" in compiled
    assert "'hash'" in compiled


def test_webhook_repository_returns_active_subscriptions() -> None:
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = ["active"]
    assert WebhookRepository(session).find_active_subscriptions() == ["active"]

    statement = session.execute.call_args.args[0]
    assert statement.column_descriptions[0]["entity"] is OrmWebhookSubscription
    where_sql = str(statement.whereclause.compile(compile_kwargs={"literal_binds": True}))
    assert "revoked_at IS NULL" in where_sql


def test_fight_repository_loads_fight_with_related_rows() -> None:
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = "fight"
    assert FightRepository(session).get_by_id_with_agents_and_skills("fight-id") == "fight"

    statement = session.execute.call_args.args[0]
    assert statement.column_descriptions[0]["entity"] is OrmFight
    where_sql = str(statement.whereclause.compile(compile_kwargs={"literal_binds": True}))
    assert "'fight-id'" in where_sql
    assert len(statement._with_options) == 2


def test_guild_repository_finds_distinct_account_memberships() -> None:
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = ["guild"]
    assert GuildRepository(session).find_guilds_for_account("Commander") == ["guild"]

    statement = session.execute.call_args.args[0]
    compiled = statement.compile(compile_kwargs={"literal_binds": True}).string
    assert "JOIN" in compiled
    assert "guild_members.account_name = 'Commander'" in compiled
    assert statement._distinct


# services (2)
def test_guild_service_delegates_to_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = MagicMock()
    repo.find_guilds_for_account.return_value = ["guild"]
    monkeypatch.setattr(guild_service, "GuildRepository", lambda db: repo)
    assert guild_service.list_guilds_for_account("db", "Commander") == ["guild"]
    repo.find_guilds_for_account.assert_called_once_with("Commander")


@pytest.mark.asyncio
async def test_cache_service_returns_hit_and_computes_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    class Redis:
        def __init__(self) -> None:
            self.values = {"hit": '{"ok": true}'}

        async def get(self, key: str) -> str | None:
            return self.values.get(key)

        async def setex(self, key: str, ttl: int, value: str) -> None:
            self.values[key] = value

        async def delete(self, key: str) -> int:
            return 1

        async def aclose(self) -> None:
            pass

    redis = Redis()
    monkeypatch.setattr(cache_service.aioredis, "from_url", lambda *args, **kwargs: redis)
    service = cache_service.CacheService(default_ttl=7)
    assert await service.get_or_compute("hit", AsyncMock(return_value="wrong")) == {"ok": True}
    assert await service.get_or_compute("miss", AsyncMock(return_value=[1])) == [1]
    await service.close()
