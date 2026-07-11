"""Hermetic tests for :mod:`gw2_evtc_parser.rev` (v0.10.5 plan 138).

All fixtures are synthetic byte arrays so the tests do not depend on
disk artefacts or real arcdps logs.
"""

from __future__ import annotations

import struct

import pytest

from gw2_evtc_parser.exceptions import EvtcParseError
from gw2_evtc_parser.rev import (
    STATE_CHANGE_SPAWN,
    HeaderInfo,
    decode_event_rev0,
    decode_event_rev1,
    decode_header,
    pre_scan_spawn,
)

# ---------------------------------------------------------------------------
# Header decoding
# ---------------------------------------------------------------------------


def _build_header(
    *,
    build: bytes = b"20250925",
    revision: int = 1,
    combat_id: int = 0xBEEF,
    agent_count: int = 2,
    skill_count: int | None = 3,
    map_id: int = 0x12345678,
) -> bytes:
    """Build a synthetic EVTC header.

    For ``revision >= 1`` the header is 24 bytes (reference rev1 layout
    with map_id) or 28 bytes when ``skill_count`` is also supplied.
    For ``revision == 0`` the header is 20 bytes by default, or 24
    bytes when ``skill_count`` is supplied.
    """
    header = struct.pack(
        "<4s8sBHBI",
        b"EVTC",
        build,
        revision,
        combat_id,
        0,  # unused
        agent_count,
    )
    if revision >= 1:
        # Reference rev1: map_id at offset 20, optional skill_count at 24.
        if skill_count is None:
            header += struct.pack("<I", map_id)
        else:
            header += struct.pack("<II", map_id, skill_count)
    elif skill_count is not None:
        # Extended rev0: skill_count at offset 20.
        header += struct.pack("<I", skill_count)
    return header


def test_decode_header_rev1() -> None:
    """Plan 138 spec test 1: rev1 header exposes map_id and header_size=24."""
    data = _build_header(revision=1, map_id=0xDEADBEEF)
    info = decode_header(data)
    assert info == HeaderInfo(
        build="20250925",
        revision=1,
        combat_id=0xBEEF,
        agent_count=2,
        skill_count=3,
        map_id=0xDEADBEEF,
        header_size=24,
    )


def test_decode_header_rev0() -> None:
    """Plan 138 spec test 2: rev0 header has no map_id and header_size=20."""
    data = _build_header(revision=0, skill_count=None)
    info = decode_header(data)
    assert info == HeaderInfo(
        build="20250925",
        revision=0,
        combat_id=0xBEEF,
        agent_count=2,
        skill_count=0,
        map_id=None,
        header_size=20,
    )


def test_decode_header_rejects_bad_magic() -> None:
    with pytest.raises(EvtcParseError, match="Bad magic"):
        decode_header(b"JUNK" + b"\x00" * 20)


def test_decode_header_rejects_truncated_data() -> None:
    with pytest.raises(EvtcParseError, match="header needs"):
        decode_header(b"EVTC" + b"\x00" * 10)


# ---------------------------------------------------------------------------
# Event decoding
# ---------------------------------------------------------------------------


def _build_rev1_event(
    *,
    time_ms: int = 1_000,
    src_agent: int = 42,
    dst_agent: int = 99,
    value: int = 1_337,
    buff_dmg: int = 0,
    overstack_value: int = 0,
    skill_id: int = 101,
    src_instid: int = 7,
    dst_instid: int = 8,
    translocated: int = 0,
    is_cleanup: int = 0,
    is_nondamage: int = 0,
    is_statechange: int = 0,
    is_flanking: int = 0,
    is_shields: int = 0,
    is_offcycle: int = 0,
) -> bytes:
    """Build a 64-byte rev1 cbtevent record."""
    return struct.pack(
        "<QQQiiIIHHHbbbbbbbbIIbb",
        time_ms,
        src_agent,
        dst_agent,
        value,
        buff_dmg,
        overstack_value,
        skill_id,
        src_instid,
        dst_instid,
        translocated,
        is_cleanup,
        is_nondamage,
        is_statechange,
        is_flanking,
        is_shields,
        is_offcycle,
        0,  # pad61
        0,  # pad62
        0,  # pad63
        0,  # pad64
        0,  # pad65
        0,  # pad66
    )


def _build_rev0_event(
    *,
    time_ms: int = 1_000,
    src_agent: int = 42,
    dst_agent: int = 99,
    value: int = 1_337,
    buff_dmg: int = 0,
    overstack_value: int = 0,
    skill_id: int = 101,
    src_instid: int = 7,
    dst_instid: int = 8,
    translocated: int = 0,
    extra_h: int = 0,
    is_cleanup: int = 0,
    is_nondamage: int = 0,
    is_statechange: int = 0,
    is_flanking: int = 0,
    is_shields: int = 0,
    is_offcycle: int = 0,
) -> bytes:
    """Build a 64-byte rev0 cbtevent record.

    The rev0 layout packs ``overstack_value`` (low 16 bits) and
    ``skill_id`` (high 16 bits) into a single 32-bit integer.
    """
    packed_skill = (overstack_value & 0xFFFF) | ((skill_id & 0xFFFF) << 16)
    return struct.pack(
        "<qqqiiIHHHH13B7x",
        time_ms,
        src_agent,
        dst_agent,
        value,
        buff_dmg,
        packed_skill,
        src_instid,
        dst_instid,
        translocated,
        extra_h,
        is_cleanup,
        is_nondamage,
        is_statechange,
        is_flanking,
        is_shields,
        is_offcycle,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )


def test_decode_event_rev1() -> None:
    """Plan 138 spec test 3: rev1 event decodes to the expected tuple."""
    data = _build_rev1_event(
        time_ms=2_000,
        src_agent=11,
        dst_agent=22,
        value=555,
        buff_dmg=777,
        overstack_value=12,
        skill_id=303,
        src_instid=5,
        dst_instid=6,
        is_statechange=1,
    )
    tup = decode_event_rev1(data, 0)
    assert tup[0] == 2_000  # time_ms
    assert tup[1] == 11  # src_agent
    assert tup[2] == 22  # dst_agent
    assert tup[3] == 555  # value
    assert tup[4] == 777  # buff_dmg
    assert tup[5] == 12  # overstack_value
    assert tup[6] == 303  # skill_id
    assert tup[7] == 5  # src_instid
    assert tup[8] == 6  # dst_instid
    assert tup[10] == 0  # is_cleanup
    assert tup[11] == 0  # is_nondamage
    assert tup[12] == 1  # is_statechange


def test_decode_event_rev0() -> None:
    """Plan 138 spec test 4: rev0 event decodes and expands packed skill_id."""
    data = _build_rev0_event(
        time_ms=3_000,
        src_agent=111,
        dst_agent=222,
        value=999,
        buff_dmg=111,
        overstack_value=44,
        skill_id=505,
        src_instid=9,
        dst_instid=10,
        is_statechange=2,
    )
    tup = decode_event_rev0(data, 0)
    assert tup[0] == 3_000
    assert tup[1] == 111
    assert tup[2] == 222
    assert tup[3] == 999
    assert tup[4] == 111
    assert tup[5] == 44  # overstack_value recovered from packed_skill
    assert tup[6] == 505  # skill_id recovered from packed_skill
    assert tup[7] == 9  # src_instid
    assert tup[8] == 10  # dst_instid
    assert tup[10] == 0  # is_cleanup
    assert tup[11] == 0  # is_nondamage
    assert tup[12] == 2  # is_statechange


def test_decode_event_rev0_and_rev1_same_shape() -> None:
    """Both decoders return tuples of the same length."""
    rev1_data = _build_rev1_event()
    rev0_data = _build_rev0_event()
    rev1_tuple = decode_event_rev1(rev1_data, 0)
    rev0_tuple = decode_event_rev0(rev0_data, 0)
    assert len(rev1_tuple) == len(rev0_tuple)


# ---------------------------------------------------------------------------
# SPAWN pre-scan
# ---------------------------------------------------------------------------


def test_pre_scan_spawn_finds_spawn_record() -> None:
    """Plan 138 spec test 5: pre-scan extracts instid -> agent for SPAWN."""
    # Two rev1 event records; the second is a SPAWN.
    record1 = _build_rev1_event(time_ms=1_000, src_agent=1, src_instid=1)
    record2 = _build_rev1_event(
        time_ms=2_000,
        src_agent=0xDEADBEEF,
        src_instid=0x1234,
        is_statechange=STATE_CHANGE_SPAWN,
    )
    data = record1 + record2
    event_offset = 0
    result = pre_scan_spawn(data, event_offset, revision=1)
    assert result == {0x1234: 0xDEADBEEF}


def test_pre_scan_spawn_rev0() -> None:
    """Pre-scan works for rev0 event layout too."""
    record1 = _build_rev0_event(time_ms=1_000, src_agent=1, src_instid=1)
    record2 = _build_rev0_event(
        time_ms=2_000,
        src_agent=0xCAFEBABE,
        src_instid=0x5678,
        is_statechange=STATE_CHANGE_SPAWN,
    )
    data = record1 + record2
    result = pre_scan_spawn(data, 0, revision=0)
    assert result == {0x5678: 0xCAFEBABE}


def test_pre_scan_spawn_ignores_non_spawn_statechanges() -> None:
    """Only STATE_CHANGE_SPAWN records populate the map."""
    record = _build_rev1_event(
        time_ms=1_000,
        src_agent=0xDEADBEEF,
        src_instid=0x1234,
        is_statechange=STATE_CHANGE_SPAWN + 1,
    )
    result = pre_scan_spawn(record, 0, revision=1)
    assert result == {}


def test_pre_scan_spawn_handles_empty_event_stream() -> None:
    assert pre_scan_spawn(b"", 0, revision=1) == {}
