"""End-to-end POST /uploads + GET /fights/{id}/events tests against a real Postgres.

Builds a synthetic ``.zevtc`` in-memory (using :pymod:`struct` to
mimic the arcdps layout), POSTs it through the public API, then
queries GET ``/uploads`` + GET ``/fights`` + GET ``/fights/{id}/events``
to verify the schema + Phase 7 v1 wire-up are correct.

The fixture now appends a 64-byte ``cbtevent`` record per damage event
so the parser surfaces a non-empty stream and the persistence layer
can write ``events_blob_uri`` end-to-end. Truncated cbtevent trailing
bytes are tolerated by :meth:`PythonEvtcParser.parse_events` so the
fixture can use a whole-record span.

Requires a Postgres server reachable at the ``DATABASE_URL`` declared
in ``pyproject.toml`` / ``.env``. Run ``docker compose up -d
gw2a-postgres`` first if your local environment does not already
expose Postgres on port 5432.

The happy-path test is **idempotent** by design: each run injects a
uuid-derived suffix into ``agent_id``, ``name``, the build string,
the skill ``id``s and the cbtevent ``time_ms`` so the
``fight_agents (fight_id, agent_id)`` PK, the
``fight_skills (fight_id, skill_id)`` PK and the ``fights.id`` are
unique per invocation. No CASCADE truncate needed.

See ``apps/api/README.md`` for how to bring up the upstream Postgres
dependency locally + in CI.
"""

from __future__ import annotations

import struct
import time
import uuid as _uuid
import zipfile
from io import BytesIO
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from gw2analytics_api.main import app

client = TestClient(app)

# V1.3 EVTC layout (matches libs/gw2_evtc_parser parser.py):
#   25-byte header (magic + 8B build + rev + encounter + unused
#                   + agent_count + skill_count + language)
#   + agent_count x 96-byte agent records
#   + skill_count x variable-size skill records
#   + N x 64-byte cbtevent records (Phase 7 v1)
_HEADER_FMT = "<4s8sBHBI IB"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 25
_AGENT_RECORD_FMT = "<QIIhhhhhh"
_AGENT_PREFIX_SIZE = struct.calcsize(_AGENT_RECORD_FMT)  # 28
_AGENT_NAME_SIZE = 68
_AGENT_SIZE = _AGENT_PREFIX_SIZE + _AGENT_NAME_SIZE  # 96
_SKILL_HEADER_FMT = "<II"
_SKILL_HEADER_SIZE = struct.calcsize(_SKILL_HEADER_FMT)  # 8
_EVENT_FMT = "<QQQiiIIHHHbbbbbbbbIIbb"
_EVENT_SIZE = struct.calcsize(_EVENT_FMT)  # 64


def _make_cbtevent(
    time_ms: int,
    src: int,
    dst: int,
    value: int,
    skill_id: int,
    *,
    is_statechange: int = 0,
    is_nondamage: int = 0,
    buff_dmg: int = 0,
) -> bytes:
    """Pack one 64-byte cbtevent record matching the parser's struct layout.

    Field padding (pad61..pad66) is set to zero -- the parser does not
    read them. ``value > 0`` + ``is_statechange == 0`` +
    ``is_nondamage == 0`` produces a yielded ``DamageEvent``.

    Phase 8: ``buff_dmg`` is the ``int32`` arcdps field that surfaces a
    separate ``BuffRemovalEvent`` from the heal-class event kind. Set
    to > 0 on a record with ``is_nondamage == 1`` to exercise the
    same-record dual-emit (heal + strip) or the pure-strip (no heal)
    case.
    """
    return struct.pack(
        _EVENT_FMT,
        time_ms,  # uint64 time
        src,  # uint64 src_agent
        dst,  # uint64 dst_agent
        value,  # int32 value
        buff_dmg,  # int32 buff_dmg
        0,  # uint32 overstack_value
        skill_id,  # uint32 skillid
        0,  # uint16 src_instid
        0,  # uint16 dst_instid
        0,  # uint16 translocated
        0,  # uint8 is_cleanup
        is_nondamage,  # uint8 is_nondamage
        is_statechange,  # uint8 is_statechange
        0,  # uint8 is_flanking
        0,  # uint8 is_shields
        0,  # uint8 is_offcycle
        0,  # uint8 pad61
        0,  # uint8 pad62
        0,  # uint32 pad63
        0,  # uint32 pad64
        0,  # uint8 pad65
        0,  # uint8 pad66
    )[:_EVENT_SIZE]


