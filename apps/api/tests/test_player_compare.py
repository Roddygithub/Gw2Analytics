"""Contract tests for v0.10.0 plan 032 ``GET /api/v1/players/compare/timeline``.

Eight contract branches locked down (see advisor-plans/001).
"""

from __future__ import annotations

import time
import uuid as _uuid

import pytest
from _fixtures import make_cbtevent, make_minimal_zevtc
from fastapi.testclient import TestClient

# v0.10.8 plan 140 Fix-C: replace the prior ``client = TestClient(app)``
# (which fired the app lifespan AT IMPORT TIME -- before pytest autouse
# fixtures like ``_disable_arq_for_tests`` could monkeypatch
# ``arq.create_pool``) with a per-test binding.
client: TestClient | None = None


@pytest.fixture(autouse=True)
def _bind_client(request: pytest.FixtureRequest) -> None:
    """Bind the module-level ``client`` to the per-test conftest fixture.

    Avoids rewriting every test in this file to take ``client`` as a
    parameter; the global ``client`` name is rebound per-test to the
    conftest's per-test TestClient (which uses the ``with TestClient(app)
    as c:`` context manager for proper lifespan entry/exit).
    """
    global client  # noqa: PLW0603
    client = request.getfixturevalue("client")


def _post_compare_fight(n_players: int, suffix: str | None = None) -> tuple[str, list[str]]:
    assert client is not None  # mypy: narrow TestClient | None → TestClient
    suffix = suffix or _uuid.uuid4().hex[:8]
    base_id = 2_000_000_000 + int(suffix, 16)
    base_skill = 2_000_000 + int(suffix[:4], 16) if len(suffix) >= 4 else 2_000_000
    agents = [(base_id + i, 2, 5, f"V0100 P{i} {suffix}", True) for i in range(n_players)]
    events = []
    for i in range(n_players):
        events.append(
            make_cbtevent(
                time_ms=1_500,
                src=base_id + i,
                dst=base_id + ((i + 1) % n_players),
                value=1_000,
                skill_id=base_skill,
            )
        )
    blob = make_minimal_zevtc(
        agents,
        build="20250925",
        skills=[(base_skill, f"V0100 Skill {suffix}")],
        events=events,
    )
    resp = client.post(
        "/api/v1/uploads", files={"file": ("sample.zevtc", blob, "application/octet-stream")}
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]
    for _ in range(50):
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        if upload_resp.status_code == 200 and upload_resp.json()["status"] == "completed":
            time.sleep(0.1)
            fight_id = str(upload_resp.json()["fight_id"])
            account_names = [f"synth.{base_id + i}" for i in range(n_players)]
            return fight_id, account_names
        time.sleep(0.1)
    raise AssertionError(f"upload {upload_id} did not complete in 5s")


def test_compare_2_accounts_recency_first() -> None:
    assert client is not None  # mypy: narrow TestClient | None → TestClient
    suffix = _uuid.uuid4().hex[:8]
    _, account_names = _post_compare_fight(n_players=2, suffix=suffix)
    resp = client.get(
        "/api/v1/players/compare/timeline",
        params=[("accounts", account_names[0]), ("accounts", account_names[1])],
    )
    assert resp.status_code == 200, resp.text
    series = resp.json()
    assert len(series) == 2
    accounts_in_response = {s["account_name"] for s in series}
    assert accounts_in_response == set(account_names)


