"""Shared test fixtures for the apps/api e2e tests.

The V1.4/2025 EVTC layout (struct pack/unpack) and the synthetic
``.zevtc`` blob builder are ~150 lines of code that all e2e
tests share. This module extracts them so the test files
focus on the test contract (the assertions on the API
response + the DB state) rather than the wire format.
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

# V1.4/2025 EVTC layout (matches libs/gw2_evtc_parser parser.py):
#   24-byte header (magic + 8B build + rev + combat_id + unused
#   + agent_count + map_id)
#   + agent_count x 96-byte agent records
#   + skill_count x fixed 68-byte skill records
#       * legacy (pre-2025): 4-byte count prefix before records
#       * EVTC2025+: records start immediately, no count prefix
#   + N x 64-byte cbtevent records
_HEADER_FMT: Final = "<4s8sBHBII"
_HEADER_SIZE: Final = struct.calcsize(_HEADER_FMT)  # 24

_AGENT_RECORD_FMT: Final = "<QIIhhhh"
_AGENT_PREFIX_SIZE: Final = struct.calcsize(_AGENT_RECORD_FMT)  # 24
_AGENT_NAME_SIZE: Final = 72
_AGENT_SIZE: Final = _AGENT_PREFIX_SIZE + _AGENT_NAME_SIZE  # 96

_AGENT_NAME_SIZE_2025: Final = 64
_AGENT_FMT_2025: Final = f"<IIIIII{_AGENT_NAME_SIZE_2025}sII"

_SKILL_RECORD_SIZE: Final = 68

# Legacy event format (empirically calibrated for pre-2025 builds).
_EVENT_FMT: Final = "<QQQiiIIHHHbbbbbbbbIIbb"
_EVENT_SIZE: Final = struct.calcsize(_EVENT_FMT)  # 64

# EVTC2025+ event format (standard arcdps.h cbtevent layout).
_EVENT_FMT_2025: Final = "<QQQiiIIHHHH16B"
_EVENT_SIZE_2025: Final = struct.calcsize(_EVENT_FMT_2025)  # 64


def _is_evtc2025(build: str) -> bool:
    """Return True for builds dated 2025 or later."""
    if len(build) >= 4 and build[:4].isdigit():
        return int(build[:4]) >= 2025
    return False


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
    is_evtc2025: bool = True,
) -> bytes:
    """Pack one 64-byte cbtevent record matching the parser's struct layout.

    For EVTC2025+ builds the ``result`` byte (offset 50) encodes the
    event class: ``13``/``14`` = heal. For legacy builds the
    ``is_nondamage`` byte is used directly.
    """
    if is_evtc2025:
        flags = bytearray(16)
        # byte 50 (index 2) = result. 13 = CBTR_HEAL, 14 = CBTR_BUFFHEAL.
        flags[2] = 13 if is_nondamage > 0 else 0
        # byte 56 (index 8) = is_statechange.
        flags[8] = is_statechange
        return struct.pack(
            _EVENT_FMT_2025,
            time_ms,
            src,
            dst,
            value,
            buff_dmg,
            0,  # overstack_value
            skill_id,
            0,  # src_instid
            0,  # dst_instid
            0,  # src_master_instid
            0,  # dst_master_instid
            *flags,
        )

    return struct.pack(
        _EVENT_FMT,
        time_ms,
        src,
        dst,
        value,
        buff_dmg,
        0,  # overstack_value
        skill_id,
        0,  # src_instid
        0,  # dst_instid
        0,  # src_master_instid
        0,  # dst_master_instid
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


def _encode_agent(
    aid: int,
    prof: int,
    elite: int,
    name: str,
    is_player: bool,
    *,
    is_2025: bool,
) -> bytes:
    """Encode a single 96-byte agent record."""
    if is_2025:
        account = f":synth.{aid}".encode() if is_player else b""
        raw_name = name.encode() + b"\x00" + account + b"\x00" + b"\x00"
        raw_name = raw_name[:_AGENT_NAME_SIZE_2025]
        name_buf = raw_name + b"\x00" * (_AGENT_NAME_SIZE_2025 - len(raw_name))
        return struct.pack(
            _AGENT_FMT_2025,
            0,  # iid_low (unused)
            prof,
            elite,
            0,  # toughness
            0,  # healing
            0,  # concentration
            name_buf,
            0,  # subgroup
            aid,  # addr (event-matching id for 2025+)
        )

    prefix = struct.pack(_AGENT_RECORD_FMT, aid, prof, elite, 0, 0, 0, 0)
    account = f":synth.{aid}".encode() if is_player else b""
    raw = name.encode() + b"\x00" + account + (b"\x00\x00" if is_player else b"\x00")
    name_buf = raw + b"\x00" * (_AGENT_NAME_SIZE - len(raw))
    return prefix + name_buf


def make_minimal_zevtc(
    agents: list[tuple[int, int, int, str, bool]],
    build: str,
    skills: list[tuple[int, str]] | None = None,
    events: list[bytes] | None = None,
) -> bytes:
    """Build a synthetic ``.zevtc`` blob (zip wrapper around EVTC).

    Supports both legacy (pre-2025) and EVTC2025+ wire formats.
    The build string determines which format is emitted; tests
    currently default to 2025+ builds.
    """
    if skills is None:
        skills = []
    if events is None:
        events = []
    is_2025 = _is_evtc2025(build)

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        header = struct.pack(
            _HEADER_FMT,
            b"EVTC",
            build.encode("ascii"),
            0,  # rev
            0,  # combat_id
            0,  # unused
            len(agents),
            0,  # map_id
        )
        assert len(header) == _HEADER_SIZE
        body = bytearray()

        for aid, prof, elite, name, is_player in agents:
            body += _encode_agent(aid, prof, elite, name, is_player, is_2025=is_2025)

        if not is_2025:
            body += struct.pack("<I", len(skills))

        for skill_id, skill_name in skills:
            name_bytes = skill_name.encode("utf-8")[:64]
            name_buf = name_bytes + b"\x00" * (_SKILL_RECORD_SIZE - 4 - len(name_bytes))
            body += struct.pack("<I64s", skill_id, name_buf)

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
    suffix_digits = f"{int(suffix[:4], 16) % 10000:04d}" if len(suffix) >= 4 else "0925"
    build = f"2025{suffix_digits}"
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
    return wait_for_upload_completion(resp.json()["id"])


def post_npc_only_fight() -> str:
    """POST a fight containing only NPC agents.

    Returns the persisted ``fight_id``. The fixture is used by
    tests that exercise the backfill's "no player agents" skip
    path: the parser marks every agent as ``is_player=False``
    and ``account_name=None``, so ``run_backfill`` should count
    the fight as ``skipped`` and write no summary rows.
    """
    suffix = _uuid.uuid4().hex[:8]
    suffix_digits = f"{int(suffix[:4], 16) % 10000:04d}" if len(suffix) >= 4 else "0925"
    build = f"2025{suffix_digits}"
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
    return wait_for_upload_completion(resp.json()["id"])


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