def _make_minimal_zevtc(
    agents: list[tuple[int, int, int, str, bool]],
    build: str,
    skills: list[tuple[int, str]] | None = None,
    events: list[bytes] | None = None,
) -> bytes:
    """Build a synthetic .zevtc blob (zip wrapper around EVTC).

    Uses the V1.3 25-byte header + 96-byte agent records + variable
    skill records. For player agents the combo string
    ``name\\\\0:synth.<id>\\\\0`` is null-padded to 68 bytes; NPCs get a
    single null-terminated name null-padded to 68 bytes. Skill records
    are ``<II`` (skill_id + name_len) + UTF-8 name + 1 byte null.

    ``events`` is an optional list of pre-packed 64-byte cbtevent
    records appended verbatim after the skill block -- Phase 7 v1
    parser drains them with :meth:`PythonEvtcParser.parse_events`.
    """
    if skills is None:
        skills = []
    if events is None:
        events = []
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        header = struct.pack(
            _HEADER_FMT,
            b"EVTC",
            build.encode("ascii"),
            0,
            0,
            0,
            len(agents),
            len(skills),
            0,  # language
        )
        assert len(header) == _HEADER_SIZE
        body = bytearray()
        for aid, prof, elite, name, is_player in agents:
            prefix = struct.pack(
                _AGENT_RECORD_FMT,
                aid,
                prof,
                elite,
                0,
                0,
                0,
                0,
                0,
                0,
            )
            assert len(prefix) == _AGENT_PREFIX_SIZE
            if is_player:
                raw = name.encode() + b"\x00" + f":synth.{aid}".encode() + b"\x00\x00"
            else:
                raw = name.encode() + b"\x00"
            if len(raw) > _AGENT_NAME_SIZE:
                msg = f"agent name region {len(raw)} > {_AGENT_NAME_SIZE}"
                raise ValueError(msg)
            name_buf = raw + b"\x00" * (_AGENT_NAME_SIZE - len(raw))
            assert len(name_buf) == _AGENT_NAME_SIZE
            body += prefix + name_buf
        for skill_id, skill_name in skills:
            name_bytes = skill_name.encode("utf-8")
            skill_record = (
                struct.pack(_SKILL_HEADER_FMT, skill_id, len(name_bytes)) + name_bytes + b"\x00"
            )
            body += skill_record
        for ev in events:
            # ``ev`` is a pre-packed 64-byte cbtevent record from
            # :func:`_make_cbtevent` -- no further packing here.
            body += ev
        zf.writestr("fight.evtc", header + bytes(body))
    return buf.getvalue()


