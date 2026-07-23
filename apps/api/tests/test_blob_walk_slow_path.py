"""Tests for the slow-path blob walk fallback (``_contributions_from_blob_walk``).

When ``OrmFightPlayerSummary`` rows exist for a fight, the player routes use
the **fast-path** (SQL query on the pre-materialised summary rows). When the
summary rows are missing (pre-v0.8.4 fights, or fights whose re-parse has not
yet landed), the routes fall back to the **slow-path**: decompress the events
blob from MinIO and walk the event stream to accumulate per-account totals.

These tests exercise the slow-path by:

1. Posting a fight via the normal upload path (which creates summary + events blob).
2. Deleting the ``OrmFightPlayerSummary`` rows so the route's
   ``find_account_fights_without_summary`` returns the fight id.
3. Querying the player routes — they now fall back to the slow-path blob walk.
4. Verifying the output matches the fast-path output identically.

Design
------
Hermetic by construction: each test creates its own fight via
:func:`_fixtures.post_minimal_fight` (unique uuid suffix), and the conftest's
``_isolate_test_state`` autouse fixture bulk-deletes all state tables before
every test. The ``_mock_s3`` autouse fixture provides a fresh
:class:`FakeMinio` per test that carries the events blob written by the
parser during the POST.

Because the conftest's ``_clear_blob_caches`` autouse fixture clears the
in-memory blob cache before each test, a stale cache entry from a previous
test cannot affect the slow-path blob read.
"""

from __future__ import annotations

import uuid as _uuid
from urllib.parse import quote

from _fixtures import build_2025_string, make_cbtevent, make_minimal_zevtc
from fastapi.testclient import TestClient
from sqlalchemy import delete
from test_uploads_helpers import _post_minimal_fight as post_minimal_fight
from test_uploads_helpers import _wait_for_upload_completion as wait_for_upload_completion

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.main import app
from gw2analytics_api.models import OrmFightPlayerSummary

