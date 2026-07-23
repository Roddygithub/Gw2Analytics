"""End-to-end tests for the v0.9.0 ``?profession=`` filter on ``GET /api/v1/players``."""

from __future__ import annotations

import time
import uuid as _uuid
from urllib.parse import quote

from _fixtures import _make_cbtevent, _make_minimal_zevtc
from fastapi.testclient import TestClient

from gw2analytics_api.main import app

client = TestClient(app)


def _post_minimal_fight_with_professions(
    professions: list[int],
    suffix: str | None = None,
) -> tuple[str, list[str]]:
    """POST a minimal fight with one player agent per ``professions[i]``.

    The helper threads a uuid suffix + the per-agent profession
    values through :func:`_make_minimal_zevtc` so the parser-assigned
    agent_ids in the per-fight agents table match the
    source_agent_id values in the cbtevent records. Without this
    match, the per-(fight, account) source-side attribution in
    :func:`apps.api.services._persist_player_summaries` silently
    drops the events (the per-source-side ``source_map`` lookup
    returns ``None`` for unmatched agent_ids), leaving the
    player with 0 contributions and 404ing downstream tests.

    The cbtevent records flow ``agent[0] -> agent[1]``,
    ``agent[1] -> agent[0]``, etc. (a single back-and-forth per
    pair) so every player has at least 1 contribution. The
    direction doesn't matter for the profession filter (the
    filter sees the modal profession, which is the seeded
    value since each player has exactly 1 profession).

    Returns ``(fight_id, account_names)`` where ``account_names``
    is the list of ``:synth.<base_id_a + i>`` strings in the
    same order as ``professions``. The unique ``base_id_a``
    (derived from the uuid suffix) lets the tests filter the
    cross-fight response by the ``:synth.<base_id_a>`` prefix
    to count only the test's seeded players.
    """

    suffix = suffix or _uuid.uuid4().hex[:8]
    # Legacy (pre-2025) build: the local _make_minimal_zevtc helper
    # uses the legacy EVTC wire format (uint64 agent_id, variable
    # skill records, legacy event struct).  A 2025+ build string would
    # make the parser use the EVTC2025+ layout, causing a layout
    # mismatch and garbage reads.
    build = "20240925"
    # Large ``base_id_a`` range to avoid collisions with prior
    # test runs' account_names (1_000_000_000..1_429_496_729 for
    # a full 8-char hex suffix). The agent_id field is uint64
    # in the EVTC pack format, so this is well within range.
    base_id_a = 1_000_000_000 + int(suffix, 16)
    base_skill = 1_000_000 + int(suffix[:4], 16) if len(suffix) >= 4 else 1_000_000
    agents: list[tuple[int, int, int, str, bool]] = []
    events: list[bytes] = []
    for i, prof in enumerate(professions):
        aid = base_id_a + i
        agents.append(
            (aid, prof, 0, f"V09 Player {suffix} {i}", True),
        )
    # Back-and-forth cbtevent stream so every agent has at
    # least 1 contribution. The exact direction doesn't
    # matter for the profession filter.
    # Events MUST be in non-decreasing time_ms order so the
    # parser's ``_validate_event_candidate`` monotonicity check
    # passes (backwards timestamps cause the parser to fall back
    # to EVTC2025+ detection, misreading events as skills).
    # Emit all forward events first, then all reverse events.
    for i in range(len(professions) - 1):
        events.append(
            _make_cbtevent(
                time_ms=1_500 + i * 1_000,
                src=base_id_a + i,
                dst=base_id_a + i + 1,
                value=1_000,
                skill_id=base_skill,
            ),
        )
    for i in range(len(professions) - 1):
        events.append(
            _make_cbtevent(
                time_ms=2_000 + i * 1_000,
                src=base_id_a + i + 1,
                dst=base_id_a + i,
                value=500,
                skill_id=base_skill,
            ),
        )
    blob = _make_minimal_zevtc(
        agents,
        build=build,
        skills=[(base_skill, f"V09 Skill {suffix}")],
        events=events,
    )
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]
    # Poll for completion (the parser runs in a BackgroundTask).
    for _ in range(50):
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        assert upload_resp.status_code == 200
        if upload_resp.json()["status"] == "completed":
            time.sleep(0.1)
            fight_id = str(upload_resp.json()["fight_id"])
            account_names = [f"synth.{base_id_a + i}" for i in range(len(professions))]
            return fight_id, account_names
        time.sleep(0.1)
    msg = f"upload {upload_id} did not reach 'completed' within 5s"
    raise AssertionError(msg)