def test_uploads_e2e_happy_path() -> None:  # noqa: PLR0915  -- single happy path: POST + GET upload + GET fight + GET events
    # Per-run uuid suffix keeps fights.id, fight_agents (fight_id,
    # agent_id) and fight_skills (fight_id, skill_id) unique across
    # re-runs, so no CASCADE truncate is required.
    suffix = _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_skill_b = base_skill_a + 1

    # Two damage cbtevent records targeting agent B with skill A. Both
    # satisfy the Phase 7 v1 filter (``is_statechange == 0``,
    # ``is_nondamage == 0``, ``value > 0``), so the parser yields 2
    # ``DamageEvent`` records and the blob URI is non-null. Timestamps
    # span 2 separate 1-second buckets so the small ``window_s=1``
    # roll-up shows 2 buckets instead of one combined mega-bucket.
    # Two healing cbtevent records (Phase 7 v2: ``is_nondamage == 1``,
    # ``value > 0``) flow the opposite direction (B healing A) so the
    # per-target healing roll-up has a non-empty payload on a
    # DIFFERENT target than the damage roll-up -- exercises the
    # damage-only / heal-only / mixed-fight cases the route has to
    # support independently.
    # Phase 8: one of the heal records carries ``buff_dmg > 0`` so it
    # dual-emits a ``HealingEvent`` AND a ``BuffRemovalEvent`` from the
    # same cbtevent (corrupting / confusion skill -- heals the caster
    # and strips a boon from the target). One strip-only record
    # (``is_nondamage == 1``, ``value == 0``, ``buff_dmg > 0``) yields
    # ONLY a ``BuffRemovalEvent`` -- the pure-strip path.
    events = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
        _make_cbtevent(
            time_ms=2_500,
            src=base_id_a,
            dst=base_id_b,
            value=567,
            skill_id=base_skill_b,
        ),
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_b,
            dst=base_id_a,
            value=800,
            buff_dmg=300,
            skill_id=base_skill_a,
            is_nondamage=1,
        ),
        _make_cbtevent(
            time_ms=2_500,
            src=base_id_b,
            dst=base_id_a,
            value=400,
            skill_id=base_skill_b,
            is_nondamage=1,
        ),
        # Phase 8 pure-strip record: B strips a buff from A, no heal
        # component. The roll-up lands on target A (alongside the
        # dual-emit strip from above), exercising the same-target
        # roll-up invariant for the BPS aggregator.
        _make_cbtevent(
            time_ms=2_000,
            src=base_id_b,
            dst=base_id_a,
            value=0,
            buff_dmg=200,
            skill_id=base_skill_b,
            is_nondamage=1,
        ),
    ]

    blob = _make_minimal_zevtc(
        [
            (base_id_a, 2, 18, f"E2E Warrior {suffix}", True),
            (base_id_b, 1, 27, f"E2E Guard {suffix}", True),
        ],
        build=build,
        skills=[
            (base_skill_a, f"Whirlwind {suffix}"),
            (base_skill_b, f"Burning Precision {suffix}"),
        ],
        events=events,
    )

    # POST a synthetic .zevtc
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert "id" in created
    assert "sha256" in created
    assert created["status"] in {"pending", "completed", "failed"}

    # GET /uploads/{id} returns the persisted row
    upload_resp = client.get(f"/api/v1/uploads/{created['id']}")
    assert upload_resp.status_code == 200
    payload = upload_resp.json()
    assert payload["sha256"] == created["sha256"]
    assert payload["status"] == "completed"
    assert payload["parser_version"]  # non-empty
    assert payload["fight_id"] is not None

    # GET /fights/{id} returns the parsed fight with 2 agents + 2 skills
    fight_resp = client.get(f"/api/v1/fights/{payload['fight_id']}")
    assert fight_resp.status_code == 200
    fight = fight_resp.json()
    assert fight["agent_count"] == 2
    assert len(fight["agents"]) == 2
    names = {a["name"] for a in fight["agents"]}
    assert names == {f"E2E Warrior {suffix}", f"E2E Guard {suffix}"}
    for a in fight["agents"]:
        assert a["is_player"] is True
        assert a["account_name"] is not None
        assert a["account_name"].startswith(":synth.")
        assert a["subgroup"] == ""
    # V1.3: skills round-trip
    assert len(fight["skills"]) == 2
    skill_names = {s["name"] for s in fight["skills"]}
    assert skill_names == {f"Whirlwind {suffix}", f"Burning Precision {suffix}"}
    skill_ids = {s["id"] for s in fight["skills"]}
    assert skill_ids == {base_skill_a, base_skill_b}

    # Phase 7 v1: GET /fights/{id}/events returns the aggregated summary.
    # ``window_s=1`` keeps both events in separate 1-second buckets so
    # the roll-up is observable (``duration_s == max(time_ms) / 1000``
    # = 2.5, target_dps rows collapsed to a single entry because both
    # events hit the same target).
    events_resp = client.get(
        f"/api/v1/fights/{payload['fight_id']}/events",
        params={"window_s": 1},
    )
    assert events_resp.status_code == 200, events_resp.text
    summary = events_resp.json()
    assert summary["fight_id"] == payload["fight_id"]
    assert summary["duration_s"] == pytest.approx(2.5)
    assert len(summary["target_dps"]) == 1
    row = summary["target_dps"][0]
    assert row["target_agent_id"] == base_id_b
    assert row["total_damage"] == 1_234 + 567
    assert row["dps"] == pytest.approx((1_234 + 567) / 2.5)
    # 2 events landed in the first 3 second-timespan; window_s=1
    # buckets are [0,1000), [1000,2000), [2000,3000) so buckets 1 + 2
    # each carry exactly 1 event.
    assert len(summary["event_windows"]) == 3
    counts = [b["event_count"] for b in summary["event_windows"]]
    # Per-bucket event_count: bucket 0 [0,1s) is empty; bucket 1
    # [1s,2s) carries 1 damage (t=1.5s) + 1 heal (t=1.5s) + 1 strip
    # (t=1.5s, the dual-emit's strip half) = 3 events; bucket 2
    # [2s,3s) carries 1 damage (t=2.5s) + 1 heal (t=2.5s) + 1 pure
    # strip (t=2.0s) = 3 events. The dual-emit at t=1.5s inflates
    # bucket 1's count by 1 (the strip half) -- without it the
    # expected would be [0, 2, 3].
    assert counts == [0, 3, 3]
    damages = [b["damage_total"] for b in summary["event_windows"]]
    assert damages == [0, 1_234, 567]
    healings = [b["healing_total"] for b in summary["event_windows"]]
    assert healings == [0, 800, 400]
    # Phase 7 v1 of the API: per-target healing roll-up. Strict
    # parallel of ``target_dps`` -- damage flowed A->B, healing
    # flowed B->A, so the two roll-ups land on DIFFERENT targets,
    # exercising the damage-only / heal-only / mixed-fight cases
    # the route supports independently.
    assert len(summary["target_healing"]) == 1
    heal_row = summary["target_healing"][0]
    assert heal_row["target_agent_id"] == base_id_a
    assert heal_row["total_healing"] == 800 + 400
    assert heal_row["hps"] == pytest.approx((800 + 400) / 2.5)
    # Phase 8: per-target buff-removal roll-up. The dual-emit
    # record (``is_nondamage == 1``, ``value == 800``,
    # ``buff_dmg == 300``) yields a strip landing on A; the
    # pure-strip record (``value == 0``, ``buff_dmg == 200``) also
    # lands on A. Both strips target A, so the roll-up has one row
    # with ``total_buff_removal == 300 + 200 = 500`` and
    # ``bps == 500 / 2.5 = 200.0``.
    assert len(summary["target_buff_removal"]) == 1
    strip_row = summary["target_buff_removal"][0]
    assert strip_row["target_agent_id"] == base_id_a
    assert strip_row["total_buff_removal"] == 300 + 200
    assert strip_row["bps"] == pytest.approx((300 + 200) / 2.5)


