"""v0.10.1 plan 010: tests for the Arq integration in the upload route.

The route handler :func:`gw2analytics_api.routes.uploads.create_upload`
dispatches the parse + webhook chain via the Arq pool if
``app.state.arq_pool`` is set, and falls back to
``asyncio.to_thread`` (mimicking the pre-v0.10.1 BackgroundTasks
behavior) if the pool is ``None``.

These tests pin the dispatch contract:

1. **Arq path (mocked)**: a POST with the Arq pool set
   enqueues the job via ``pool.enqueue_job`` with the
   canonical ``("parse_job", str(upload_id), raw)``
   argument tuple. The parse does NOT run inline.
2. **Fallback path (no Arq)**: a POST with the Arq pool
   ``None`` runs the parse synchronously in a thread, the
   upload row's status flips to ``"completed"``, and the
   existing test contract
   (``wait_for_upload_completion`` polls + the row is
   queryable via ``GET /uploads/{id}``) is preserved.
3. **Idempotent re-parse**: a POST whose ``Upload.status
   == "failed"`` enqueues the Arq job (or the fallback)
   for re-parse. The re-parse path is the same as the
   primary path -- there is no separate code branch.

Hermetic: the conftest autouse fixture
:func:`_disable_arq_for_tests` sets the Arq pool to ``None``
so the fallback path is the default; the Arq path test
overrides the pool to a mock via a local fixture.
"""

from __future__ import annotations

import time
import uuid as _uuid
from collections.abc import Generator
from typing import Any

import pytest
from _fixtures import make_minimal_zevtc
from fastapi.testclient import TestClient

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.main import app
from gw2analytics_api.models import Upload

# ---------------------------------------------------------------------
# Arq-path fixtures
# ---------------------------------------------------------------------


class _MockArqPool:
    """In-memory Arq pool for tests that verify the enqueue contract.

    ``enqueue_job`` is awaited by the route handler; the mock
    records the call args + kwargs into a list and returns
    immediately. The actual ``parse_job`` does NOT run (no
    Redis broker, no Arq worker process); tests assert on
    the recorded calls.
    """

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.enqueued.append((name, args, kwargs))


@pytest.fixture
def mock_arq_pool() -> Generator[_MockArqPool, None, None]:
    """Install a mock Arq pool on ``app.state`` for the test scope.

    The fixture restores the previous ``arq_pool`` value on
    teardown so subsequent tests see the conftest's default
    (pool is ``None``).
    """
    pool = _MockArqPool()
    previous = getattr(app.state, "arq_pool", None)
    app.state.arq_pool = pool
    try:
        yield pool
    finally:
        app.state.arq_pool = previous


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------


