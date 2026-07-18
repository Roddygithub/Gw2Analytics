"""Shared test fixtures for the apps/api e2e tests.

The V1.3 EVTC layout (struct pack/unpack) and the synthetic
``.zevtc`` blob builder are ~150 lines of code that all e2e
tests share. This module extracts them so the test files
focus on the test contract (the assertions on the API
response + the DB state) rather than the wire format.

v0.8.5 bring-up: extracted from :mod:`tests.test_uploads_e2e`
to support :mod:`tests.test_backfill` (the v0.8.5 backfill
script's e2e tests). The struct layout + the ZIP builder
are byte-identical to the v0.7.0+ tests; the only difference
is the location (this module vs inline in the test file).
"""

from __future__ import annotations

import struct
import time
import uuid as _uuid
import zipfile
from io import BytesIO
from typing import Final

from fastapi.testclient import TestClient

from gw2analytics_api.main import app

client: Final = TestClient(app)

# V1.3 EVTC layout (matches libs/gw2_evtc_parser parser.py):
#   24-byte header (magic + 8B build + rev + combat + unused
#                   + agent_count + map_id)
#   + 4-byte skill_count (at bytes 24-27)
#   + agent_count x 96-byte agent records
#   + skill_count x variable-size skill records
#   + N x 64-byte cbtevent records (Phase 7 v1)
_HEADER_FMT: Final = "<4s8sBHBI I"
_HEADER_SIZE: Final = struct.calcsize(_HEADER_FMT)  # 24
_AGENT_RECORD_FMT: Final = "<QIIhhhh"
_AGENT_PREFIX_SIZE: Final = struct.calcsize(_AGENT_RECORD_FMT)  # 24
_AGENT_NAME_SIZE: Final = 72
_AGENT_SIZE: Final = _AGENT_PREFIX_SIZE + _AGENT_NAME_SIZE  # 96
_SKILL_HEADER_FMT: Final = "<II"
_SKILL_HEADER_SIZE: Final = struct.calcsize(_SKILL_HEADER_FMT)  # 8
_EVENT_FMT: Final = "<QQQiiIIHHHbbbbbbbbIIbb"
_EVENT_SIZE: Final = struct.calcsize(_EVENT_FMT)  # 64


def make_cbtevent(
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

    Field padding (``pad61..pad66``) is set to zero -- the parser does
    not read them. ``value > 0`` + ``is_statechange == 0`` +
    ``is_nondamage == 0`` produces a yielded ``DamageEvent``.

    Phase 8: ``buff_dmg`` is the ``int32`` arcdps field that surfaces
    a separate ``BuffRemovalEvent`` from the heal-class event kind.
    Set to > 0 on a record with ``is_nondamage == 1`` to exercise
    the same-record dual-emit (heal + strip) or the pure-strip (no
    heal) case.
    """
    return struct.pack(
        _EVENT_FMT,
        time_ms,
        src,
        dst,
        value,
        buff_dmg,
        0,
        skill_id,
        0,
        0,
        0,
        0,
        is_nondamage,
        is_statechange,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )[:_EVENT_SIZE]


def make_minimal_zevtc(
    agents: list[tuple[int, int, int, str, bool]],
    build: str,
    skills: list[tuple[int, str]] | None = None,
    events: list[bytes] | None = None,
) -> bytes:
    """Build a synthetic ``.zevtc`` blob (zip wrapper around EVTC).

    Uses the V1.3 24-byte header + 96-byte agent records +
    variable skill records. For player agents the combo string
    ``name\\0:synth.<id>\\0`` is null-padded to 72 bytes; NPCs
    get a single null-terminated name null-padded to 72 bytes.
    Skill records are ``<II`` (skill_id + name_len) + UTF-8
    name + 1 byte null.

    ``events`` is an optional list of pre-packed 64-byte
    cbtevent records appended verbatim after the skill block.
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
            0,  # map_id
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
            body += ev
        zf.writestr("fight.evtc", header + bytes(body))
    return buf.getvalue()


def post_minimal_fight(
    events: list[bytes] | None = None,
    suffix: str | None = None,
) -> str:
    """POST a minimal 2-player fight with optional cbtevent records.

    Returns the persisted ``fight_id``. The fixture mirrors the
    happy-path's 2-player layout (Warrior A + Guardian B, both
    with empty subgroup) so the per-subgroup roll-up has exactly
    1 row in the empty-string bucket.

    ``suffix`` lets callers thread their own uuid-derived suffix
    through the helper so the agent + skill IDs in the cbtevent
    records match the IDs the parser writes into the agent
    table. Without this, the route's source-side attribution
    silently drops the events (``local_agents.get(
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
    blob = make_minimal_zevtc(
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
    return wait_for_upload_completion(upload_id)


def post_npc_only_fight() -> str:
    """POST a fight containing only NPC agents.

    Returns the persisted ``fight_id``. The fixture is used by
    tests that exercise the backfill's "no player agents" skip
    path: the parser marks every agent as ``is_player=False``
    and ``account_name=None``, so ``run_backfill`` should count
    the fight as ``skipped`` and write no summary rows.
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    blob = make_minimal_zevtc(
        [
            (base_id_a, 99, 99, f"NPC Mob A {suffix}", False),
            (base_id_b, 99, 99, f"NPC Mob B {suffix}", False),
        ],
        build=build,
    )
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("npc_only.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]
    return wait_for_upload_completion(upload_id)


def wait_for_upload_completion(upload_id: str) -> str:
    """Poll the upload status until the background parser flips
    ``status`` to ``"completed"``, then return the persisted
    ``fight_id``.

    The POST handler spawns :func:`process_parse` via FastAPI's
    ``BackgroundTasks``, so the upload is still ``"pending"``
    immediately after the POST. Downstream tests depend on the
    events blob being written (the ``/players`` + ``/squads`` +
    ``/skills`` routes read it), so the wait is mandatory. A
    5s ceiling is generous: the parser completes in
    milliseconds for a fixture-sized blob.

    A small post-completion ``time.sleep(0.1)`` gives the
    parser a chance to write the events blob before the
    downstream tests query it; the BackgroundTasks runner
    fires after the POST response is sent, so the first poll
    iteration may race the task startup.
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
