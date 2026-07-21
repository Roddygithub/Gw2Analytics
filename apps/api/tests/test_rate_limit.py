"""v0.13.4: rate limiting tests (slowapi).

Verifies that the POST /api/v1/uploads endpoint enforces the
5/minute rate limit configured in the @limiter.limit decorator.
"""

from __future__ import annotations

import uuid as _uuid

from fastapi.testclient import TestClient

from gw2analytics_api.limiter import limiter
from gw2analytics_api.main import app

client: TestClient = TestClient(app)


def _upload(blob: bytes) -> int:
    """Upload a single .zevtc blob and return the HTTP status code."""
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("t.zevtc", blob, "application/octet-stream")},
    )
    return resp.status_code


def test_upload_rate_limit_returns_429_after_5_per_minute() -> None:
    """Six rapid uploads: first 5 accepted (201), 6th rate-limited (429).

    Each upload uses a unique agent ID so the idempotency path
    (SHA-256 dedup) treats them as distinct files. The rate limiter
    counts HTTP requests independently of the dedup logic.
    """
    from _fixtures import make_minimal_zevtc

    build = "20240925"  # legacy format for minimal fixture

    # Reset the limiter so prior test runs don't affect this one.
    limiter.reset()

    # First 5 uploads: should all be accepted (201 Created).
    # Vary the agent ID per upload so each POST is a genuinely
    # new file (avoids testing through the idempotency path).
    for i in range(5):
        agent_id = 100001 + i
        suffix = _uuid.uuid4().hex[:8]
        blob = make_minimal_zevtc(
            agents=[(agent_id, 2, 18, f"RateLimit P{i} {suffix}", True)],
            build=build,
        )
        status = _upload(blob)
        assert status == 201, (
            f"upload {i + 1}/5 expected 201, got {status}. "
            f"The rate limiter may have accumulated state from a prior test."
        )

    # 6th upload: should be rate-limited (429 Too Many Requests).
    suffix6 = _uuid.uuid4().hex[:8]
    blob6 = make_minimal_zevtc(
        agents=[(100006, 2, 18, f"RateLimit P6 {suffix6}", True)],
        build=build,
    )
    status = _upload(blob6)
    assert status == 429, (
        f"6th upload expected 429 (rate limited), got {status}. "
        f"The @limiter.limit('5/minute') decorator may not be active."
    )


def test_rate_limit_resets_between_tests() -> None:
    """The limiter.reset() call isolates tests from each other.

    Exhausts the limit (5 uploads → 201, 6th → 429), resets,
    then verifies 5 more uploads succeed. This proves that
    limiter.reset() clears accumulated state, not just that
    the first upload after reset works.
    """
    from _fixtures import make_minimal_zevtc

    build = "20240925"

    # Phase 1: exhaust the rate limit.
    limiter.reset()
    for i in range(5):
        agent_id = 200001 + i
        suffix = _uuid.uuid4().hex[:8]
        blob = make_minimal_zevtc(
            agents=[(agent_id, 2, 18, f"RateLimit R{i} {suffix}", True)],
            build=build,
        )
        assert _upload(blob) == 201, f"Phase 1 upload {i + 1} failed"

    # Confirm the 6th is rate-limited.
    suffix6 = _uuid.uuid4().hex[:8]
    blob6 = make_minimal_zevtc(
        agents=[(200006, 2, 18, f"RateLimit R6 {suffix6}", True)],
        build=build,
    )
    assert _upload(blob6) == 429, "Phase 1: 6th upload should be rate-limited"

    # Phase 2: reset and verify 5 more pass.
    limiter.reset()
    for i in range(5):
        agent_id = 300001 + i
        suffix = _uuid.uuid4().hex[:8]
        blob = make_minimal_zevtc(
            agents=[(agent_id, 2, 18, f"RateLimit R{10 + i} {suffix}", True)],
            build=build,
        )
        assert _upload(blob) == 201, (
            f"Phase 2 upload {i + 1} after reset failed — "
            f"limiter.reset() did not clear accumulated state"
        )