def test_fight_events_404_when_unknown_fight() -> None:
    """GET /fights/{unknown}/events returns 404."""
    resp = client.get("/api/v1/fights/does-not-exist-1234/events")
    assert resp.status_code == 404


def test_fight_events_422_when_window_s_too_small() -> None:
    """GET /fights/{id}/events?window_s=0 returns 422 (Pydantic Query validation)."""
    # The Query ge=1 constraint kicks in BEFORE the handler runs, so
    # this is a FastAPI-level validation rejection rather than an
    # aggregator ValueError.
    resp = client.get("/api/v1/fights/anything/events", params={"window_s": 0})
    assert resp.status_code == 422


def test_healthz_responds() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# v0.7.0: player-centric surface + per-fight squad/skill roll-ups
#
# These tests are SELF-CONTAINED: each one POSTs its own .zevtc
# fixture so the test order is irrelevant. Sharing a single
# happy-path fight across multiple tests would make the suite
# fragile (any failure in the shared setup cascades).
# ---------------------------------------------------------------------------


def _post_minimal_fight(
    events: list[bytes] | None = None,
    suffix: str | None = None,
) -> str:
    """POST a minimal 2-player fight with optional cbtevent records.

    Returns the persisted ``fight_id``. The fixture mirrors the
    happy-path's 2-player layout (Warrior A + Guardian B, both
    with empty subgroup) so the per-subgroup roll-up has exactly
    1 row in the empty-string bucket.

    ``suffix`` lets callers thread their own uuid-derived suffix
    through the helper so the agent + skill IDs in the
    cbtevent records match the IDs the parser writes into the
    agent table. Without this, the route's source-side
    attribution silently drops the events (``local_agents.get(
    event.source_agent_id)`` returns ``None`` because the
    parser-assigned agent_id differs from the cbtevent's
    source_agent_id) and the player is missing from the
    cross-fight roll-up.
    """
    suffix = suffix or _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_skill_b = base_skill_a + 1
    blob = _make_minimal_zevtc(
        [
            (base_id_a, 2, 18, f"V07 Warrior {suffix}", True),
            (base_id_b, 1, 27, f"V07 Guard {suffix}", True),
        ],
        build=build,
        skills=[
            (base_skill_a, f"Whirlwind {suffix}"),
            (base_skill_b, f"Burning {suffix}"),
        ],
        events=events or [],
    )
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]
    # Poll the upload status until the background parser flips
    # ``status`` to ``"completed"``; the POST handler spawns
    # ``process_parse`` via FastAPI's BackgroundTasks, so the
    # upload is still "pending" immediately after the POST. The
    # tests downstream depend on the events blob being written
    # (the /players + /squads + /skills routes read it), so the
    # wait is mandatory. A 5s ceiling is generous: the parser
    # completes in milliseconds for a fixture-sized blob.
    for _ in range(50):
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        assert upload_resp.status_code == 200
        if upload_resp.json()["status"] == "completed":
            # The FastAPI BackgroundTasks runner fires after
            # the POST response is sent, so the first poll
            # iteration might race the task startup. A small
            # sleep gives the parser a chance to write the
            # events blob before the downstream tests query
            # it. The 5s ceiling is generous: the parser
            # completes in milliseconds for a fixture-sized
            # blob.
            time.sleep(0.1)
            return str(upload_resp.json()["fight_id"])
        time.sleep(0.1)
    msg = f"upload {upload_id} did not reach 'completed' within 5s"
    raise AssertionError(msg)


