"""Concurrent load-test baseline harness (v0.10.25 WAVE-8 SOAK foundation).

Pairs with :file:`test_load_baseline.py` (the sequential baseline).
The two-tier approach captures the canonical load envelope:

- ``test_load_baseline.py`` (sequential N=10): hermetic regression
  guard against a parse-pipeline slowdown.
- ``test_load_concurrent.py`` (concurrent N=WORKERS): guards
  against the in-request parse fallback bottleneck when multiple
  analysts hit the same ``POST /api/v1/uploads`` endpoint in
  parallel (the disclaimer on the WvW guild-leader realistic
  envelope cited in the sequential baseline docstring).

This file is the FOUNDATION scaffold; a future advisor-plan can
swap the in-process ThreadPoolExecutor for a real k6 / Locust
harness without re-architecting the assertions. The v0.10.25
budget keeps the in-process executor so a k6 dependency is NOT
added (k6 is not in the project's pyproject.toml and the dev
host lacks the binary per the prior audit).

Thread contention model
=======================
``TestClient`` (FastAPI) runs in-process. Each thread fires a
request through the same WSGI app; the FastAPI handler runs the
``_enqueue_parse`` path which (in tests with the conftest's
``ALLOW_INREQUEST_PARSE_FALLBACK=1`` env var) executes the
parse synchronously. We deliberately serialize the synthetic
SHA-256 ingestion (``uuid.uuid4().hex[:8]`` per task) so the
SELECT-before-INSERT idempotent path does NOT short-circuit
(an idempotent short-circuit would defeat the parse-path
coverage).

CLI (opt-in; skipped by default to keep CI fast)::

    RUN_LOAD_CONCURRENT=1 uv run pytest apps/api/tests/test_load_concurrent.py -v

The baseline asserts a wallclock budget so a parse-pipeline
regression that triples upload latency surfaces in CI rather
than silently shipping to production.
"""

from __future__ import annotations

import concurrent.futures
import os
import time
import uuid as _uuid

import pytest
from fastapi.testclient import TestClient
from tests._fixtures import make_minimal_zevtc

from apps.api.tests.routes._evtc_builder import build_2025_string
from gw2analytics_api.models import OrmFight, Upload

CONCURRENT_WORKERS = 10  # v0.10.25 starts at N=10; bumped at WAVE-8 SOAK.
# Wallclock cap for the whole concurrent run. Generous enough
# for a CI cold-start host (10 parallel parse round-trips with
# JSONL hydration + ORM commit per request); tight enough to
# surface a parse-pipeline regression in minutes rather than
# hours. Scales linearly with WORKERS: each thread's serial
# ``make_minimal_zevtc`` + POST + GET round-trip should average
# < 3 s on the canonical CI host.
WALLCLOCK_BUDGET_S = 30.0


def _worker_round_trip(
    client: TestClient,
    worker_index: int,
) -> tuple[str | None, int, int]:
    """One worker's upload+poll+get round-trip; returns (fight_id, post, get).

    Returns
    -------
    (fight_id, post_status, get_status) tuple. ``fight_id`` is
    ``None`` if the upload never reached "completed". The
    HTTP status codes are returned so the test driver can
    detect partial failures without exception-throwing (a
    partial failure surfaces silently via the assertions).
    """
    suffix = _uuid.uuid4().hex[:8]
    aid = 300_000 + worker_index
    sk = 4_000_000 + worker_index
    blob = make_minimal_zevtc(
        [(aid, 2, 18, f"W {suffix}", True)],
        build=build_2025_string(suffix),
        skills=[(sk, f"Dmg {suffix}")],
        events=[],
    )

    post = client.post(
        "/api/v1/uploads",
        files={
            "file": (f"concurrent-{worker_index}-{suffix}.zevtc", blob, "application/octet-stream")
        },
    )
    if post.status_code != 201:
        return (None, post.status_code, 0)

    upload_id = post.json()["id"]
    fight_id: str | None = None
    last_status: str | None = None
    # In tests the in-request parse fallback (conftest routes
    # ALLOW_INREQUEST_PARSE_FALLBACK=1) commits the row inside
    # the POST handler, so the first GET returns "completed"
    # on this iteration. The 100-attempt ceiling is a safety
    # net for slower hosts.
    for _ in range(100):
        poll = client.get(f"/api/v1/uploads/{upload_id}")
        if poll.status_code != 200:
            return (None, post.status_code, poll.status_code)
        last_status = poll.json()["status"]
        if last_status == "completed":
            fight_id = poll.json()["fight_id"]
            break
    if fight_id is None:
        return (None, post.status_code, poll.status_code)

    get = client.get(f"/api/v1/fights/{fight_id}")
    return (fight_id, post.status_code, get.status_code)


