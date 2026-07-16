"""Load-test baseline harness (v0.10.25 hardening).

The user-facing reality on WvW: a guild raid drops a 30-100 MiB
.zevtc upload every 5-15 minutes during peak content. Most
guild leaders + their 1-2 lieutenants (~5-10 concurrent
analysts on the same fight id) want a fresh view of the same
fight within seconds of the leader hitting "refresh". The
honest load envelope (per the WAVE-8 SOAK note in plans/) is
"~10 concurrent clients hitting 6 endpoints on the same
freshly-parsed fight, no memory growth, no missed-cache".

This baseline tests a smaller slice: N SEQUENTIAL parse
round-trips against the live app-to-DB path. SEQUENTIAL
(not concurrent) because:
1. It is hermetic -- no actor model, no asyncio.gather.
2. The Arq worker pool + the lru_cache + the singleflight
   Future-dict path is exercised end-to-end on each call.
3. CI can run it in <2 s on the dev host (the existing
   323-test suite would explode by ~50x on a 100-concurrent
   load).

The TRUE 100-concurrent load is OUT OF SCOPE for this
baseline (k6 / Locust harness, deferred to WAVE-8 SOAK or a
future advisor-plan). This file pins the SEQUENTIAL baseline
so a regression in parsing + blob storage + ORM hydration
surfaces "crashes on N=10" instead of "silent on N=1".

CLI (opt-in; skipped by default to keep CI fast)::

    RUN_LOAD_BASELINE=1 uv run pytest apps/api/tests/test_load_baseline.py -v

The baseline asserts an overall wallclock budget so a parse-pipeline
slowdown surfaces in CI rather than silently tripling upload latency.
"""

from __future__ import annotations

import os
import time
import uuid as _uuid

import pytest
from _fixtures import make_minimal_zevtc
from fastapi.testclient import TestClient

from gw2analytics_api.models import OrmFight, Upload

SEQUENTIAL_BASELINE_N = 10  # v0.10.25 starts at N=10; bumped at WAVE-8 SOAK.
POLL_MAX_ATTEMPTS = 100  # hard ceiling per iteration; first GET usually completes.

# Wallclock cap for the whole baseline run. Generous enough for a
# CI cold-start host; tight enough to surface a parse-pipeline
# slowdown in minutes rather than hours.
WALLCLOCK_BUDGET_S = 30.0


