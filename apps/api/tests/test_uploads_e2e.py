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
from datetime import UTC
from datetime import date as _date
from datetime import datetime as _dt
from datetime import timedelta as _td
from io import BytesIO
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.main import app
from gw2analytics_api.models import OrmFight, OrmFightPlayerSummary

client = TestClient(app)

# V1.3 EVTC layout (matches libs/gw2_evtc_parser parser.py):
#   25-byte header (magic + 8B build + rev + combat + unused
#                   + agent_count + skill_count + trailing_byte)
#   + agent_count x 96-byte agent records
#   + skill_count x variable-size skill records
#   + N x 64-byte cbtevent records (Phase 7 v1)
# Note: the parser reads SKILL_COUNT_OFFSET=20 (inside the header,
# what this test previously called 'map_id') and AGENT_COUNT_OFFSET=16.
# v0.5.0 of gw2_evtc_parser bumped the header from 24 to 25 bytes
# (added a trailing ``B`` field). The parser's ``AGENTS_OFFSET`` is
# ``HEADER_SIZE = 25``, so agent records start at byte 25. The old
# 24-byte header caused a 1-byte shift in all agent name reads
# (truncating the first character of every agent name and breaking
# source-side event attribution).
_HEADER_FMT = "<4s8sBHBI IB"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 25
_AGENT_RECORD_FMT = "<QIIhhhh"
_AGENT_PREFIX_SIZE = struct.calcsize(_AGENT_RECORD_FMT)  # 24
_AGENT_NAME_SIZE = 72
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

    Uses the V1.3 24-byte header + 96-byte agent records + variable
    skill records. For player agents the combo string
    ``name\\\\0:synth.<id>\\\\0`` is null-padded to 72 bytes; NPCs get a
    single null-terminated name null-padded to 72 bytes. Skill records
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
            0,  # rev
            0,  # combat
            0,  # unused
            len(agents),  # agent_count (parser AGENT_COUNT_OFFSET=16)
            len(skills or []),  # skill_count (parser SKILL_COUNT_OFFSET=20).
            # _compute_post_skills_offset Pass 2 uses
            # min(skill_count_hdr, MAX_SKILLS) to walk exactly this many
            # skill records before checking for the event stream. Setting
            # this to 0 causes the fallback to MAX_SKILLS, which walks
            # into event data and finds a spurious skill.
            0,  # trailing byte (v0.5.0 parser header bump from 24 to 25 bytes)
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
        assert a["account_name"].startswith("synth.")
        assert a["subgroup"] == ""
    # V1.3: skills round-trip. The parser's heuristic for finding
    # the event-stream boundary may emit a spurious empty-name
    # skill entry when the first event's time_ms happens to look
    # like a valid skill record. Filter on non-empty names to
    # assert only the real skills we packed.
    real_skills = [s for s in fight["skills"] if s["name"]]
    assert len(real_skills) == 2
    skill_names = {s["name"] for s in real_skills}
    assert skill_names == {f"Whirlwind {suffix}", f"Burning Precision {suffix}"}
    skill_ids = {s["id"] for s in real_skills}
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
    # v0.8.3: the optional ``name`` field surfaces the player-name
    # denormalisation (the agent's arcdps char-name as recorded on
    # ``OrmFightAgent``). Damage flowed A->B, so the row's name is
    # B's char-name. The field is additive -- existing wire
    # consumers ignore it; new consumers use it for the
    # ``TargetFilter`` dropdown labels.
    assert row["name"] == f"E2E Guard {suffix}"
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
    # v0.8.3: same name_map powers all three per-target roll-ups
    # (cross-roll-up consistency invariant: same agent_id ==
    # same name). Healing flowed B->A, so the row's name is
    # A's char-name.
    assert heal_row["name"] == f"E2E Warrior {suffix}"
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
    # v0.8.3: strict parallel of the DPS + Healing assertions --
    # the same name_map produces the same name on every roll-up
    # row that targets A.
    assert strip_row["name"] == f"E2E Warrior {suffix}"

    # v0.8.4: the parser also materialises the per-(fight, account)
    # roll-up in ``OrmFightPlayerSummary``. Source-side attribution
    # (event.source_agent_id -> account_name) is the OPPOSITE of the
    # target-side roll-up the test asserted above: the SUMMARY
    # attributes events to the SOURCE agent (the player who
    # generated them), while the per-target roll-ups attribute to
    # the TARGET agent (the player who received them).
    #
    # In this fixture the 2 damage events flow A -> B (A is the
    # source of 1_234 + 567 = 1_801 damage; B receives it). The
    # 2 heal events + 1 dual-emit's strip half + 1 pure-strip
    # record all flow B -> A (B is the source of 800 + 400 = 1_200
    # healing + 300 + 200 = 500 strip-removal; A receives them).
    # A's source-side totals are therefore 1_801 damage + 0 heal
    # + 0 strip; B's are 0 damage + 1_200 heal + 500 strip.
    # The cross-check against the per-target roll-ups above
    # (A received 1_200 heal + 500 strip; B received 1_801
    # damage) confirms the source/target inversion.
    session = get_sessionmaker()()
    try:
        summary_rows = (
            session.execute(
                select(OrmFightPlayerSummary).where(
                    OrmFightPlayerSummary.fight_id == payload["fight_id"],
                ),
            )
            .scalars()
            .all()
        )
        # The fixture has 2 player agents, so we expect exactly
        # 2 summary rows (one per (fight_id, account_name) pair).
        assert len(summary_rows) == 2
        by_account = {r.account_name: r for r in summary_rows}
        a_row = by_account[f"synth.{base_id_a}"]
        b_row = by_account[f"synth.{base_id_b}"]
        # A's source-side totals: A is the SOURCE of the 2 damage
        # events only (the heal + strip events all flow B -> A,
        # so B is their source). A's damage is 1_234 + 567; heal
        # and strip are 0.
        assert a_row.total_damage == 1_234 + 567
        assert a_row.total_healing == 0
        assert a_row.total_buff_removal == 0
        # B's source-side totals: B is the SOURCE of the 2 heal
        # events (800 + 400) + the dual-emit's strip half (300) +
        # the pure-strip (200) = 500 strip total. B's damage is 0
        # (B is the TARGET, not the source, of the 2 damage
        # events).
        assert b_row.total_damage == 0
        assert b_row.total_healing == 800 + 400
        assert b_row.total_buff_removal == 300 + 200
        # Denormalised identity: name is the agent's char-name
        # (last-seen, which here equals the only seen event);
        # profession/elite are the agent table's values.
        assert a_row.name == f"E2E Warrior {suffix}"
        assert b_row.name == f"E2E Guard {suffix}"
    finally:
        session.close()

    # v0.8.4 fast-path parity: the /players list, /players/{name}
    # detail, and /players/{name}/timeline routes must serve the
    # SAME per-(fight, account) totals via the new
    # OrmFightPlayerSummary fast-path that the v0.7.0 slow-path
    # served via the events blob walk. The two paths are locked
    # against drift by this assertion (a regression in the
    # fast-path would flip one of these totals and fail the
    # test). The aggregation rules (last-seen name, first-seen
    # profession/elite) are the same in both paths; only the
    # READ source differs.
    players_resp = client.get("/api/v1/players")
    assert players_resp.status_code == 200, players_resp.text
    players_rows = players_resp.json()
    players_by_account = {r["account_name"]: r for r in players_rows}
    a_player = players_by_account[f"synth.{base_id_a}"]
    # Source-side attribution: A is the source of 2 damage events
    # only (the heal + strip events all flow B -> A). The
    # player route's cross-fight roll-up feeds the same per-(fight,
    # account) contributions, so the totals match the summary
    # table assertions above.
    assert a_player["total_damage"] == 1_234 + 567
    assert a_player["total_healing"] == 0
    assert a_player["total_buff_removal"] == 0
    assert a_player["fights_attended"] == 1

    # v0.8.4 re-parse safety: re-uploading the same SHA (the parser
    # reuses the existing OrmFight row) must DELETE the old
    # summary rows and INSERT the new ones -- not duplicate them.
    # The events blob itself is identical (same SHA), so the
    # per-(fight, account) totals are also identical; the only
    # observable signal is the ROW COUNT (no duplicates) + the
    # timestamps on the rows (the new INSERTs overwrite the old
    # DELETE-tracked rows). Re-posting via the test client.
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    _wait_for_upload_completion(resp.json()["id"])
    # After re-parse: still exactly 2 summary rows (no duplicate
    # INSERTs from the first parse + the second parse).
    session = get_sessionmaker()()
    try:
        summary_rows = (
            session.execute(
                select(OrmFightPlayerSummary).where(
                    OrmFightPlayerSummary.fight_id == payload["fight_id"],
                ),
            )
            .scalars()
            .all()
        )
        assert len(summary_rows) == 2
        by_account = {r.account_name: r for r in summary_rows}
        # Totals are unchanged (same events blob => same totals).
        assert by_account[f"synth.{base_id_a}"].total_damage == 1_234 + 567
        assert by_account[f"synth.{base_id_a}"].total_healing == 0
        assert by_account[f"synth.{base_id_b}"].total_buff_removal == 300 + 200
    finally:
        session.close()


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
    *,
    agents: list[tuple[int, int, int, str, bool]] | None = None,
) -> str:
    """POST a minimal 2-agent fight with optional cbtevent records.

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

    ``agents`` (added in v0.10.3 plan 083 Feature 3A test refactor)
    lets callers override the default 2-player layout with a
    custom agent list -- the per-player timeline's 0-player
    contract test posts an NPC-only fight (``is_player=False``
    on both agents) so the source-side attribution filter
    strips every event and the route returns 200 OK with
    ``series: []`` (NOT 404). The kwarg is fully flexible --
    any 2-tuple of ``(aid, prof, elite, name, is_player)``
    tuples is accepted -- but the default (V07 Warrior +
    V07 Guard) preserves backward compatibility with the 14
    pre-existing callers.
    """
    suffix = suffix or _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_skill_b = base_skill_a + 1
    if agents is None:
        agents = [
            (base_id_a, 2, 18, f"V07 Warrior {suffix}", True),
            (base_id_b, 1, 27, f"V07 Guard {suffix}", True),
        ]
    blob = _make_minimal_zevtc(
        agents,
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
    return _wait_for_upload_completion(upload_id)


def _wait_for_upload_completion(upload_id: str) -> str:
    """Poll the upload status until the background parser flips
    ``status`` to ``"completed"``, then return the persisted ``fight_id``.

    The POST handler spawns :func:`process_parse` via FastAPI's
    ``BackgroundTasks``, so the upload is still ``"pending"`` immediately
    after the POST. Downstream tests depend on the events blob being
    written (the ``/players`` + ``/squads`` + ``/skills`` routes read it),
    so the wait is mandatory. A 5s ceiling is generous: the parser
    completes in milliseconds for a fixture-sized blob.

    A small post-completion ``time.sleep(0.1)`` gives the parser a chance
    to write the events blob before the downstream tests query it; the
    BackgroundTasks runner fires after the POST response is sent, so the
    first poll iteration may race the task startup.
    """
    for _ in range(50):
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        assert upload_resp.status_code == 200
        if upload_resp.json()["status"] == "completed":
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
    assert any(a.startswith("synth.") for a in accounts)


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


def test_player_routes_accept_colon_prefixed_account_name() -> None:
    """Retrocompatibility: routes that accept ``account_name`` in the URL
    still tolerate the legacy arcdps ``:`` prefix.

    The persistence layer now stores account names in bare form
    (``synth.<id>``), but external bookmarks / frontend URLs may
    still reference the old colon-prefixed form (``%3Asynth.<id>``).
    The player detail, player timeline, and per-fight player-skills
    routes all strip the leading ``:`` defensively and return the
    canonical bare account_name on the wire.
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    events = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
    ]
    fight_id = _post_minimal_fight(events, suffix=suffix)

    # The fixture seeds agent A as a player with bare account_name
    # ``synth.<base_id_a>``. Build the legacy colon-prefixed form
    # and URL-encode it so the request path contains ``%3Asynth...``.
    bare_account_name = f"synth.{base_id_a}"
    colon_prefixed = f":{bare_account_name}"
    encoded = quote(colon_prefixed, safe="")
    assert encoded.startswith("%3A"), (
        "the colon must be URL-encoded for this retrocompatibility test"
    )

    # Player detail with colon prefix.
    detail_resp = client.get(f"/api/v1/players/{encoded}")
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()
    assert detail["account_name"] == bare_account_name
    assert detail["fights_attended"] >= 1

    # Player timeline with colon prefix.
    timeline_resp = client.get(f"/api/v1/players/{encoded}/timeline")
    assert timeline_resp.status_code == 200, timeline_resp.text
    timeline = timeline_resp.json()
    assert timeline["account_name"] == bare_account_name
    assert timeline["total"] >= 1

    # Per-fight player skills with colon prefix. Agent A is the
    # source of the seeded damage event, so the skill roll-up
    # must contain at least one skill row.
    skills_resp = client.get(f"/api/v1/fights/{fight_id}/players/{encoded}/skills")
    assert skills_resp.status_code == 200, skills_resp.text
    skills = skills_resp.json()
    assert skills["fight_id"] == fight_id
    assert skills["account_name"] == bare_account_name
    assert skills["agent_id"] == base_id_a
    assert len(skills["skills"]) == 1
    assert skills["skills"][0]["total_damage"] == 1_234


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


# ---------------------------------------------------------------------------
# v0.8.0: account-level historical timelines
# ---------------------------------------------------------------------------


def test_player_timeline_returns_paginated_recency_first_points() -> None:
    """v0.8.0: GET /api/v1/players/{name}/timeline returns the per-fight
    history sorted by started_at DESC, with limit/offset slices.

    Seeds TWO fights for the same account (so ``total >= 2``),
    then validates that offset 0 / limit 1 returns the most
    recent fight + offset 1 / limit 1 returns the second-most
    recent. The 3 totals per point are independent (the 2
    fights seed different event signatures).
    """
    suffix_a = _uuid.uuid4().hex[:8]
    suffix_b = _uuid.uuid4().hex[:8]

    # Fight 1: A damages B (1234 + 567 = 1801 damage, no heal/strip).
    base_id_a = 100_000 + (int(suffix_a[:4], 16) if len(suffix_a) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix_a[:4], 16) if len(suffix_a) >= 4 else 0)
    base_skill_b = base_skill_a + 1
    events_a = [
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
    ]
    fight_id_a = _post_minimal_fight(events_a, suffix=suffix_a)

    # Fight 2: A heals B (800 + 400 = 1200 healing, no damage).
    # Bypass ``_post_minimal_fight`` and inline a custom POST so the
    # 2 fights share the same ``account_name`` (A and B are
    # identical agent_ids between fight 1 and fight 2, so the
    # parser-assigned account_name ``:synth.<base_id_a>`` is
    # shared). Reusing ``_post_minimal_fight`` would force a fresh
    # uuid suffix and break the cross-fight account_name contract
    # the timeline endpoint depends on.
    base_skill_c = 2_000_000 + (int(suffix_b[:4], 16) if len(suffix_b) >= 4 else 0)
    base_skill_d = base_skill_c + 1
    events_b = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,  # A (same as fight 1)
            dst=base_id_b,  # B (same as fight 1)
            value=800,
            skill_id=base_skill_c,
            is_nondamage=1,
        ),
        _make_cbtevent(
            time_ms=2_500,
            src=base_id_a,
            dst=base_id_b,
            value=400,
            skill_id=base_skill_d,
            is_nondamage=1,
        ),
    ]
    blob_b = _make_minimal_zevtc(
        [
            (base_id_a, 2, 18, f"V08 Warrior {suffix_b}", True),
            (base_id_b, 1, 27, f"V08 Guard {suffix_b}", True),
        ],
        build=f"2025{int(suffix_b[:4], 16) % 10000:04d}",
        skills=[
            (base_skill_c, f"Whirlwind B {suffix_b}"),
            (base_skill_d, f"Burning B {suffix_b}"),
        ],
        events=events_b,
    )
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob_b, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    fight_id_b = _wait_for_upload_completion(resp.json()["id"])
    assert fight_id_a != fight_id_b

    # Pick the shared account_name (agent A's ``:synth.<id>``).
    account_name = f"synth.{base_id_a}"
    encoded = quote(account_name, safe="")

    # Default limit/offset: returns up to 20 most-recent points.
    resp = client.get(f"/api/v1/players/{encoded}/timeline")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["account_name"] == account_name
    assert payload["total"] >= 2
    assert payload["limit"] == 20
    assert payload["offset"] == 0
    assert len(payload["points"]) == payload["total"]
    # Recency-first: the first point is the most recent fight.
    started_ats = [p["started_at"] for p in payload["points"]]
    assert started_ats == sorted(started_ats, reverse=True)

    # Page 1: limit=1 offset=0 returns the most recent fight.
    resp1 = client.get(f"/api/v1/players/{encoded}/timeline", params={"limit": 1, "offset": 0})
    assert resp1.status_code == 200
    page1 = resp1.json()
    assert len(page1["points"]) == 1
    assert page1["total"] >= 2
    assert page1["limit"] == 1
    assert page1["offset"] == 0

    # Page 2: limit=1 offset=1 returns the second-most recent fight.
    resp2 = client.get(f"/api/v1/players/{encoded}/timeline", params={"limit": 1, "offset": 1})
    assert resp2.status_code == 200
    page2 = resp2.json()
    assert len(page2["points"]) == 1
    assert page2["offset"] == 1
    # The 2 pages must not overlap.
    assert page1["points"][0]["fight_id"] != page2["points"][0]["fight_id"]
    # The 2 pages combined cover exactly the first 2 fights.
    first_two = {page1["points"][0]["fight_id"], page2["points"][0]["fight_id"]}
    assert {fight_id_a, fight_id_b} == first_two


def test_player_timeline_404_when_account_unknown() -> None:
    """v0.8.0: GET /api/v1/players/{unknown}/timeline returns 404."""
    resp = client.get("/api/v1/players/does-not-exist-1234/timeline")
    assert resp.status_code == 404


def test_player_timeline_422_when_limit_out_of_range() -> None:
    """v0.8.0: limit=101 (above the 100 ceiling) returns 422."""
    resp = client.get(
        "/api/v1/players/anything/timeline",
        params={"limit": 101},
    )
    assert resp.status_code == 422


def test_player_timeline_422_when_limit_zero() -> None:
    """v0.8.0: limit=0 (below the 1 floor) returns 422.

    Symmetric counterpart to :func:`test_player_timeline_422_when_limit_out_of_range`:
    FastAPI's ``Query(ge=1, le=100)`` rejects 0 with 422 BEFORE the
    handler runs (so the route never sees a bad value). Covers the
    lower bound of the [1, 100] window.
    """
    resp = client.get(
        "/api/v1/players/anything/timeline",
        params={"limit": 0},
    )
    assert resp.status_code == 422


def test_player_timeline_422_when_offset_negative() -> None:
    """v0.8.0: offset=-1 returns 422 (ge=0 constraint)."""
    resp = client.get(
        "/api/v1/players/anything/timeline",
        params={"offset": -1},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# v0.8.1: per-day bucketing on the timeline
# ---------------------------------------------------------------------------


def test_player_timeline_default_bucket_is_fight() -> None:
    """v0.8.1: GET .../timeline without ``bucket`` returns ``bucket="fight"``
    and one point per attended fight (``total >= 1``). The
    ``fight_id`` of each point is the actual fight id, the
    ``started_at`` is the original parser-derived wall-clock time.
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    events = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
    ]
    _post_minimal_fight(events, suffix=suffix)
    account_name = f"synth.{base_id_a}"
    encoded = quote(account_name, safe="")
    resp = client.get(f"/api/v1/players/{encoded}/timeline")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["bucket"] == "fight"
    assert payload["total"] >= 1
    assert len(payload["points"]) >= 1
    # The first point's ``started_at`` is NOT at midnight (the
    # parser writes a real wall-clock timestamp).
    started_at = _dt.fromisoformat(payload["points"][0]["started_at"])
    assert (started_at.hour, started_at.minute, started_at.second) != (0, 0, 0)