@pytest.mark.skipif(
    os.getenv("RUN_LOAD_CONCURRENT") is None,
    reason=(
        "Concurrent load baseline is opt-in. Set "
        "RUN_LOAD_CONCURRENT=1 to enable (N=10 workers "
        "running parallel POST/GET round-trips; CI wallclock "
        "budget 30 s)."
    ),
)
def test_load_concurrent_workers_upload_and_get(
    client: TestClient,
) -> None:
    """N CONCURRENT workers complete upload+parse+get without race / drop.

    ThreadPoolExecutor with max_workers=CONCURRENT_WORKERS fans out
    N parallel round-trips. Each worker uses a fresh
    ``uuid.uuid4().hex[:8]`` suffix so the synthetic SHA-256
    ingestion is unique (parsing-path coverage is preserved; the
    SELECT-before-INSERT idempotent path does NOT short-circuit).

    Assertions:
      - All N workers return HTTP 201 (POST) + HTTP 200 (GET).
      - All N fight_ids are distinct (no SHA-256 collision
        on the uuids + no DB-level primary-key skip).
      - The final OrmFight row count is exactly N (silent-drop
        regression guard).
      - Overall wallclock < WALLCLOCK_BUDGET_S (a parse-pipeline
        slowdown is flagged in CI rather than tripling upload
        latency in production).
    """
    start_ts = time.monotonic()
    fight_ids: list[str] = []
    statuses: list[tuple[int, int]] = []

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=CONCURRENT_WORKERS,
    ) as pool:
        futures = [
            pool.submit(_worker_round_trip, client, idx) for idx in range(CONCURRENT_WORKERS)
        ]
        for future in concurrent.futures.as_completed(futures):
            fight_id, post_status, get_status = future.result()
            statuses.append((post_status, get_status))
            if fight_id is not None:
                fight_ids.append(fight_id)

    # All workers returned 201 + 200.
    for idx, (post, get) in enumerate(statuses):
        assert post == 201, f"worker {idx}: POST status={post} (race-induced failure?)"
        assert get == 200, f"worker {idx}: GET status={get} (race-induced failure?)"

    # All fight_ids are distinct (no UUID collision; no DB PK skip).
    assert len(set(fight_ids)) == CONCURRENT_WORKERS, (
        f"distinct fight_ids={len(set(fight_ids))} < "
        f"workers={CONCURRENT_WORKERS} (collision regression?)"
    )

    # DB consistency: N OrmFight rows + N Upload rows.
    from sqlalchemy import select

    from gw2analytics_api.database import (
        get_sessionmaker,
    )

    with get_sessionmaker()() as db:
        fights = (
            db.execute(
                select(OrmFight).where(OrmFight.id.in_(fight_ids)),
            )
            .scalars()
            .all()
        )
        assert len(fights) == CONCURRENT_WORKERS, (
            f"expected {CONCURRENT_WORKERS} OrmFight rows, "
            f"got {len(fights)} (silent-drop regression?)"
        )
        uploads = (
            db.execute(
                select(Upload).where(
                    Upload.fight.has(OrmFight.id.in_(fight_ids)),
                ),
            )
            .scalars()
            .all()
        )
        assert len(uploads) == CONCURRENT_WORKERS, (
            f"expected {CONCURRENT_WORKERS} Upload rows, "
            f"got {len(uploads)} (silent-drop regression?)"
        )

    # Wallclock ceiling: parse-pipeline slowdown gate.
    overall_elapsed = time.monotonic() - start_ts
    assert overall_elapsed < WALLCLOCK_BUDGET_S, (
        f"baseline exceeded wallclock budget: {overall_elapsed:.2f}s "
        f">= {WALLCLOCK_BUDGET_S:.2f}s (parse-pipeline slowdown?)"
    )