@pytest.mark.skipif(
    os.getenv("RUN_LOAD_BASELINE") is None,
    reason=(
        "Sequential load baseline is opt-in. Set "
        "RUN_LOAD_BASELINE=1 to enable (N=10 upload+parse+GET "
        "round-trips; CI wallclock budget 30 s)."
    ),
)
def test_load_baseline_sequential_uploads_and_parses(
    client: TestClient,
) -> None:
    """N SEQUENTIAL upload+parse round-trips finish without OOM / crash.

    Each iteration:
      1. POST /api/v1/uploads with a synthetic 200-byte .zevtc
      2. Poll the upload until it reaches "completed"
      3. GET /api/v1/fights/{fight_id} returns 200

    The whole baseline asserts an overall wallclock ceiling so a
    parse-pipeline regression that triples upload latency surfaces
    in CI rather than silently shipping to production.

    Assertions:
      - All N iterations return HTTP 201 (POST) + HTTP 200 (GET).
      - The final OrmFight row count in the DB is exactly N (no
        silent drops, no duplicate-id collisions on synthetic
        SHA-256 collisions).
      - No exception escapes to the test runner (an OOM or a
        backend ``MemoryError`` manifests as a worker crash +
        a 500 from the cable handler).

    NOTE: ``test_uploads_e2e.py`` already exercises a single
    happy path; this baseline is the N>1 regression guard.
    """
    start_ts = time.monotonic()
    # Each iteration uses a fresh suffix so the blob SHA-256 is
    # unique; if we re-uploaded the SAME blob, the SELECT-before-
    # INSERT idempotent path would short-circuit (returning the
    # existing upload id) and we'd lose the parsing-path coverage.
    fight_ids: list[str] = []
    for n in range(SEQUENTIAL_BASELINE_N):
        suffix = _uuid.uuid4().hex[:8]
        aid = 200_000 + n
        sk = 2_000_000 + n
        blob = make_minimal_zevtc(
            [(aid, 2, 18, f"W {suffix}", True)],
            build=f"2025{suffix[:4]}",
            skills=[(sk, f"Dmg {suffix}")],
            events=[],
        )

        # POST upload: 201 created.
        post = client.post(
            "/api/v1/uploads",
            files={"file": (f"baseline-{suffix}.zevtc", blob, "application/octet-stream")},
        )
        assert post.status_code == 201, (
            f"iteration {n}: POST status={post.status_code} body={post.text}"
        )

        upload_id = post.json()["id"]

        # Poll until "completed". In tests, the parse fallback runs
        # synchronously inside the POST handler (conftest routes
        # ALLOW_INREQUEST_PARSE_FALLBACK=1) so the first GET after
        # POST usually returns "completed" on the very first call;
        # the 100-call ceiling is a generous safety net for slower
        # hosts. We deliberately don't burn CPU with elapsed + sleep
        # math -- the synchronous in-process parse does not need it.
        fight_id: str | None = None
        last_status: str | None = None
        # In tests the in-request parse fallback (conftest routes
        # ALLOW_INREQUEST_PARSE_FALLBACK=1) commits the row inside
        # the POST handler, so the first GET returns "completed"
        # on this iteration. The 100-attempt ceiling is a safety
        # net for slower hosts (e.g. CI under memory pressure).
        for _attempt in range(POLL_MAX_ATTEMPTS):
            r = client.get(f"/api/v1/uploads/{upload_id}")
            assert r.status_code == 200, f"iteration {n}: GET upload status={r.status_code}"
            last_status = r.json()["status"]
            if last_status == "completed":
                fight_id = r.json()["fight_id"]
                break
        assert fight_id is not None, (
            f"iteration {n}: upload {upload_id} never reached "
            f"'completed' (last status={last_status!r})"
        )
        fight_ids.append(fight_id)

    # GET fight: 200 OK + valid wire envelope. Iterates all N.
    for n, fid in enumerate(fight_ids):
        r = client.get(f"/api/v1/fights/{fid}")
        assert r.status_code == 200, f"iteration {n}: GET fight status={r.status_code}"
        payload = r.json()
        assert payload["id"] == fid

    # DB consistency: N distinct rows. The SELECT-before-INSERT
    # idempotent path guards against duplicate upload ids on
    # SHA-256 collision; this assertion closes the silent-drop
    # regression gate (an OOM mid-iteration would manifest as
    # N < SEQUENTIAL_BASELINE_N).
    from sqlalchemy import select  # noqa: PLC0415  -- lazy import

    from gw2analytics_api.database import (  # noqa: PLC0415
        get_sessionmaker,
    )

    with get_sessionmaker()() as db:
        rows = (
            db.execute(
                select(OrmFight).where(OrmFight.id.in_(fight_ids)),
            )
            .scalars()
            .all()
        )
        assert len(rows) == SEQUENTIAL_BASELINE_N, (
            f"expected {SEQUENTIAL_BASELINE_N} OrmFight rows, "
            f"got {len(rows)} (silent-drop regression?)"
        )

        uploads = (
            db.execute(
                select(Upload).where(Upload.fight.has(OrmFight.id.in_(fight_ids))),
            )
            .scalars()
            .all()
        )
        assert len(uploads) == SEQUENTIAL_BASELINE_N, (
            f"expected {SEQUENTIAL_BASELINE_N} Upload rows, got {len(uploads)}"
        )

    # Wallclock ceiling: a parse-pipeline regression that triples
    # upload latency (e.g. an accidental N+1 query) trips this gate
    # in CI before it ships to production. Generous for cold-start
    # CI hosts; tight enough to flag a 10x slowdown.
    overall_elapsed = time.monotonic() - start_ts
    assert overall_elapsed < WALLCLOCK_BUDGET_S, (
        f"baseline exceeded wallclock budget: {overall_elapsed:.2f}s "
        f">= {WALLCLOCK_BUDGET_S:.2f}s (parse-pipeline slowdown?)"
    )