def test_players_no_filter_returns_full_pool() -> None:
    """v0.9.0: GET /api/v1/players (no ``?profession=``) returns the full pool.

    Seeds 3 players with different professions (Mesmer / Warrior
    / Necromancer); the response contains all 3 seeded
    account_names regardless of profession. ``limit=500``
    ensures the seeded players (low damage, sorted to the
    bottom of the cross-fight roll-up) are NOT cut off by
    pagination.
    """
    suffix = _uuid.uuid4().hex[:8]
    _, account_names = _post_minimal_fight_with_professions(
        professions=[7, 2, 8],  # MESMER, WARRIOR, NECROMANCER
        suffix=suffix,
    )
    resp = client.get("/api/v1/players", params={"limit": 500})
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    response_accounts = {r["account_name"] for r in rows}
    # The 3 seeded account_names are all in the response
    # (subset check: the test pollutes the DB, so the
    # response contains more accounts than just the seeded
    # ones).
    seeded = set(account_names)
    assert seeded <= response_accounts, (
        f"expected seeded accounts {seeded} in response, missing: {seeded - response_accounts}"
    )


def test_players_filter_by_base_profession() -> None:
    """v0.9.0: ``?profession=MESMER`` returns only Mesmer players.

    Seeds 3 players with different professions; the
    Mesmer is in the response and the Warrior + Necromancer
    are NOT. Membership check (NOT count) so the test is
    robust against prior runs' Mesmer accounts in the DB.
    """
    suffix = _uuid.uuid4().hex[:8]
    _, account_names = _post_minimal_fight_with_professions(
        professions=[7, 2, 8],  # MESMER, WARRIOR, NECROMANCER
        suffix=suffix,
    )
    mesmer_account, warrior_account, necro_account = account_names
    resp = client.get(
        "/api/v1/players",
        params={"profession": "MESMER", "limit": 500},
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    response_accounts = {r["account_name"] for r in rows}
    # The Mesmer is in the response.
    assert mesmer_account in response_accounts, (
        f"Mesmer {mesmer_account} should be in response, got {response_accounts}"
    )
    # The Warrior + Necromancer are NOT in the response
    # (the filter excludes them).
    assert warrior_account not in response_accounts, (
        f"Warrior {warrior_account} should NOT be in response, got {response_accounts}"
    )
    assert necro_account not in response_accounts, (
        f"Necromancer {necro_account} should NOT be in response, got {response_accounts}"
    )


def test_players_filter_with_no_matches() -> None:
    """v0.9.0: ``?profession=RANGER`` returns no seeded players.

    Seeds 3 players (Mesmer / Warrior / Necromancer);
    filtering by RANGER excludes all 3 from the response.
    The route returns HTTP 200 (NOT 404 -- the route is
    "list", not "get one"). ``limit=500`` ensures the
    seeded players (low damage) are in the response when
    the filter is NOT applied.
    """
    suffix = _uuid.uuid4().hex[:8]
    _, account_names = _post_minimal_fight_with_professions(
        professions=[7, 2, 8],  # MESMER, WARRIOR, NECROMANCER
        suffix=suffix,
    )
    resp = client.get(
        "/api/v1/players",
        params={"profession": "RANGER", "limit": 500},
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    response_accounts = {r["account_name"] for r in rows}
    # The 3 seeded players are NOT in the response (RANGER
    # excludes Mesmer, Warrior, and Necromancer).
    for account in account_names:
        assert account not in response_accounts, (
            f"Account {account} should NOT be in RANGER response, got {response_accounts}"
        )


def test_players_filter_invalid_profession_422() -> None:
    """v0.9.0: ``?profession=NOT_A_REAL_PROFESSION`` returns 422.

    The :func:`_parse_profession_filter` helper raises
    HTTPException(422) for unknown values. The response's
    ``detail`` is a plain string (NOT a Pydantic
    list-of-objects -- the route catches the unknown
    value at the route layer, BEFORE any model-level
    validation). The detail string includes the rejected
    value for debuggability.
    """
    resp = client.get(
        "/api/v1/players",
        params={"profession": "NOT_A_REAL_PROFESSION"},
    )
    assert resp.status_code == 422
    body = resp.json()
    # The detail is a string (route-level HTTPException,
    # not Pydantic validation). The string includes the
    # rejected value in repr form (``'NOT_A_REAL_PROFESSION'``).
    detail = body.get("detail", "")
    assert isinstance(detail, str), f"detail should be a string, got {type(detail)}: {body}"
    assert "NOT_A_REAL_PROFESSION" in detail, (
        f"rejected value should appear in detail, got: {detail}"
    )


def test_players_filter_accepts_integer_value() -> None:
    """v0.9.0: ``?profession=7`` (integer value) returns the Mesmer player.

    The :func:`_parse_profession_filter` helper accepts BOTH
    the enum NAME (case-insensitive) and the integer VALUE
    for canonical-wire-compat. This test locks the integer
    fallback (the wire format is the integer value).
    """
    suffix = _uuid.uuid4().hex[:8]
    _, account_names = _post_minimal_fight_with_professions(
        professions=[7, 2, 8],  # MESMER (int 7), WARRIOR (int 2), NECROMANCER (int 8)
        suffix=suffix,
    )
    mesmer_account, warrior_account, necro_account = account_names
    resp = client.get(
        "/api/v1/players",
        params={"profession": "7", "limit": 500},
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    response_accounts = {r["account_name"] for r in rows}
    # The Mesmer (Profession.MESMER.value == 7) is in the
    # response. The Warrior (value 2) + Necromancer (value 8)
    # are NOT.
    assert mesmer_account in response_accounts
    assert warrior_account not in response_accounts
    assert necro_account not in response_accounts


def test_players_filter_with_pagination() -> None:
    """v0.9.0 + v0.9.2: filter is applied BEFORE pagination; pages stay Mesmer-only.

    Post-v0.9.2 plan 009 Step 5 the conftest's autouse
    ``_isolate_test_state`` wipes the test DB before each
    test, so the "many Mesmer accounts from prior runs"
    pollution is gone. We now seed 5 Mesmers deterministically
    to exercise the cross-page consistency contract:
    1. All rows on every page have ``profession == "PROF(7)"`` (Mesmer)
       -- the filter is applied to every page, not just page 1.
    2. Page 1 + page 2 do not overlap -- the offset/limit
       are consistent on the filtered set.
    """
    # v0.9.2 plan 009 Step 5: seed 5 Mesmers (the conftest wipes
    # accumulated state pre-test; pre-Step-5 the test relied on
    # cross-test pollution, which the conftest now prevents).
    suffix = _uuid.uuid4().hex[:8]
    _post_minimal_fight_with_professions(
        professions=[7] * 5,  # 5 Mesmers
        suffix=suffix,
    )
    resp1 = client.get(
        "/api/v1/players",
        params={"profession": "MESMER", "limit": 2, "offset": 0},
    )
    assert resp1.status_code == 200, resp1.text
    rows1 = resp1.json()
    # Every row on page 1 is a Mesmer (the filter was
    # applied -- if the filter were broken, page 1 might
    # include a Warrior or Necromancer).
    for row in rows1:
        assert row["profession"] == "PROF(7)", f"page 1 row should be Mesmer (PROF(7)), got {row}"
    resp2 = client.get(
        "/api/v1/players",
        params={"profession": "MESMER", "limit": 2, "offset": 2},
    )
    assert resp2.status_code == 200, resp2.text
    rows2 = resp2.json()
    # Every row on page 2 is a Mesmer too.
    for row in rows2:
        assert row["profession"] == "PROF(7)", f"page 2 row should be Mesmer (PROF(7)), got {row}"
    page1_accounts = {r["account_name"] for r in rows1}
    page2_accounts = {r["account_name"] for r in rows2}
    # Page 1 + page 2 must not overlap (the offset/limit
    # are consistent on the filtered set).
    assert page1_accounts & page2_accounts == set(), (
        f"page 1 + page 2 overlap: {page1_accounts & page2_accounts}"
    )


def test_players_filter_does_not_affect_other_responses() -> None:
    """v0.9.0: the filter is scoped to the list endpoint only.

    The ``/api/v1/players/{account_name}`` detail route does
    NOT accept a ``?profession=`` filter. Querying the detail
    route with ``?profession=MESMER`` returns the player's
    full profile (the filter is silently ignored -- not a
    422, not a partial filter, the detail response is
    unchanged).
    """
    suffix = _uuid.uuid4().hex[:8]
    _, account_names = _post_minimal_fight_with_professions(
        professions=[7, 2],  # MESMER + WARRIOR
        suffix=suffix,
    )
    mesmer_account = account_names[0]
    encoded = quote(mesmer_account, safe="")
    # The detail route ignores the ``?profession=`` filter
    # (the filter is only on the list endpoint). The response
    # is the full profile for the Mesmer.
    resp = client.get(
        f"/api/v1/players/{encoded}",
        params={"profession": "WARRIOR"},  # intentionally mismatched
    )
    assert resp.status_code == 200, resp.text
    profile = resp.json()
    assert profile["account_name"] == mesmer_account
    # The detail response is unchanged by the filter (the
    # ``profession`` field in the response is the Mesmer's
    # modal profession, not the Warrior filter value).
    assert profile["fights_attended"] >= 1
    # The ``profession`` field is the wire-format string label
    # (``"PROF(7)"`` for Mesmer -- see :func:`_profession_label`
    # in routes/players.py for the exact wire shape).
    assert profile["profession"] == "PROF(7)"
    # v0.10.3 plan 083: the per-fight breakdown now carries the
    # role detection (detected_role / detected_tags). The Mesmer
    # seeded above has damage-only events (the back-and-forth
    # cbtevent stream in the fixture), so the heuristic should
    # classify it as DPS (the Mesmer's profession hint is DPS,
    # and the damage axis crosses the pure threshold). The
    # assertion locks BOTH the non-None invariant AND the
    # specific value to catch regressions in the algorithm or
    # the route integration (a weak ``is not None`` check would
    # miss a regression that classifies everything as UNKNOWN).
    breakdown_roles = [row.get("detected_role") for row in profile["per_fight_breakdown"]]
    assert any(r is not None for r in breakdown_roles), (
        f"expected at least one per-fight breakdown row with a non-None "
        f"detected_role, got {breakdown_roles!r}"
    )
    assert "DPS" in breakdown_roles, (
        f"expected at least one per-fight breakdown row classified as "
        f"DPS (Mesmer with damage-only events -> DPS via profession hint), "
        f"got {breakdown_roles!r}"
    )