client = TestClient(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _delete_summaries(fight_id: str) -> None:
    """Delete all OrmFightPlayerSummary rows for a fight (force slow-path)."""
    session = get_sessionmaker()()
    try:
        session.execute(
            delete(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id)
        )
        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_slow_path_detail_after_summary_deleted() -> None:
    """After deleting the OrmFightPlayerSummary rows, the player detail
    route serves the same data via the slow-path blob walk.

    Exercise::
        1. POST a fight with 2 damage events (A→B).
        2. Query the player detail via fast-path → capture baseline.
        3. DELETE the summary rows → the route now uses the slow-path.
        4. Re-query the player detail → the response is byte-identical on
           all wire fields.
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)

    events = [
        make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
        make_cbtevent(
            time_ms=2_500,
            src=base_id_a,
            dst=base_id_b,
            value=567,
            skill_id=base_skill_a,
        ),
    ]
    fight_id = post_minimal_fight(events, suffix=suffix)
    account_name = f"synth.{base_id_a}"

    # 1. Fast-path baseline.
    fast_resp = client.get(f"/api/v1/players/{account_name}")
    assert fast_resp.status_code == 200, fast_resp.text
    fast_data = fast_resp.json()

    # 2. Delete summary rows → force slow-path.
    _delete_summaries(fight_id)

    # 3. Re-query via slow-path.
    slow_resp = client.get(f"/api/v1/players/{account_name}")
    assert slow_resp.status_code == 200, slow_resp.text
    slow_data = slow_resp.json()

    # 4. Assertions: all wire fields must match.
    assert slow_data["account_name"] == fast_data["account_name"]
    assert slow_data["fights_attended"] == fast_data["fights_attended"]
    assert slow_data["total_damage"] == fast_data["total_damage"]
    assert slow_data["total_healing"] == fast_data["total_healing"]
    assert slow_data["total_buff_removal"] == fast_data["total_buff_removal"]
    assert slow_data["profession"] == fast_data["profession"]
    assert slow_data["elite_spec"] == fast_data["elite_spec"]
    assert slow_data["name"] == fast_data["name"]
    # Per-fight breakdown: same number of rows, same values.
    assert len(slow_data["per_fight_breakdown"]) == len(fast_data["per_fight_breakdown"])
    for slow_row, fast_row in zip(
        slow_data["per_fight_breakdown"], fast_data["per_fight_breakdown"], strict=True
    ):
        assert slow_row["fight_id"] == fast_row["fight_id"]
        assert slow_row["total_damage"] == fast_row["total_damage"]
        assert slow_row["total_healing"] == fast_row["total_healing"]
        assert slow_row["total_buff_removal"] == fast_row["total_buff_removal"]


def test_slow_path_timeline_after_summary_deleted() -> None:
    """The timeline route also falls back to slow-path when summaries are deleted.

    Seeds 2 fights for the same account to verify the merged sort order
    (recency-first) is preserved across the SQL + slow-path boundary.
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)

    # Fight 1 (earlier time → older started_at).
    events_1 = [
        make_cbtevent(
            time_ms=1_000,
            src=base_id_a,
            dst=base_id_b,
            value=1_000,
            skill_id=base_skill_a,
        ),
    ]
    fight_id_1 = post_minimal_fight(events_1, suffix=suffix)

    # Fight 2 (later time → more recent started_at). Inline POST so it
    # shares the same agent IDs and therefore the same account_name.
    events_2 = [
        make_cbtevent(
            time_ms=2_000,
            src=base_id_a,
            dst=base_id_b,
            value=2_000,
            skill_id=base_skill_a,
        ),
    ]
    blob_2 = make_minimal_zevtc(
        [
            (base_id_a, 2, 18, f"V07 Warrior {suffix}", True),
            (base_id_b, 1, 27, f"V07 Guard {suffix}", True),
        ],
        build=build_2025_string(suffix),
        skills=[
            (base_skill_a, f"Whirlwind {suffix}"),
        ],
        events=events_2,
    )
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob_2, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    fight_id_2 = wait_for_upload_completion(resp.json()["id"])
    assert fight_id_1 != fight_id_2

    account_name = f"synth.{base_id_a}"
    encoded = quote(account_name, safe="")

    # 1. Fast-path baseline.
    fast_resp = client.get(f"/api/v1/players/{encoded}/timeline")
    assert fast_resp.status_code == 200, fast_resp.text
    fast_data = fast_resp.json()

    # 2. Delete summaries for BOTH fights → force slow-path.
    _delete_summaries(fight_id_1)
    _delete_summaries(fight_id_2)

    # 3. Re-query via slow-path.
    slow_resp = client.get(f"/api/v1/players/{encoded}/timeline")
    assert slow_resp.status_code == 200, slow_resp.text
    slow_data = slow_resp.json()

    # 4. Assertions.
    assert slow_data["account_name"] == fast_data["account_name"]
    assert slow_data["total"] == fast_data["total"]
    assert len(slow_data["points"]) == len(fast_data["points"])
    # Recency-first: first point is the most recent fight (fight_id_2).
    assert slow_data["points"][0]["fight_id"] == fight_id_2
    assert slow_data["points"][0]["total_damage"] == 2_000
    # Second point is the older fight (fight_id_1).
    assert slow_data["points"][1]["fight_id"] == fight_id_1
    assert slow_data["points"][1]["total_damage"] == 1_000
    # Per-point totals match fast-path.
    for slow_point, fast_point in zip(slow_data["points"], fast_data["points"], strict=True):
        assert slow_point["total_damage"] == fast_point["total_damage"]
        assert slow_point["total_healing"] == fast_point["total_healing"]
        assert slow_point["total_buff_removal"] == fast_point["total_buff_removal"]


def test_slow_path_404_when_account_unknown() -> None:
    """The slow-path preserves the same 404 contract: an unknown account
    returns 404 regardless of which path the route uses."""
    resp = client.get("/api/v1/players/does-not-exist-slowpath-1234")
    assert resp.status_code == 404