def test_player_timeline_day_bucket_aggregates_per_day() -> None:
    """v0.8.1: ``?bucket=day`` collapses fights sharing a calendar day
    into one point. Seed 1 fight; the response has 1 point whose
    ``started_at`` is the day's UTC midnight (the canonical
    day-aligned timestamp) and whose ``bucket`` is ``"day"``.
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
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
            skill_id=base_skill_a,
        ),
    ]
    _post_minimal_fight(events, suffix=suffix)
    account_name = f"synth.{base_id_a}"
    encoded = quote(account_name, safe="")
    resp = client.get(
        f"/api/v1/players/{encoded}/timeline",
        params={"bucket": "day"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["bucket"] == "day"
    assert payload["total"] == len(payload["points"])
    assert payload["total"] >= 1
    # Every point's ``started_at`` is at UTC midnight (the chart's
    # X-axis auto-detects this to render ``MM/DD``).
    for p in payload["points"]:
        started_at = _dt.fromisoformat(p["started_at"])
        assert (started_at.hour, started_at.minute, started_at.second) == (0, 0, 0)
        # The 3 totals are non-negative (the day-bucketed point
        # sums all fights of the day; an empty bucket would
        # not surface a row).
        assert p["total_damage"] >= 0
        assert p["total_healing"] >= 0
        assert p["total_buff_removal"] >= 0
    # The day-bucketed point's total_damage is the sum of the
    # seeded events (1_234 + 567 = 1_801).
    assert payload["points"][0]["total_damage"] == 1_234 + 567


def test_player_timeline_422_when_bucket_invalid() -> None:
    """v0.8.1: ``?bucket=week`` (not in the Literal["fight", "day"]
    set) returns 422 BEFORE the handler runs. FastAPI's
    Query-validation pattern is identical to the existing
    ``limit`` / ``offset`` 422 tests.
    """
    resp = client.get(
        "/api/v1/players/anything/timeline",
        params={"bucket": "week"},
    )
    assert resp.status_code == 422


def test_player_timeline_day_bucket_splits_across_days() -> None:
    """v0.8.1: ``?bucket=day`` collapses fights sharing a calendar
    day AND emits 1 point per distinct calendar day. Seeds 2
    fights for the same account, then UPDATEs the second
    fight's ``started_at`` to a different calendar day via a
    direct SQLAlchemy UPDATE (the parser writes ``datetime.
    now(UTC)`` at parse time, so the 2 fights would otherwise
    share a day). Asserts the response has exactly 2 points
    with the right per-day ``total_damage``.

    The 2nd fight's POST is inlined (not via
    :func:`_post_minimal_fight`) so the 2 fights share the
    same ``base_id_a`` / ``base_id_b`` agent IDs and therefore
    the same ``account_name = :synth.<base_id_a>``. Reusing
    ``_post_minimal_fight`` for the 2nd fight would force a
    fresh uuid-derived ``base_id_a_2`` and the cbtevent
    records' source/dst IDs would NOT match the 2nd fight's
    agent table, silently dropping the events and leaving
    the 2nd fight with 0 contributions (the route's
    source-side attribution would return ``None`` for every
    event). This is the same inlined-POST pattern used by
    :func:`test_player_timeline_returns_paginated_recency_first_points`.

    The UPDATE goes through :func:`get_sessionmaker` so it
    shares the same connection pool as the route's
    :func:`get_session` dependency -- no DDL or migration is
    required, just a row-level ``UPDATE`` that the route
    observes on its next read.
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)

    # Fight 1: standard 1-event fight, A damages B for 1_234.
    events = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
    ]
    fight_id_1 = _post_minimal_fight(events, suffix=suffix)
    account_name = f"synth.{base_id_a}"
    encoded = quote(account_name, safe="")

    # Fight 2: inline a custom POST so the 2 fights share
    # ``base_id_a`` / ``base_id_b`` (and therefore the same
    # ``account_name``). A damages B for 2_000 with a
    # different skill to keep the skill table disjoint.
    suffix_2 = _uuid.uuid4().hex[:8]
    base_skill_b = 2_000_000 + (int(suffix_2[:4], 16) if len(suffix_2) >= 4 else 0)
    events_2 = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,  # A (same as fight 1)
            dst=base_id_b,  # B (same as fight 1)
            value=2_000,
            skill_id=base_skill_b,
        ),
    ]
    blob_2 = _make_minimal_zevtc(
        [
            (base_id_a, 2, 18, f"V81 Warrior {suffix_2}", True),
            (base_id_b, 1, 27, f"V81 Guard {suffix_2}", True),
        ],
        build=f"2025{int(suffix_2[:4], 16) % 10000:04d}",
        skills=[(base_skill_b, f"V81 Skill {suffix_2}")],
        events=events_2,
    )
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob_2, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    fight_id_2 = _wait_for_upload_completion(resp.json()["id"])
    assert fight_id_1 != fight_id_2

    # Rewind fight 2's started_at by 2 calendar days so the 2
    # fights land on distinct calendar days. The parser wrote
    # ``datetime.now(UTC)`` for both, so without the UPDATE
    # they'd share a day and the day-bucketed response would
    # collapse them into 1 point.
    session = get_sessionmaker()()
    try:
        # ``OrmFight.started_at`` is ``DateTime(timezone=True)`` --
        # a TZ-AWARE column. We must pass a TZ-AWARE datetime or
        # SQLAlchemy raises on the bind. ``datetime.now(UTC)``
        # returns a TZ-aware UTC datetime; ``datetime.utcnow()``
        # is NAIVE and would fail the column type check.
        new_started = _dt.now(UTC) - _td(days=2)
        session.execute(
            update(OrmFight).where(OrmFight.id == fight_id_2).values(started_at=new_started)
        )
        session.commit()
    finally:
        session.close()

    resp = client.get(
        f"/api/v1/players/{encoded}/timeline",
        params={"bucket": "day"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["bucket"] == "day"
    # Exactly 2 day-bucketed points: today + 2 days ago.
    assert payload["total"] == 2
    assert len(payload["points"]) == 2
    # Recency-first: today's point wins.
    started_ats = [_dt.fromisoformat(p["started_at"]) for p in payload["points"]]
    assert started_ats == sorted(started_ats, reverse=True)
    # The 2 day-bucketed points are exactly 2 days apart (UTC).
    assert (started_ats[0] - started_ats[1]).days == 2
    # Per-day totals: the recency-first point carries 1_234
    # damage (today), the second point carries 2_000 damage
    # (2 days ago). We use a list-based comparison instead of
    # a dict keyed on ``started_at`` because the response's
    # ISO string format (``2026-07-07T00:00:00+00:00``) can
    # drift from ``datetime.isoformat()`` output (microsecond
    # truncation, ``Z`` vs ``+00:00``, etc.) and produce a
    # spurious ``KeyError``. The recency-first ordering is
    # already verified by the earlier ``sorted(..., reverse=True)``
    # assertion, so positional access is sufficient.
    assert payload["points"][0]["total_damage"] == 1_234  # today
    assert payload["points"][1]["total_damage"] == 2_000  # 2 days ago
    # The 2 day-bucketed ``fight_id``s are the actual fight_ids
    # of the 2 underlying fights (the day bucket stores the
    # most-recent fight_id of the day, which is the only fight
    # of the day here).
    assert {p["fight_id"] for p in payload["points"]} == {fight_id_1, fight_id_2}


# ---------------------------------------------------------------------------
# v0.8.9: ``?tz=Continent/City`` on the player timeline
# ---------------------------------------------------------------------------


def test_player_timeline_tz_default_is_utc() -> None:
    """v0.8.9: GET .../timeline without ``?tz=`` defaults to UTC.

    Seeds 1 fight and UPDATEs its ``started_at`` to a
    mid-afternoon UTC timestamp (no DST edge case for either
    Paris or NY). Asserts the day-bucketed point is at the
    SAME calendar day in UTC and the response's ``tz`` field
    echoes the default ``"UTC"`` string.

    The day-bucketed ``started_at`` is at UTC midnight (the
    ``_combine_day_midnight`` helper), so the response's ISO
    string is ``"2024-01-15T00:00:00+00:00"`` -- the test
    parses it back and confirms the UTC date matches the
    ``started_at`` we set.
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    events = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
    ]
    fight_id = _post_minimal_fight(events, suffix=suffix)
    account_name = f"synth.{base_id_a}"
    encoded = quote(account_name, safe="")

    # Pin ``started_at`` to a fixed mid-afternoon UTC timestamp
    # (winter -- no DST ambiguity for any TZ). The parser wrote
    # ``datetime.now(UTC)`` at parse time, so the UPDATE is
    # required to assert a known calendar day.
    target_utc = _dt(2024, 1, 15, 14, 30, 0, tzinfo=UTC)
    session = get_sessionmaker()()
    try:
        session.execute(
            update(OrmFight).where(OrmFight.id == fight_id).values(started_at=target_utc)
        )
        session.commit()
    finally:
        session.close()

    # No ``?tz=`` param: defaults to UTC. ``bucket=day`` to
    # exercise the day-bucketing branch.
    resp = client.get(
        f"/api/v1/players/{encoded}/timeline",
        params={"bucket": "day"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["bucket"] == "day"
    assert payload["tz"] == "UTC"
    assert payload["total"] == 1
    assert len(payload["points"]) == 1
    # The day-bucketed point's ``started_at`` is at UTC midnight
    # of the SAME day (2024-01-15). The wire format is UTC
    # (the ``_combine_day_midnight`` helper serialises the
    # local-midnight back to UTC), so the ISO string is
    # ``"2024-01-15T00:00:00+00:00"``.
    p = payload["points"][0]
    started_at = _dt.fromisoformat(p["started_at"])
    assert started_at.astimezone(ZoneInfo("UTC")).date() == _date(2024, 1, 15)
    # The local-time midnight invariant (strict parallel of
    # :func:`test_player_timeline_day_bucket_aggregates_per_day`):
    # at the requested TZ (UTC), the wall-clock time is 00:00:00.
    assert (started_at.hour, started_at.minute, started_at.second) == (0, 0, 0)
    # The 1-event total_damage is the seeded value.
    assert p["total_damage"] == 1_234


def test_player_timeline_tz_europe_paris() -> None:
    """v0.8.9: ``?tz=Europe/Paris`` shifts the day-bucketed point to Paris time.

    Seeds 1 fight at 2024-01-15 23:30:00 UTC. In UTC, this
    is calendar day 2024-01-15; in Europe/Paris (UTC+1 in
    winter, no DST on Jan 15), this is 2024-01-16 00:30:00
    Paris -- so the day-bucketed point should land on
    2024-01-16 in Paris.

    Asserts:
      * the response's ``tz`` field echoes ``"Europe/Paris"``
      * the day-bucketed point's date (in Paris) is 2024-01-16
      * the day-bucketed point's local wall-clock time is 00:00:00
        (Paris midnight, serialised back to UTC on the wire as
        ``"2024-01-15T23:00:00+00:00"``)
      * the same point, queried WITHOUT ``?tz=``, lands on
        2024-01-15 UTC -- the cross-TZ day-shift is observable
        in the response, not just an internal flag.
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    events = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
    ]
    fight_id = _post_minimal_fight(events, suffix=suffix)
    account_name = f"synth.{base_id_a}"
    encoded = quote(account_name, safe="")

    # 2024-01-15 23:30:00 UTC = 2024-01-16 00:30:00 Europe/Paris
    # (UTC+1 in winter). The day-bucketed point should land on
    # 2024-01-16 in Paris.
    target_utc = _dt(2024, 1, 15, 23, 30, 0, tzinfo=UTC)
    session = get_sessionmaker()()
    try:
        session.execute(
            update(OrmFight).where(OrmFight.id == fight_id).values(started_at=target_utc)
        )
        session.commit()
    finally:
        session.close()

    paris = ZoneInfo("Europe/Paris")

    # With ?tz=Europe/Paris: the day-bucketed point lands on
    # 2024-01-16 (Paris) -- NOT 2024-01-15 (the UTC day).
    resp_paris = client.get(
        f"/api/v1/players/{encoded}/timeline",
        params={"bucket": "day", "tz": "Europe/Paris"},
    )
    assert resp_paris.status_code == 200, resp_paris.text
    payload_paris = resp_paris.json()
    assert payload_paris["bucket"] == "day"
    assert payload_paris["tz"] == "Europe/Paris"
    assert payload_paris["total"] == 1
    assert len(payload_paris["points"]) == 1
    p_paris = payload_paris["points"][0]
    started_at_paris = _dt.fromisoformat(p_paris["started_at"])
    # The point's date, in Paris, is 2024-01-16.
    assert started_at_paris.astimezone(paris).date() == _date(2024, 1, 16)
    # And the local wall-clock time in Paris is midnight
    # (serialised back to UTC on the wire: 2024-01-15T23:00:00Z).
    local_paris = started_at_paris.astimezone(paris)
    assert (local_paris.hour, local_paris.minute, local_paris.second) == (0, 0, 0)
    # The damage is unchanged (the TZ only affects the bucket
    # grouping, not the magnitude).
    assert p_paris["total_damage"] == 1_234

    # Cross-check: the SAME fight, queried WITHOUT ``?tz=``,
    # lands on 2024-01-15 (UTC). This is the observable
    # day-shift between the default and the Paris TZ.
    resp_utc = client.get(
        f"/api/v1/players/{encoded}/timeline",
        params={"bucket": "day"},
    )
    assert resp_utc.status_code == 200, resp_utc.text
    payload_utc = resp_utc.json()
    assert payload_utc["tz"] == "UTC"
    assert payload_utc["total"] == 1
    p_utc = payload_utc["points"][0]
    started_at_utc = _dt.fromisoformat(p_utc["started_at"])
    assert started_at_utc.astimezone(ZoneInfo("UTC")).date() == _date(2024, 1, 15)
    # The 2 day-bucketed points are 23 hours apart on the wire
    # (one is 2024-01-15T00:00:00Z, the other is
    # 2024-01-15T23:00:00Z). This is the structural signature
    # of the TZ shift: the SAME UTC instant is midnight in
    # one TZ and 23:00 the previous day in the other, so the
    # serialised UTC timestamps differ by 23h.
    assert (started_at_paris - started_at_utc).total_seconds() == 23 * 3600


def test_player_timeline_tz_america_new_york() -> None:
    """v0.8.9: ``?tz=America/New_York`` shifts the day-bucketed point to NY time.

    Seeds 1 fight at 2024-01-15 02:30:00 UTC. In UTC, this
    is calendar day 2024-01-15; in America/New_York (UTC-5
    in winter, no DST on Jan 15), this is 2024-01-14 21:30:00
    NY -- so the day-bucketed point should land on
    2024-01-14 in NY.

    Strict structural parallel of
    :func:`test_player_timeline_tz_europe_paris` -- the only
    differences are the TZ (NY vs Paris) and the calendar
    direction (NY shifts BACK a day, Paris shifts FORWARD).
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    events = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
    ]
    fight_id = _post_minimal_fight(events, suffix=suffix)
    account_name = f"synth.{base_id_a}"
    encoded = quote(account_name, safe="")

    # 2024-01-15 02:30:00 UTC = 2024-01-14 21:30:00 America/New_York
    # (UTC-5 in winter). The day-bucketed point should land on
    # 2024-01-14 in NY.
    target_utc = _dt(2024, 1, 15, 2, 30, 0, tzinfo=UTC)
    session = get_sessionmaker()()
    try:
        session.execute(
            update(OrmFight).where(OrmFight.id == fight_id).values(started_at=target_utc)
        )
        session.commit()
    finally:
        session.close()

    ny = ZoneInfo("America/New_York")

    # With ?tz=America/New_York: the day-bucketed point lands on
    # 2024-01-14 (NY) -- NOT 2024-01-15 (the UTC day).
    resp_ny = client.get(
        f"/api/v1/players/{encoded}/timeline",
        params={"bucket": "day", "tz": "America/New_York"},
    )
    assert resp_ny.status_code == 200, resp_ny.text
    payload_ny = resp_ny.json()
    assert payload_ny["bucket"] == "day"
    assert payload_ny["tz"] == "America/New_York"
    assert payload_ny["total"] == 1
    assert len(payload_ny["points"]) == 1
    p_ny = payload_ny["points"][0]
    started_at_ny = _dt.fromisoformat(p_ny["started_at"])
    # The point's date, in NY, is 2024-01-14.
    assert started_at_ny.astimezone(ny).date() == _date(2024, 1, 14)
    # And the local wall-clock time in NY is midnight
    # (serialised back to UTC on the wire: 2024-01-14T05:00:00Z,
    # because NY is UTC-5 in winter).
    local_ny = started_at_ny.astimezone(ny)
    assert (local_ny.hour, local_ny.minute, local_ny.second) == (0, 0, 0)
    assert p_ny["total_damage"] == 1_234

    # Cross-check: the SAME fight, queried WITHOUT ``?tz=``,
    # lands on 2024-01-15 (UTC). The day shifts BACK in NY
    # (the opposite direction of the Paris test).
    resp_utc = client.get(
        f"/api/v1/players/{encoded}/timeline",
        params={"bucket": "day"},
    )
    assert resp_utc.status_code == 200, resp_utc.text
    payload_utc = resp_utc.json()
    assert payload_utc["tz"] == "UTC"
    assert payload_utc["total"] == 1
    p_utc = payload_utc["points"][0]
    started_at_utc = _dt.fromisoformat(p_utc["started_at"])
    assert started_at_utc.astimezone(ZoneInfo("UTC")).date() == _date(2024, 1, 15)
    # The NY point is 5 hours BEHIND the UTC point (NY is
    # UTC-5 in winter; the NY midnight of 2024-01-14 is
    # 2024-01-14T05:00:00Z; the UTC midnight of 2024-01-15 is
    # 2024-01-15T00:00:00Z; delta = 19h -- but the test asserts
    # the relative offset from a single instant, not 2 midnights,
    # so the sign + magnitude are: NY point's UTC time is 5h
    # BEFORE the UTC point's UTC time).
    # Actually the 2 points represent different calendar days,
    # so the relative offset is 19h, not 5h. The structural
    # invariant is: the NY point's UTC time is BEFORE the UTC
    # point's UTC time (the day shifted back).
    assert started_at_ny < started_at_utc


def test_player_timeline_tz_422_when_invalid_timezone() -> None:
    """v0.8.9: ``?tz=Mars/Olympus`` (not a valid IANA name) returns 422.

    Seeds 1 fight for a real account so the 404 check
    (which fires BEFORE the TZ parse) passes; the
    handler then reaches the ``ZoneInfo(tz)`` parse
    block, which raises ``ZoneInfoNotFoundError`` on
    the unknown IANA name, which the route surfaces as
    ``HTTP 422 Unprocessable Entity`` to match FastAPI's
    Query-validation convention (invalid query params
    are 422, not 400).

    **404-vs-422 ordering invariant.** An UNKNOWN account
    + valid TZ returns 404 (the 404 check fires first);
    a KNOWN account + invalid TZ returns 422 (the TZ
    parse fires second); an UNKNOWN account + invalid
    TZ also returns 404 (the 404 wins because it fires
    first). This test exercises the second case. The
    first case is covered by
    :func:`test_player_timeline_404_when_account_unknown`
    -- querying with NO ``?tz=`` on an unknown account
    returns 404, confirming the 404 check fires before
    the TZ parse.
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    events = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
    ]
    _post_minimal_fight(events, suffix=suffix)
    # The 404 check needs to PASS so the handler reaches the
    # ``ZoneInfo(tz)`` parse block. Use the real account_name
    # (NOT ``"anything"`` -- the 404 would fire first and mask
    # the 422 we are actually testing).
    account_name = f"synth.{base_id_a}"
    encoded = quote(account_name, safe="")

    resp = client.get(
        f"/api/v1/players/{encoded}/timeline",
        params={"bucket": "day", "tz": "Mars/Olympus"},
    )
    assert resp.status_code == 422
    # The error payload includes the rejected TZ string in the
    # ``detail`` field (matches the existing 422 detail-message
    # convention used by the limit/offset/bucket validators).
    # The route surfaces a plain-string ``detail`` (the
    # ``ZoneInfoNotFoundError`` message) rather than a
    # FastAPI-validation list-detail (no Pydantic field is
    # being validated here -- the IANA name is parsed
    # inside the handler, not by the Query type system).
    body = resp.json()
    assert "Mars/Olympus" in str(body.get("detail", "")), body