def test_players_list_returns_accounts_present_in_fight() -> None:
    """v0.7.0: GET /api/v1/players returns one row per account_name with
    the cross-fight totals. The e2e fixture seeds 2 players (A + B),
    so the list should contain both account_names.
    """
    _post_minimal_fight()
    resp = client.get("/api/v1/players")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert isinstance(rows, list)
    assert len(rows) >= 2
    accounts = {r["account_name"] for r in rows}
    assert any(a.startswith(":synth.") for a in accounts)


def test_player_detail_returns_profile_with_per_fight_breakdown() -> None:
    """v0.7.0: GET /api/v1/players/{account_name} returns the full profile
    + per-fight breakdown array.

    Seeds the fight with at least 1 cbtevent so the parser writes
    a non-null ``events_blob_uri``; the player route's
    ``_compute_contributions`` returns 0 contributions for a fight
    with no events, which would 404 the test.
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    # Seed TWO events (A→B + B→A) so BOTH player agents have
    # non-zero contributions; the test picks the first player
    # agent from the API response (which may be A or B depending
    # on ORM ordering) and queries their profile. A single
    # directional event would leave one agent with 0 contributions
    # and 404 the test.
    events = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
        _make_cbtevent(
            time_ms=2_000,
            src=base_id_b,
            dst=base_id_a,
            value=500,
            skill_id=base_skill_a,
        ),
    ]
    fight_id = _post_minimal_fight(events, suffix=suffix)
    fight_resp = client.get(f"/api/v1/fights/{fight_id}")
    assert fight_resp.status_code == 200
    fight = fight_resp.json()
    player_agents = [a for a in fight["agents"] if a.get("account_name")]
    assert player_agents, "expected at least 1 player agent in the fixture"
    account_name = player_agents[0]["account_name"]

    encoded = quote(account_name, safe="")
    resp = client.get(f"/api/v1/players/{encoded}")
    assert resp.status_code == 200, resp.text
    profile = resp.json()
    assert profile["account_name"] == account_name
    assert profile["fights_attended"] >= 1
    assert profile["total_damage"] >= 0
    assert profile["total_healing"] >= 0
    assert profile["total_buff_removal"] >= 0
    assert isinstance(profile["attended_fight_ids"], list)
    assert isinstance(profile["per_fight_breakdown"], list)
    assert len(profile["per_fight_breakdown"]) == profile["fights_attended"]


def test_player_detail_404_when_account_unknown() -> None:
    """v0.7.0: GET /api/v1/players/{unknown} returns 404."""
    resp = client.get("/api/v1/players/does-not-exist-1234")
    assert resp.status_code == 404


def test_fight_squads_returns_per_subgroup_rollup() -> None:
    """v0.7.0: GET /api/v1/fights/{id}/squads returns the squad roll-up.

    Exercises the Phase 8 DUAL-EMIT case: the cbtevent at
    t=1.5s carries ``is_nondamage=1``, ``value=800``,
    ``buff_dmg=300`` — the parser yields BOTH a ``HealingEvent``
    (heal=800) AND a ``BuffRemovalEvent`` (strip=300) from the
    same record. Both contributions land in the empty-string
    subgroup bucket (the fixture seeds empty subgroups).
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_skill_b = base_skill_a + 1
    events = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
        _make_cbtevent(
            time_ms=2_500,
            src=base_id_a,
            dst=base_id_b,
            value=567,
            skill_id=base_skill_b,
        ),
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_b,
            dst=base_id_a,
            value=800,
            buff_dmg=300,
            skill_id=base_skill_a,
            is_nondamage=1,
        ),
        _make_cbtevent(
            time_ms=2_500,
            src=base_id_b,
            dst=base_id_a,
            value=400,
            skill_id=base_skill_b,
            is_nondamage=1,
        ),
        _make_cbtevent(
            time_ms=2_000,
            src=base_id_b,
            dst=base_id_a,
            value=0,
            buff_dmg=200,
            skill_id=base_skill_b,
            is_nondamage=1,
        ),
    ]
    fight_id = _post_minimal_fight(events, suffix=suffix)

    resp = client.get(f"/api/v1/fights/{fight_id}/squads")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["fight_id"] == fight_id
    assert payload["duration_s"] > 0
    assert isinstance(payload["squads"], list)
    assert len(payload["squads"]) == 1
    squad = payload["squads"][0]
    assert squad["subgroup"] == ""
    assert squad["total_damage"] == 1_234 + 567
    assert squad["total_healing"] == 800 + 400
    assert squad["total_buff_removal"] == 300 + 200