def test_create_upload_enqueues_via_arq(
    client: TestClient,
    mock_arq_pool: _MockArqPool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the Arq pool is set, POST enqueues the parse job (no inline run)."""
    # v0.10.2 hotfix followup #11: the dev workflow sets
    # ALLOW_INREQUEST_PARSE_FALLBACK=1 globally (via dev-api-bg.sh). The
    # arq-path test must opt out so the route's new "pool reachable but
    # operator opted in" bypass does not silently re-route to inline.
    monkeypatch.delenv("ALLOW_INREQUEST_PARSE_FALLBACK", raising=False)
    blob = make_minimal_zevtc(
        agents=[(100_001, 2, 18, "V10 Warrior ARQ", True)],
        build="20251015",
    )
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("arq_sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]
    assert len(mock_arq_pool.enqueued) == 1
    name, args, _ = mock_arq_pool.enqueued[0]
    assert name == "parse_job"
    # First positional arg is ``upload_id`` as str.
    assert args[0] == upload_id
    # Second positional arg is the raw bytes (preserved end-to-end
    # so the Arq worker can re-parse without a MinIO round-trip).
    assert args[1] == blob
    # The upload row should still be "pending" because the parse
    # has NOT run yet (the mock Arq pool does not invoke the
    # job -- it just records the call).
    upload = client.get(f"/api/v1/uploads/{upload_id}").json()
    assert upload["status"] == "pending"


def test_create_upload_falls_back_to_background_tasks(
    client: TestClient,
) -> None:
    """When the Arq pool is None, the parse runs synchronously via
    ``asyncio.to_thread`` and the upload row flips to ``completed``."""
    # The conftest's ``_disable_arq_for_tests`` autouse fixture
    # already set the Arq pool to ``None`` (via the disabled
    # Redis host). Assert the contract: no Arq pool, parse
    # runs inline, status flips.
    assert getattr(app.state, "arq_pool", None) is None
    blob = make_minimal_zevtc(
        agents=[(100_002, 2, 18, "V10 Warrior FALLBACK", True)],
        build="20251016",
    )
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("fb_sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]
    # Poll for the status flip (max 5s; the parse is
    # milliseconds for a fixture-sized blob).
    for _ in range(50):
        upload = client.get(f"/api/v1/uploads/{upload_id}").json()
        if upload["status"] == "completed":
            assert upload["fight_id"] is not None
            return
        if upload["status"] == "failed":
            pytest.fail(f"upload {upload_id} failed: {upload.get('error_message')}")
        time.sleep(0.1)
    pytest.fail(f"upload {upload_id} did not reach 'completed' within 5s")


def test_create_upload_idempotent_existing_failed_enqueues(
    client: TestClient,
    mock_arq_pool: _MockArqPool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-upload of a SHA matching an existing ``failed`` upload re-enqueues."""
    # v0.10.2 hotfix followup #11: see test_create_upload_enqueues_via_arq.
    monkeypatch.delenv("ALLOW_INREQUEST_PARSE_FALLBACK", raising=False)
    blob = make_minimal_zevtc(
        agents=[(100_003, 2, 18, "V10 Warrior IDEMPOTENT", True)],
        build="20251017",
    )
    # First POST: simulates a previously-failed parse by
    # monkey-patching the Upload row to status="failed"
    # after the first POST commits.
    resp1 = client.post(
        "/api/v1/uploads",
        files={"file": ("idem_sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp1.status_code == 201, resp1.text
    upload_id = resp1.json()["id"]
    # Flip the row to "failed" via direct ORM.
    with get_sessionmaker()() as db:
        upload = db.get(Upload, _uuid.UUID(upload_id))
        assert upload is not None
        upload.status = "failed"
        db.commit()
    # Reset the mock so the second POST's enqueue is the
    # only one recorded (the first POST's enqueue was the
    # primary path; the second's is the re-parse path).
    mock_arq_pool.enqueued.clear()
    # Second POST with the same SHA: idempotent path,
    # should re-enqueue.
    resp2 = client.post(
        "/api/v1/uploads",
        files={"file": ("idem_sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp2.status_code == 201, resp2.text
    assert resp2.json()["id"] == upload_id  # same upload row
    assert len(mock_arq_pool.enqueued) == 1
    name, args, _ = mock_arq_pool.enqueued[0]
    assert name == "parse_job"
    assert args[0] == upload_id


def test_create_upload_503_when_arq_down_and_no_fallback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Arq pool is None AND ``ALLOW_INREQUEST_PARSE_FALLBACK`` is unset, POST returns 503.

    Production safety: a misconfigured Redis broker must NOT
    silently degrade to in-request parsing (the pre-v0.10.1
    behavior). The 503 surfaces the misconfiguration to the
    operator (HTTP 5xx in dashboards + log search) instead of
    hiding it behind a slow response.

    Pins the contract so a future refactor that drops the
    env-var check silently regresses to the silent-degradation
    behavior.
    """
    monkeypatch.delenv("ALLOW_INREQUEST_PARSE_FALLBACK", raising=False)
    blob = make_minimal_zevtc(
        agents=[(100_005, 2, 18, "V10 Warrior 503", True)],
        build="20251019",
    )
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("503_sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert "Parser worker unavailable" in str(body.get("detail", ""))


@pytest.mark.parametrize("status", ["pending", "completed"])
def test_re_upload_does_not_redispatch_when_not_failed(
    client: TestClient,
    mock_arq_pool: _MockArqPool,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    """Re-POST of a SHA matching an existing non-failed upload does NOT enqueue.

    The idempotent path in the route handler is:
    - ``Upload.status == "failed"`` -> re-enqueue (re-parse).
    - ``Upload.status == "pending"`` (the immediate-post state,
      before the first parse has run) or ``"completed"`` (after
      the chained parse+dispatch has finished) -> return existing
      record WITHOUT enqueuing.

    Re-enqueuing in the ``"pending"`` case would race the
    in-flight Arq worker (two parses on the same SHA), and
    re-enqueuing in the ``"completed"`` case would silently
    double-deliver the webhook to every active subscriber
    (the original dispatch already fired inside the chained
    ``parse_job``).

    Pins the contract so a future refactor that drops the
    status check surfaces as a failed test (and not as a
    silent race or double-delivery in production).
    """
    # v0.10.2 hotfix followup #11: see test_create_upload_enqueues_via_arq.
    monkeypatch.delenv("ALLOW_INREQUEST_PARSE_FALLBACK", raising=False)
    blob = make_minimal_zevtc(
        agents=[(100_004, 2, 18, "V10 Warrior REDISPATCH", True)],
        build="20251018",
    )
    # First POST: enqueues the parse (mock does not run it).
    resp1 = client.post(
        "/api/v1/uploads",
        files={"file": ("redisp_sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp1.status_code == 201, resp1.text
    upload_id = resp1.json()["id"]
    assert len(mock_arq_pool.enqueued) == 1
    # Flip the row to the parametrised status (NOT "failed").
    # The chained dispatch has already fired (in the real Arq
    # worker) for the "completed" case; for the "pending"
    # case the first parse is in-flight. Either way, a
    # re-POST must NOT re-enqueue.
    with get_sessionmaker()() as db:
        upload = db.get(Upload, _uuid.UUID(upload_id))
        assert upload is not None
        upload.status = status
        db.commit()
    mock_arq_pool.enqueued.clear()
    # Second POST with the same SHA: idempotent path,
    # should NOT re-enqueue (status != "failed").
    resp2 = client.post(
        "/api/v1/uploads",
        files={"file": ("redisp_sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp2.status_code == 201, resp2.text
    assert resp2.json()["id"] == upload_id
    assert mock_arq_pool.enqueued == []  # no double-dispatch


def test_create_upload_inline_fallback_when_pool_reachable_and_env_set(
    client: TestClient,
    mock_arq_pool: _MockArqPool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v0.10.2 hotfix followup #11: the dev workflow has Redis up
    (docker-compose) but no arq worker. The operator opts in to the
    inline fallback via ``ALLOW_INREQUEST_PARSE_FALLBACK=1`` so the
    route bypasses the arq pool entirely and parses in-request.

    Before the fix: pool is reachable + no env opt-in -> the route
    enqueued the job to Redis, no worker consumed it, and the
    upload sat in ``status='pending'`` forever (the UI's
    ``attempt 7/15`` counter was just frontend polling, not real
    arq retries). The dev experience was broken.

    After the fix: pool is reachable + env opt-in -> the route
    short-circuits the enqueue and runs the parse + dispatch in a
    thread, the upload flips to ``completed`` within milliseconds.
    Production behavior (env unset) is unchanged: pool is reachable
    -> enqueue, pool is None -> 503 (the existing loud-signal path).
    """
    monkeypatch.setenv("ALLOW_INREQUEST_PARSE_FALLBACK", "1")
    blob = make_minimal_zevtc(
        agents=[(100_006, 2, 18, "V10 Warrior POOL_REACHABLE", True)],
        build="20251020",
    )
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("pool_reachable.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]
    # Pool was reachable but the operator opted in: no enqueue.
    assert mock_arq_pool.enqueued == []
    # Parse ran inline (status flips to completed within 5s).
    for _ in range(50):
        upload = client.get(f"/api/v1/uploads/{upload_id}").json()
        if upload["status"] == "completed":
            assert upload["fight_id"] is not None
            return
        if upload["status"] == "failed":
            pytest.fail(f"upload {upload_id} failed: {upload.get('error_message')}")
        time.sleep(0.1)
    pytest.fail(f"upload {upload_id} did not reach 'completed' within 5s")
