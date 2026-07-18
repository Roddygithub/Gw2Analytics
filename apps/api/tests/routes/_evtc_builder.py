"""Shared EVTC binary builder for route-level test helpers."""

from __future__ import annotations

import struct
import time
import zipfile
from io import BytesIO

from fastapi.testclient import TestClient

_HEADER_FMT = "<4s8sBHBI I"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_AGENT_RECORD_FMT = "<QIIhhhh"
_AGENT_PREFIX_SIZE = struct.calcsize(_AGENT_RECORD_FMT)
_AGENT_NAME_SIZE = 72
_SKILL_HEADER_FMT = "<II"
_SKILL_HEADER_SIZE = struct.calcsize(_SKILL_HEADER_FMT)
_EVENT_FMT = "<QQQiiIIHHHbbbbbbbbIIbb"
_EVENT_SIZE = struct.calcsize(_EVENT_FMT)


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
            prefix = struct.pack(_AGENT_RECORD_FMT, aid, prof, elite, 0, 0, 0, 0)
            account = f":synth.{aid}".encode() if is_player else b""
            raw = name.encode() + b"\x00" + account + (b"\x00\x00" if is_player else b"\x00")
            name_buf = raw + b"\x00" * (_AGENT_NAME_SIZE - len(raw))
            body += prefix + name_buf
        for skill_id, skill_name in skills:
            n = skill_name.encode("utf-8")
            body += struct.pack(_SKILL_HEADER_FMT, skill_id, len(n)) + n + b"\x00"
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
