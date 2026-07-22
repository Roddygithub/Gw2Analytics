"""Shared EVTC test fixtures: synthetic .zevtc builder helpers.

Extracted from ``test_uploads_e2e.py`` so ``test_players.py`` and
``test_fight_rollup_cap.py`` can import ``_make_cbtevent`` and
``_make_minimal_zevtc`` without duplicating the struct definitions.
"""

from __future__ import annotations

import struct
import zipfile
from io import BytesIO

# V1.3 EVTC layout (matches libs/gw2_evtc_parser parser.py).
_HEADER_FMT = "<4s8sBHBII"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 24
_AGENT_RECORD_FMT = "<QIIhhhh"
_AGENT_PREFIX_SIZE = struct.calcsize(_AGENT_RECORD_FMT)  # 24
_AGENT_NAME_SIZE = 72
_AGENT_SIZE = _AGENT_PREFIX_SIZE + _AGENT_NAME_SIZE  # 96
_SKILL_RECORD_SIZE = 68  # skill_id(u32) + name(64s)
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

    ``value > 0`` + ``is_statechange == 0`` + ``is_nondamage == 0``
    produces a yielded ``DamageEvent``. ``buff_dmg`` exercises the
    same-record dual-emit (heal + strip) or the pure-strip case.
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
        0,
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
    ``name\\0:synth.<id>\\0`` is null-padded to 72 bytes; NPCs get a
    single null-terminated name null-padded to 72 bytes. Skill records
    are ``<II`` (skill_id + name_len) + UTF-8 name + 1 byte null.

    ``events`` is an optional list of pre-packed 64-byte cbtevent
    records appended verbatim after the skill block.
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
        body += struct.pack("<I", len(skills))
        for skill_id, skill_name in skills:
            name_bytes = skill_name.encode("utf-8")[:64]
            name_buf = name_bytes + b"\x00" * (_SKILL_RECORD_SIZE - 4 - len(name_bytes))
            body += struct.pack("<I64s", skill_id, name_buf)
        for ev in events:
            body += ev
        zf.writestr("fight.evtc", header + bytes(body))
    return buf.getvalue()


# Public alias (no underscore prefix) so the 15+ test files that
# import ``from _fixtures import make_minimal_zevtc`` (rather than
# the ``_make_minimal_zevtc`` form) continue to work.
make_minimal_zevtc = _make_minimal_zevtc