# ---------------------------------------------------------------------------
# v0.8.9: per-fight timeline (``GET /api/v1/fights/{id}/timeline``)
#
# The per-fight timeline is a thin wrapper over the existing
# events-blob decompress + per-kind isinstance filter pattern
# from :func:`get_fight_events`. The new aggregator
# :class:`PerFightTimelineAggregator` re-iterates the events
# stream to build the per-bucket (damage + healing + buff-removal)
# roll-up. The 4 tests below exercise the 4 contract corners:
# happy path (3 events in 1 bucket), 404 on unknown fight, 422
# on out-of-range ``window_s`` (both bounds).
# ---------------------------------------------------------------------------


def test_player_timeline_tz_europe_paris_dst_spring_forward() -> None:
    """v0.9.0 followup: EU spring-forward day-bucketing.

    Seeds 1 fight and pins ``started_at`` to a UTC datetime
    that straddles the EU spring-forward boundary (2024-03-31
    01:00 UTC = Paris clocks jump 02:00 CET -> 03:00 CEST).
    With ``?tz=Europe/Paris&bucket=day``, the day-bucketed
    point must land on the Paris calendar day (2024-03-31)
    and the local-midnight invariant must hold at 00:00 Paris.
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    events = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=2_345,
            skill_id=base_skill_a,
        ),
    ]
    fight_id = _post_minimal_fight(events, suffix=suffix)
    account_name = f"synth.{base_id_a}"
    encoded = quote(account_name, safe="")

    # 2024-03-31 01:30 UTC = 03:30 CEST (post-jump). Paris
    # calendar day: 2024-03-31. Without DST awareness the
    # naive day-grouping would bucket on 2024-03-30 (the UTC
    # date) -- that's the regression case the v0.9.0 followup
    # locks.
    target_utc = _dt(2024, 3, 31, 1, 30, 0, tzinfo=UTC)
    session = get_sessionmaker()()
    try:
        session.execute(
            update(OrmFight).where(OrmFight.id == fight_id).values(started_at=target_utc)
        )
        session.commit()
    finally:
        session.close()

    resp = client.get(
        f"/api/v1/players/{encoded}/timeline",
        params={"bucket": "day", "tz": "Europe/Paris"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["bucket"] == "day"
    assert payload["tz"] == "Europe/Paris"
    assert payload["total"] == 1
    assert len(payload["points"]) == 1
    p = payload["points"][0]
    started_at = _dt.fromisoformat(p["started_at"])
    # Paris calendar day is 2024-03-31.
    assert started_at.astimezone(ZoneInfo("Europe/Paris")).date() == _date(2024, 3, 31)
    # Local-midnight invariant at Europe/Paris (regardless of
    # CET vs CEST -- the day-bucketed point is at 00:00:00
    # Paris-local).
    paris = started_at.astimezone(ZoneInfo("Europe/Paris"))
    assert (paris.hour, paris.minute, paris.second) == (0, 0, 0)
    # The 1-event damage total is the seeded value.
    assert p["total_damage"] == 2_345


def test_player_timeline_tz_america_new_york_dst_fall_back() -> None:
    """v0.9.0 followup: US fall-back day-bucketing.

    Seeds 1 fight and pins ``started_at`` to a UTC datetime
    that straddles the US fall-back boundary (2024-11-03 06:00
    UTC = NY clocks roll 02:00 EDT -> 01:00 EST). With
    ``?tz=America/New_York&bucket=day``, the day-bucketed
    point must land on the NY calendar day (2024-11-03) and
    the local-midnight invariant must hold at 00:00 NY local.
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    events = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=3_456,
            skill_id=base_skill_a,
        ),
    ]
    fight_id = _post_minimal_fight(events, suffix=suffix)
    account_name = f"synth.{base_id_a}"
    encoded = quote(account_name, safe="")

    # 2024-11-03 06:30 UTC = 01:30 EST (post-fall-back). NY
    # calendar day: 2024-11-03. The pre-fall-back wall-clock
    # would have been 02:30 EDT; the route honours the
    # wall-clock state at parse time.
    target_utc = _dt(2024, 11, 3, 6, 30, 0, tzinfo=UTC)
    session = get_sessionmaker()()
    try:
        session.execute(
            update(OrmFight).where(OrmFight.id == fight_id).values(started_at=target_utc)
        )
        session.commit()
    finally:
        session.close()

    resp = client.get(
        f"/api/v1/players/{encoded}/timeline",
        params={"bucket": "day", "tz": "America/New_York"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["bucket"] == "day"
    assert payload["tz"] == "America/New_York"
    assert payload["total"] == 1
    assert len(payload["points"]) == 1
    p = payload["points"][0]
    started_at = _dt.fromisoformat(p["started_at"])
    # NY calendar day is 2024-11-03.
    assert started_at.astimezone(ZoneInfo("America/New_York")).date() == _date(2024, 11, 3)
    # Local-midnight invariant at America/New_York (regardless
    # of EDT vs EST -- the day-bucketed point is at 00:00:00
    # NY-local).
    ny = started_at.astimezone(ZoneInfo("America/New_York"))
    assert (ny.hour, ny.minute, ny.second) == (0, 0, 0)
    # The 1-event damage total is the seeded value.
    assert p["total_damage"] == 3_456


def test_fight_timeline_returns_per_bucket_totals_for_known_fight() -> None:
    """v0.8.9: ``GET /fights/{id}/timeline?window_s=1`` returns one row
    per bucket with the correct per-kind totals (damage +
    healing + buff-removal) for a known fight.

    Seeds 3 cbtevent records at distinct ``time_ms`` values
    within a 3-second window (1 damage, 1 heal, 1 strip) +
    asserts the response has the expected per-bucket
    totals. Uses ``window_s=1`` so each event lands in its
    own 1-second bucket.

    The aggregator's ``agents`` + ``duration_s`` parameters
    are accepted for signature parity but NOT consumed by
    the per-bucket aggregation -- the test only asserts
    the wire shape (per-bucket totals + ``window_s`` echo
    + ``duration_s``), not the internal route plumbing.
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    # 3 events: 1 damage at t=1.5s (bucket 1), 1 heal at
    # t=2.5s (bucket 2), 1 strip at t=1.5s (bucket 1, the
    # pure-strip path: value=0 + buff_dmg=200). window_s=1
    # -> 3 contiguous buckets: 0 (zero), 1 (damage + strip),
    # 2 (heal).
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
            src=base_id_b,
            dst=base_id_a,
            value=800,
            skill_id=base_skill_a,
            is_nondamage=1,
        ),
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_b,
            dst=base_id_a,
            value=0,
            buff_dmg=200,
            skill_id=base_skill_a,
            is_nondamage=1,
        ),
    ]
    fight_id = _post_minimal_fight(events, suffix=suffix)

    resp = client.get(
        f"/api/v1/fights/{fight_id}/timeline",
        params={"window_s": 1},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    # The wire shape mirrors the e2e plan: fight_id + window_s
    # + duration_s + points (per-bucket rows sorted ascending
    # by window_start_ms).
    assert payload["fight_id"] == fight_id
    assert payload["window_s"] == 1
    # ``duration_s`` is the parser's max(time_ms) / 1000.0 --
    # the same scalar the /events endpoint uses (V1.3 EVTC
    # header doesn't carry a wall-clock duration).
    assert payload["duration_s"] == pytest.approx(2.5)
    # 3 contiguous 1-second buckets: 0 (zero), 1 (damage + strip),
    # 2 (heal). The continuous-fill invariant mirrors the
    # v0.6.0 EventWindowAggregator contract.
    assert len(payload["points"]) == 3
    # Bucket 0: zero-filled (no events at t < 1s).
    p0 = payload["points"][0]
    assert p0["window_start_ms"] == 0
    assert p0["window_end_ms"] == 1_000
    assert p0["total_damage"] == 0
    assert p0["total_healing"] == 0
    assert p0["total_buff_removal"] == 0
    # Bucket 1: damage (1_234 at t=1.5s) + strip (200 at t=1.5s,
    # the pure-strip half).
    p1 = payload["points"][1]
    assert p1["window_start_ms"] == 1_000
    assert p1["window_end_ms"] == 2_000
    assert p1["total_damage"] == 1_234
    assert p1["total_healing"] == 0
    assert p1["total_buff_removal"] == 200
    # Bucket 2: heal (800 at t=2.5s).
    p2 = payload["points"][2]
    assert p2["window_start_ms"] == 2_000
    assert p2["window_end_ms"] == 3_000
    assert p2["total_damage"] == 0
    assert p2["total_healing"] == 800
    assert p2["total_buff_removal"] == 0


def test_fight_timeline_404_when_unknown_fight() -> None:
    """v0.8.9: ``GET /fights/{unknown}/timeline`` returns 404.

    Same 404 contract as :func:`get_fight_events`: the shared
    ``_load_fight_events`` helper raises 404 when the fight
    id is unknown (the route inherits the contract for free
    via the helper).
    """
    resp = client.get("/api/v1/fights/does-not-exist-1234/timeline")
    assert resp.status_code == 404


def test_fight_timeline_422_when_window_s_too_small() -> None:
    """v0.8.9: ``?window_s=0`` returns 422 (the FastAPI
    ``Query(ge=1)`` validator fires BEFORE the handler).

    Symmetric counterpart to the
    :func:`test_fight_events_422_when_window_s_too_small`
    test -- the per-fight timeline shares the same
    ``window_s`` bounds (``[1, 600]``) as the events endpoint.
    """
    resp = client.get(
        "/api/v1/fights/anything/timeline",
        params={"window_s": 0},
    )
    assert resp.status_code == 422


def test_fight_timeline_422_when_window_s_too_large() -> None:
    """v0.8.9: ``?window_s=601`` returns 422 (the FastAPI
    ``Query(le=600)`` validator fires BEFORE the handler).

    The upper bound ``600`` mirrors the per-fight events
    endpoint (10 minutes is the canonical ceiling for
    per-fight bucket roll-ups -- a longer window would
    yield a single bucket for most fights, which defeats
    the purpose of the timeline visualisation).
    """
    resp = client.get(
        "/api/v1/fights/anything/timeline",
        params={"window_s": 601},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# v0.10.3 plan 083 Feature 3A: per-player timeline
# (``GET /api/v1/fights/{id}/timeline/players``).
#
# The per-player timeline is the SOURCE-SIDE counterpart of the
# aggregated per-fight timeline: one series per player agent, each
# series owns its own per-bucket (damage + healing + buff-removal)
# points, all series share the SAME zero-filled bucket grid (the
# visx multi-line chart's array-alignment contract -- see
# :class:`PerPlayerTimelineAggregator`).
#
# The 4 tests below cover the 4 contract corners the
# :func:`get_fight_player_timeline` route docstring pins:
#   1. happy path with deterministic ordering + per-bucket
#      per-player totals
#   2. 0-player (NPC-only) fight -- 200 OK with ``series: []``
#      (divergent from the /timeline endpoint's 404 contract)
#   3. 404 on unknown fight id
#   4. 422 on out-of-range ``window_s`` (both bounds)
# ---------------------------------------------------------------------------


def test_fight_player_timeline_returns_per_player_per_bucket_series() -> None:
    """Feature 3A happy path: 2-player fight → 2 series sorted by
    (-total_damage, account_name), each with the same zero-filled
    bucket grid.

    Seeds a 2-player fight with A→B damage at t=1.5s AND B→A heal
    at t=2.5s (the B-direction heal uses ``is_nondamage=1`` so the
    parser yields a :class:`HealingEvent`). With ``window_s=1``
    the events land in 2 distinct buckets (1 and 2) with bucket 0
    zero-filled. Source-side attribution:

      * A's series: 1 damage point in bucket 1 (1_234), 0 in others.
      * B's series: 1 heal point in bucket 2 (800), 0 in others.

    Deterministic ordering: A first because ``(-1234, A) < (-0, B)``;
    ties broken by ascending ``account_name`` (the natural lex order
    on ``":synth.<id>"`` with ``base_id_b = base_id_a + 1``).
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_skill_b = base_skill_a + 1
    events = [
        # A (source) damages B (target) for 1_234 at t=1.5s.
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
        # B (source) heals A (target) for 800 at t=2.5s.
        # ``is_nondamage=1`` makes the parser yield a HealingEvent.
        _make_cbtevent(
            time_ms=2_500,
            src=base_id_b,
            dst=base_id_a,
            value=800,
            skill_id=base_skill_b,
            is_nondamage=1,
        ),
    ]
    fight_id = _post_minimal_fight(events, suffix=suffix)

    resp = client.get(
        f"/api/v1/fights/{fight_id}/timeline/players",
        params={"window_s": 1},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    # Wire shape mirrors the per-fight timeline (``/timeline``) contract.
    assert payload["fight_id"] == fight_id
    assert payload["window_s"] == 1
    assert payload["duration_s"] == pytest.approx(2.5)
    # 2 player agents → exactly 2 series (sort order checked below).
    assert len(payload["series"]) == 2

    series_a = payload["series"][0]
    series_b = payload["series"][1]
    # Deterministic ordering: A first because total_damage(A)=1234
    # > total_damage(B)=0; if A and B tied on damage, ascending
    # ``account_name`` would break the tie. With the
    # ``base_id_b = base_id_a + 1`` setup, lex order agrees.
    assert series_a["account_name"] == f"synth.{base_id_a}"
    assert series_b["account_name"] == f"synth.{base_id_b}"

    # A is the SOURCE of the damage event only. Per-bucket
    # placement: bucket 1 (t=1.5s).
    assert len(series_a["points"]) == 3  # window_s=1, max bucket=2
    assert series_a["points"][0]["window_start_ms"] == 0
    assert series_a["points"][0]["window_end_ms"] == 1_000
    assert series_a["points"][0]["total_damage"] == 0
    assert series_a["points"][0]["total_healing"] == 0
    assert series_a["points"][1]["window_start_ms"] == 1_000
    assert series_a["points"][1]["window_end_ms"] == 2_000
    assert series_a["points"][1]["total_damage"] == 1_234
    assert series_a["points"][1]["total_healing"] == 0
    assert series_a["points"][2]["window_start_ms"] == 2_000
    assert series_a["points"][2]["window_end_ms"] == 3_000
    assert series_a["points"][2]["total_damage"] == 0
    assert series_a["points"][2]["total_healing"] == 0

    # B is the SOURCE of the heal event only. Per-bucket
    # placement: bucket 2 (t=2.5s).
    assert len(series_b["points"]) == 3
    assert series_b["points"][0]["total_damage"] == 0
    assert series_b["points"][0]["total_healing"] == 0
    assert series_b["points"][1]["total_damage"] == 0
    assert series_b["points"][1]["total_healing"] == 0
    assert series_b["points"][2]["total_damage"] == 0
    assert series_b["points"][2]["total_healing"] == 800

    # Cross-cut invariants.
    # 1. A is the source of 1_234 damage; B's series is 0.
    assert sum(p["total_damage"] for p in series_a["points"]) == 1_234
    assert sum(p["total_damage"] for p in series_b["points"]) == 0
    # 2. B is the source of 800 heal; A's series is 0 (source-side
    #    inversion vs the per-target roll-up).
    assert sum(p["total_healing"] for p in series_a["points"]) == 0
    assert sum(p["total_healing"] for p in series_b["points"]) == 800


def test_fight_player_timeline_200_with_empty_series_for_npc_only_fight() -> None:
    """Feature 3A 0-player contract: a 2-NPC fight with events
    returns ``200 OK`` with ``series: []`` -- NOT ``404``.

    The route docstring pins the divergent-empty contract:

      * ``/timeline`` (aggregated) returns 404 on a 0-event fight
        (``events_blob_uri is None`` OR the events list is empty
        after the JSONL split -- "parser ran, nothing happened"
        vs "data unavailable").
      * ``/timeline/players`` (per-player) returns 200 OK with
        ``series: []`` on a fight whose events are all
        NPC-sourced (the blob exists, the parser yielded events,
        but the source-side attribution filter strips every
        event). 0-player is a LEGITIMATE state, not "data
        unavailable".

    Seeds a 2-NPC fight with 1 damage event A→B. The events
    blob is written; the ORM agent table has 0 rows with
    ``is_player=True``. The aggregator's
    ``source_map.get(e.source_agent_id)`` returns ``None`` for
    every event (no player overlay), so ``per_account`` stays
    empty and the route returns ``series: []``.

    The fixture bypasses :func:`_post_minimal_fight` because that
    helper sets ``is_player=True`` on both agents. We inline a
    custom POST so both agents are NPCs.
    """
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    events = [
        _make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
    ]
    # ``is_player=False`` on both agents: NPCs have no
    # ``account_name`` registered in the arcdps account-name
    # stream, so the aggregator drops them at the source-side
    # attribution filter. The ``agents=`` kwarg on the helper
    # DRYs the otherwise-needed 14-line inline POST.
    fight_id = _post_minimal_fight(
        events,
        suffix=suffix,
        agents=[
            (base_id_a, 0, 0, f"NPC Alpha {suffix}", False),
            (base_id_b, 0, 0, f"NPC Beta {suffix}", False),
        ],
    )

    # 200 OK with all events filtered out at the source-side step.
    # ``duration_s`` is non-zero (the 1 event at t=1.5s sets
    # ``max(event.time_ms) / 1000.0 = 1.5``) so the parser WROTE
    # the events blob; the blob is present, but the per-player
    # series is empty because the events' source_agent_ids all
    # map to NPCs (no player overlay).
    resp = client.get(f"/api/v1/fights/{fight_id}/timeline/players")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["fight_id"] == fight_id
    assert payload["duration_s"] == pytest.approx(1.5)
    assert payload["series"] == []


def test_fight_player_timeline_404_when_unknown_fight() -> None:
    """Feature 3A: ``GET /fights/{unknown}/timeline/players`` returns 404.

    Same 404 contract as the per-fight timeline and the per-target
    roll-ups -- the shared :func:`_load_fight_events` helper raises
    404 when the fight id is unknown. The route inherits the
    contract for free via the helper.
    """
    resp = client.get("/api/v1/fights/does-not-exist-1234/timeline/players")
    assert resp.status_code == 404


def test_fight_player_timeline_422_when_window_s_too_small() -> None:
    """Feature 3A: ``?window_s=0`` returns 422 (FastAPI
    ``Query(ge=1)`` validator fires BEFORE the handler).

    Symmetric counterpart to :func:`test_fight_timeline_422_when_window_s_too_small`
    -- the per-player timeline shares the same ``window_s``
    lower bound (``1``) as the per-fight timeline, the per-target
    roll-ups, and the event-window roll-up. One test per bound
    mirrors the existing convention (per-fight timeline uses 2
    separate tests) so a regression localises cleanly to the upper
    or lower half of the validator.
    """
    resp = client.get(
        "/api/v1/fights/anything/timeline/players",
        params={"window_s": 0},
    )
    assert resp.status_code == 422


def test_fight_player_timeline_422_when_window_s_too_large() -> None:
    """Feature 3A: ``?window_s=601`` returns 422 (FastAPI
    ``Query(le=600)`` validator fires BEFORE the handler).

    Symmetric counterpart to :func:`test_fight_timeline_422_when_window_s_too_large`
    -- the per-player timeline shares the same ``window_s``
    upper bound (``600`` = 10 minutes, the canonical ceiling
    for per-fight bucket roll-ups) as the per-fight timeline,
    the per-target roll-ups, and the event-window roll-up.
    Splitting the upper + lower bound into 2 separate tests
    mirrors the existing convention so a CI log
    ``-k fight_player_timeline_422`` surfaces both failures
    side-by-side.
    """
    resp = client.get(
        "/api/v1/fights/anything/timeline/players",
        params={"window_s": 601},
    )
    assert resp.status_code == 422


def test_background_task_session_alive_at_invocation(
    client: TestClient,
    get_sessionmaker: Any,
) -> None:
    """Regression: process_parse must run with a WORKER-scoped session.

    Pre-plan-006: ``background_tasks.add_task(process_parse, db=db)`` passed
    the request-scoped ``db`` whose generator ``finally`` block fires BEFORE
    FastAPI runs the BG task. ``process_parse`` raised ``DetachedInstanceError``
    on its first query; upload.status never advanced past "queued"; webhook
    dispatch never fired.

    Post-plan-006: ``process_parse(session_factory, upload_id, raw_bytes)``
    opens its own session via ``session_factory()`` (mirrors
    ``dispatch_for_upload``).

    Operator-runs after ``alembic upgrade head`` (0006 + 0007 applied + live
    Postgres reachable). The test SKIPs cleanly when no live DB is reachable.
    """
    try:
        probe = get_sessionmaker()()
        probe.execute(text("SELECT 1"))
        probe.close()
    except Exception as exc:
        pytest.skip(
            f"regression test needs live Postgres; got: "
            f"{exc.__class__.__name__} (operator-runs after "
            f"alembic upgrade)"
        )

    blob = _make_minimal_zevtc(
        agents=[(123456789, 0, 0, "Player.One.1234", True)],
        build="20250925",
    )
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("regression.zevtc", blob, "application/zip")},
    )
    assert resp.status_code == 201, f"upload POST failed: {resp.status_code} {resp.text}"
    upload_id = resp.json()["id"]

    deadline = time.monotonic() + 2.0
    status_value = None
    while time.monotonic() < deadline:
        get_resp = client.get(f"/api/v1/uploads/{upload_id}")
        if get_resp.status_code == 200:
            status_value = get_resp.json().get("status")
            if status_value in ("completed", "failed"):
                break
        time.sleep(0.05)

    assert status_value == "completed", (
        f"BG task left upload in {status_value!r}; expected 'completed'. "
        "If this fails post-plan-006, the session_factory refactor regressed."
    )
