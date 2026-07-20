"""Shared EVTC binary builder for route-level test helpers."""

from __future__ import annotations

import struct
import time
import zipfile
from io import BytesIO

from fastapi.testclient import TestClient

_HEADER_FMT = "<4s8sBHBII"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 24

_AGENT_RECORD_FMT = "<QIIhhhh"
_AGENT_PREFIX_SIZE = struct.calcsize(_AGENT_RECORD_FMT)
_AGENT_NAME_SIZE = 72
_AGENT_SIZE = _AGENT_PREFIX_SIZE + _AGENT_NAME_SIZE  # 96

_AGENT_NAME_SIZE_2025 = 64
_AGENT_FMT_2025 = f"<IIIIII{_AGENT_NAME_SIZE_2025}sII"

_SKILL_RECORD_SIZE = 68

# Legacy event format (empirically calibrated for pre-2025 builds).
_EVENT_FMT = "<QQQiiIIHHHbbbbbbbbIIbb"
_EVENT_SIZE = struct.calcsize(_EVENT_FMT)

# EVTC2025+ event format (standard arcdps.h cbtevent layout).
_EVENT_FMT_2025 = "<QQQiiIIHHHH16B"
_EVENT_SIZE_2025 = struct.calcsize(_EVENT_FMT_2025)


def _is_evtc2025(build: str) -> bool:
    """Return True for builds dated 2025 or later."""
    if len(build) >= 4 and build[:4].isdigit():
        return int(build[:4]) >= 2025
    return False


def build_2025_string(suffix: str | None = None) -> str:
    """Return a numeric EVTC2025+ build string from an optional hex suffix.

    Real arcdps build strings are exactly 8 ASCII digits (yyyymmdd).
    Test helpers often derive a suffix from ``uuid.uuid4().hex[:8]``,
    which is hexadecimal and may contain letters. This helper converts
    the first 4 hex characters of ``suffix`` into a 4-digit decimal
    string so the parser's ``_build_version_from_build_str`` recognises
    the build as 2025+.

    If ``suffix`` is empty or too short, falls back to ``"0925"`` so
    the resulting string is still 8 digits long.
    """
    digits = (
        f"{int(suffix[:4], 16) % 10000:04d}" if suffix and len(suffix) >= 4 else "0925"
    )
    return f"2025{digits}"


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
            0,
            0,
            0,
            len(agents),
            0,
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


def post_upload(client: TestClient, blob: bytes) -> str:
    """POST a .zevtc blob, assert 201, wait for completion, return fight_id."""
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201
    upload_id = resp.json()["id"]
    for _ in range(50):
        r = client.get(f"/api/v1/uploads/{upload_id}")
        if r.status_code == 200 and r.json()["status"] == "completed":
            time.sleep(0.1)
            return str(r.json()["fight_id"])
        time.sleep(0.1)
    raise AssertionError(f"upload {upload_id} never completed")