def test_fight_skills_returns_per_skill_rollup() -> None:
    """v0.7.0: GET /api/v1/fights/{id}/skills returns the per-skill roll-up.

    Exercises the Phase 8 DUAL-EMIT case: skill A carries
    damage=1234 + heal=800 + strip=300 from the same cbtevent's
    dual-emit half. The roll-up has 2 rows ordered by total_damage
    DESC; skill A wins (1234 > 567).
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_skill_b = base_skill_a + 1
    events = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
        _make_cbtevent(
            time_ms=2_500,
            src=base_id_a,
            dst=base_id_b,
            value=567,
            skill_id=base_skill_b,
        ),
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_b,
            dst=base_id_a,
            value=800,
            buff_dmg=300,
            skill_id=base_skill_a,
            is_nondamage=1,
        ),
    ]
    fight_id = _post_minimal_fight(events, suffix=suffix)

    resp = client.get(f"/api/v1/fights/{fight_id}/skills")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["fight_id"] == fight_id
    assert isinstance(payload["skills"], list)
    assert len(payload["skills"]) == 2
    assert payload["skills"][0]["total_damage"] >= payload["skills"][1]["total_damage"]


def test_fight_squads_404_when_fight_unknown() -> None:
    """v0.7.0: GET /api/v1/fights/{unknown}/squads returns 404."""
    resp = client.get("/api/v1/fights/does-not-exist-1234/squads")
    assert resp.status_code == 404


def test_fight_skills_404_when_fight_unknown() -> None:
    """v0.7.0: GET /api/v1/fights/{unknown}/skills returns 404."""
    resp = client.get("/api/v1/fights/does-not-exist-1234/skills")
    assert resp.status_code == 404