def test_compare_3_accounts_max_inclusive() -> None:
    assert client is not None  # mypy: narrow TestClient | None → TestClient
    suffix = _uuid.uuid4().hex[:8]
    _, account_names = _post_compare_fight(n_players=3, suffix=suffix)
    resp = client.get(
        "/api/v1/players/compare/timeline", params=[("accounts", a) for a in account_names]
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 3


def test_compare_4_accounts_at_max_boundary() -> None:
    assert client is not None  # mypy: narrow TestClient | None → TestClient
    suffix = _uuid.uuid4().hex[:8]
    _, account_names = _post_compare_fight(n_players=4, suffix=suffix)
    resp = client.get(
        "/api/v1/players/compare/timeline", params=[("accounts", a) for a in account_names]
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 4


def test_compare_1_account_returns_422() -> None:
    assert client is not None  # mypy: narrow TestClient | None → TestClient
    suffix = _uuid.uuid4().hex[:8]
    _, account_names = _post_compare_fight(n_players=2, suffix=suffix)
    resp = client.get("/api/v1/players/compare/timeline", params=[("accounts", account_names[0])])
    assert resp.status_code == 422, resp.text


def test_compare_5_accounts_returns_422() -> None:
    assert client is not None  # mypy: narrow TestClient | None → TestClient
    suffix = _uuid.uuid4().hex[:8]
    _, account_names = _post_compare_fight(n_players=5, suffix=suffix)
    resp = client.get(
        "/api/v1/players/compare/timeline", params=[("accounts", a) for a in account_names]
    )
    assert resp.status_code == 422, resp.text


def test_compare_day_bucket_collapses_per_day() -> None:
    assert client is not None  # mypy: narrow TestClient | None → TestClient
    suffix = _uuid.uuid4().hex[:8]
    _, account_names = _post_compare_fight(n_players=2, suffix=suffix)
    resp = client.get(
        "/api/v1/players/compare/timeline",
        params=[
            ("accounts", account_names[0]),
            ("accounts", account_names[1]),
            ("bucket", "day"),
            ("tz", "UTC"),
        ],
    )
    assert resp.status_code == 200, resp.text
    series = resp.json()
    assert len(series) == 2
    for s in series:
        assert len(s["points"]) == 1
        # The day-bucketed point's ``started_at`` is the day-midnight
        # in the requested TZ, serialised as UTC (the ``Z`` suffix
        # on the wire -- see ``_combine_day_midnight`` in
        # ``routes/players.py`` for the conversion details).
        assert s["points"][0]["started_at"].endswith("T00:00:00Z")


def test_compare_unknown_tz_returns_422() -> None:
    assert client is not None  # mypy: narrow TestClient | None → TestClient
    suffix = _uuid.uuid4().hex[:8]
    _, account_names = _post_compare_fight(n_players=2, suffix=suffix)
    resp = client.get(
        "/api/v1/players/compare/timeline",
        params=[
            ("accounts", account_names[0]),
            ("accounts", account_names[1]),
            ("tz", "Mars/Olympus"),
        ],
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert "Mars/Olympus" in str(body.get("detail", ""))


def test_compare_unknown_account_returns_empty_points_series() -> None:
    assert client is not None  # mypy: narrow TestClient | None → TestClient
    suffix = _uuid.uuid4().hex[:8]
    _, account_names = _post_compare_fight(n_players=1, suffix=suffix)
    known = account_names[0]
    unknown = f"synth.{_uuid.uuid4().hex}"
    resp = client.get(
        "/api/v1/players/compare/timeline", params=[("accounts", known), ("accounts", unknown)]
    )
    assert resp.status_code == 200, resp.text
    series = resp.json()
    assert len(series) == 2
    unknown_series = next(s for s in series if s["account_name"] == unknown)
    assert unknown_series["points"] == []


def test_compare_accepts_colon_prefixed_account_names() -> None:
    """Colon-prefixed account names are accepted and normalised to bare form.

    Regression guard for the account_name colon-prefix normalisation:
    clients that still send the legacy ``:synth.<id>`` form (or any
    other account name with a leading colon) must get the same
    response as the bare form, with the response echoing the bare
    account_name.
    """
    assert client is not None  # mypy: narrow TestClient | None → TestClient
    suffix = _uuid.uuid4().hex[:8]
    _, account_names = _post_compare_fight(n_players=2, suffix=suffix)
    colon_prefixed = [f":{name}" for name in account_names]
    resp = client.get(
        "/api/v1/players/compare/timeline",
        params=[("accounts", a) for a in colon_prefixed],
    )
    assert resp.status_code == 200, resp.text
    series = resp.json()
    assert len(series) == 2
    accounts_in_response = {s["account_name"] for s in series}
    assert accounts_in_response == set(account_names)
    for s in series:
        assert not s["account_name"].startswith(":")
