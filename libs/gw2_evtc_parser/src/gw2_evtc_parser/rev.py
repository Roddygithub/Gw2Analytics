"""Revision-aware EVTC helpers (v0.10.5 plan 138).

This module exposes low-level helpers that understand the difference
between arcdps EVTC revision 0 and revision >= 1:

* :class:`HeaderInfo` + :func:`decode_header` return the revision and
the header size so callers can branch cleanly.
* :func:`decode_event_rev0` and :func:`decode_event_rev1` decode a
single 64-byte cbtevent record into the same tuple shape.
* :func:`pre_scan_spawn` walks the event stream once and builds a map
of ``src_instid -> src_agent`` for SPAWN statechange records.

The helpers are intentionally low-level and stateless. They do not
replace :class:`PythonEvtcParser`; they live alongside it for code that
needs to reason about EVTC revisions explicitly.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Final

from gw2_evtc_parser.exceptions import EvtcParseError

#: arcdps statechange kind for agent spawn events.
#: Value 3 is the canonical ``CBTS_SPAWN`` / ``STATE_CHANGE_SPAWN``.
STATE_CHANGE_SPAWN: Final[int] = 3

#: Size of a cbtevent record on disk (both rev0 and rev1).
EVENT_RECORD_SIZE: Final[int] = 64


@dataclass(frozen=True)
class HeaderInfo:
    """Decoded EVTC file header.

    ``header_size`` follows the reference implementation convention:
    20 bytes for rev0, 24 bytes for rev >= 1. ``map_id`` is only
    present when ``revision >= 1``.
    """

    build: str
    revision: int
    combat_id: int
    agent_count: int
    skill_count: int
    map_id: int | None
    header_size: int


def decode_header(data: bytes) -> HeaderInfo:
    """Decode the EVTC file header from the first bytes of a log.

    Supports the reference 20-byte (rev0) and 24-byte (rev1) header
    layouts, plus extended layouts that carry ``skill_count`` after
    ``map_id``. Raises :class:`EvtcParseError` for bad magic or
    non-ASCII build bytes.

    Layout (common prefix, 20 bytes):
        magic(4) + build(8) + revision(1) + combat_id(2) + unused(1)
        + agent_count(4)

    Extended rev0 (24 bytes):
        + skill_count(4)

    Extended rev1 (24+ bytes):
        + map_id(4)
        + [skill_count(4)]
    """
    if len(data) < 20:
        raise EvtcParseError(f"EVTC header needs at least 20 bytes, got {len(data)}")

    magic = data[0:4]
    if magic != b"EVTC":
        raise EvtcParseError(f"Bad magic bytes: {magic!r} (expected b'EVTC')")

    try:
        build = data[4:12].decode("ascii")
    except UnicodeDecodeError as exc:
        raise EvtcParseError(f"Build bytes are not pure ASCII: {data[4:12]!r}") from exc

    revision = data[12]
    combat_id = struct.unpack_from("<H", data, 13)[0]
    agent_count = struct.unpack_from("<I", data, 16)[0]

    map_id: int | None = None
    skill_count = 0
    header_size = 20

    if revision >= 1:
        header_size = 24
        if len(data) >= 24:
            map_id = struct.unpack_from("<I", data, 20)[0]
        if len(data) >= 28:
            skill_count = struct.unpack_from("<I", data, 24)[0]
    elif len(data) >= 24:
        skill_count = struct.unpack_from("<I", data, 20)[0]
        header_size = 24

    return HeaderInfo(
        build=build,
        revision=revision,
        combat_id=combat_id,
        agent_count=agent_count,
        skill_count=skill_count,
        map_id=map_id,
        header_size=header_size,
    )


#: struct for a rev1 64-byte cbtevent record.
#: Layout: time(Q) src_agent(Q) dst_agent(Q) value(i) buff_dmg(i)
#: overstack_value(I) skillid(I) src_instid(H) dst_instid(H)
#: translocated(H) is_cleanup(b) is_nondamage(b) is_statechange(b)
#: is_flanking(b) is_shields(b) is_offcycle(b) pad61(b) pad62(b)
#: pad63(I) pad64(I) pad65(b) pad66(b)
_REV1_EVENT_STRUCT = struct.Struct("<QQQiiIIHHHbbbbbbbbIIbb")

#: struct for a rev0 64-byte cbtevent record.
#: Layout: time(q) src_agent(q) dst_agent(q) value(i) buff_dmg(i)
#: packed_skill(I) src_instid(H) dst_instid(H) translocated(H)
#: extra(H) 13B flags 7x padding.
_REV0_EVENT_STRUCT = struct.Struct("<qqqiiIHHHH13B7x")


def decode_event_rev1(data: bytes, offset: int) -> tuple[object, ...]:
    """Decode a single rev1 cbtevent record.

    Returns the same tuple that ``_EVENT_STRUCT.unpack_from`` would
    return. This is a thin wrapper for symmetry with
    :func:`decode_event_rev0`.
    """
    return _REV1_EVENT_STRUCT.unpack_from(data, offset)


def decode_event_rev0(data: bytes, offset: int) -> tuple[object, ...]:
    """Decode a single rev0 cbtevent record.

    The rev0 layout packs ``overstack_value`` and ``skillid`` into a
    single 32-bit integer (``packed_skill``). This function expands
    that packed field and returns a tuple with the same field order as
    :func:`decode_event_rev1`.
    """
    vals = _REV0_EVENT_STRUCT.unpack_from(data, offset)
    (
        time_ms,
        src_agent,
        dst_agent,
        value,
        buff_dmg,
        packed_skill,
        src_instid,
        dst_instid,
        translocated,
        _extra_h,
        *flags,  # 13 bytes
    ) = vals

    overstack_value = packed_skill & 0xFFFF
    skill_id = (packed_skill >> 16) & 0xFFFF

    # flags are the 13 bytes starting at offset 44 in the record.
    # is_cleanup, is_nondamage, is_statechange, is_flanking,
    # is_shields, is_offcycle, pad61, pad62, then 5 more bytes that
    # the rev1 layout keeps as pad63/pad64/pad65/pad66. We mirror the
    # rev1 tuple shape by mapping the first 8 flag bytes to the same
    # positions and leaving the remaining 5 bytes as zeros.
    flag_iter = iter(flags)
    is_cleanup = next(flag_iter)
    is_nondamage = next(flag_iter)
    is_statechange = next(flag_iter)
    is_flanking = next(flag_iter)
    is_shields = next(flag_iter)
    is_offcycle = next(flag_iter)
    pad61 = next(flag_iter)
    pad62 = next(flag_iter)
    # The remaining 5 bytes are not used by rev1; pad with zeros.
    pad63 = 0
    pad64 = 0
    pad65 = 0
    pad66 = 0

    return (
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
        pad61,
        pad62,
        pad63,
        pad64,
        pad65,
        pad66,
    )


def pre_scan_spawn(data: bytes, event_offset: int, revision: int) -> dict[int, int]:
    """Walk the event stream once and collect SPAWN instid -> agent maps.

    Parameters
    ----------
    data:
        Full EVTC byte blob.
    event_offset:
        Byte offset where the cbtevent stream starts.
    revision:
        EVTC revision (0 or >= 1). Determines which byte holds
        ``is_statechange`` and where ``src_instid`` lives.

    Returns
    -------
    Mapping from ``src_instid`` to ``src_agent`` for every SPAWN
    statechange record found in the event stream.
    """
    tag_map: dict[int, int] = {}
    end = len(data)
    cursor = event_offset

    # Offsets are relative to the start of each 64-byte record.
    if revision >= 1:
        # rev1: is_statechange at byte 48, src_instid (H) at byte 40.
        statechange_off = 48
        src_instid_off = 40
    else:
        # rev0: is_statechange at byte 46 (flags[2] of the 13-byte block
        # starting at byte 44), src_instid (H) at byte 36.
        statechange_off = 46
        src_instid_off = 36

    if event_offset < 0 or event_offset > end:
        raise ValueError("event_offset must be within data bounds")

    while cursor + EVENT_RECORD_SIZE <= end:
        is_statechange = data[cursor + statechange_off]
        if is_statechange == STATE_CHANGE_SPAWN:
            src_agent = struct.unpack_from("<Q", data, cursor + 8)[0]
            src_instid = struct.unpack_from("<H", data, cursor + src_instid_off)[0]
            tag_map[src_instid] = src_agent
        cursor += EVENT_RECORD_SIZE

    return tag_map


__all__ = [
    "EVENT_RECORD_SIZE",
    "STATE_CHANGE_SPAWN",
    "HeaderInfo",
    "decode_event_rev0",
    "decode_event_rev1",
    "decode_header",
    "pre_scan_spawn",
]
