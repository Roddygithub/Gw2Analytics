"""Tests for the Python EVTC parser implementation.

Strategy
========

1. **Synthetic fixture** (always runs) — build a minimal valid EVTC blob
   in-memory using :pymod:`struct` + :pymod:`zipfile` so we are not
   dependent on disk artefacts.

2. **Real-file integration** (skipped if no fixture available) — parse
   ``/tmp/inner_20251002-213519`` (a real extraction produced by an
   earlier diagnostic). This guards against the synthetic fixture being
   too clean.

The agent-record layout is the C ``struct ag`` from ``arcdps.h``:
96 bytes total — 28-byte fixed prefix (id + prof + elite + 6 uint16s)
followed by a 68-byte name buffer that arcdps writes as a null-padded
combo string ``"char_name\\0:account_name\\0subgroup\\0"`` for player
agents or a single null-terminated string for NPCs.

The skill table (V1.3+) is a sequence of fixed-size 68-byte records:
``skill_id(u32)`` followed by a 64-byte null-padded UTF-8 name buffer.
Legacy (<2025) files prefix the table with a u32 ``skill_count``; the
parser detects this prefix and reads exactly ``skill_count`` records.
EVTC2025+ files omit the count and the parser walks fixed-size records
until it reaches the event stream or the end of data. The parser is
**lenient**: if data runs out mid-record it stops early and logs a
warning.
"""

from __future__ import annotations

import hashlib
import struct
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

# v0.10.5 audit R2.3: hoist `import gw2_evtc_parser.parser as parser_mod`
# to the top of the file (PLC0415 compliance for the 7 monkeypatch tests
# below that target `parser_mod.MAX_EVTC_BYTES`).
import gw2_evtc_parser.parser as parser_mod
from gw2_core import BuffRemovalEvent, DamageEvent, EliteSpec, HealingEvent, Profession
from gw2_evtc_parser import EvtcParseError, PythonEvtcParser, read_zevtc_bytes
from gw2_evtc_parser.parser import (
    AGENT_COUNT_OFFSET,
    AGENT_NAME_SIZE,
    AGENT_PREFIX_SIZE,
    AGENT_SIZE,
    AGENTS_OFFSET,
    EVENT_SIZE,
    HEADER_SIZE,
    MAX_EVTC_BYTES,
    SKILL_COUNT_OFFSET,
    SKILL_RECORD_SIZE,
    _iter_skill_records,
)

# v0.10.5 audit R2.3: hoist `import gw2_evtc_parser.parser as parser_mod`
# to the top of the file (PLC0415 compliance for the 7 monkeypatch tests
# below that target `parser_mod.MAX_EVTC_BYTES`).


# ---------------------------------------------------------------------------
# Synthetic fixture
# ---------------------------------------------------------------------------


def _build_agent_record(
    agent_id: int,
    prof: int,
    elite: int,
    name: str,
    *,
    account_name: str | None = None,
    subgroup: str | None = None,
) -> bytes:
    """Build one 96-byte V1.2 agent record.

    The 72-byte name buffer is filled with the combo string
    (player) or single name (NPC) null-padded to 72 bytes. arcdps
    fills the full buffer unconditionally, so we mirror that.
    """
    prefix = struct.pack(
        "<QIIhhhh",
        agent_id,
        prof,
        elite,
        0,  # toughness
        0,  # concentration
        0,  # healing
        0,  # hitbox_width
    )
    if account_name is None:
        # NPC: single null-terminated string, null-padded to 72 bytes.
        raw = name.encode("utf-8") + b"\x00"
    else:
        # Player. Combo string ``name\0account\0sub\0``. We DELIBERATELY
        # do not enforce the ``:`` prefix on account_name here: real arcdps
        # revisions emit unprefixed accounts (see
        # test_account_name_without_colon_is_accepted_as_player) and the
        # parser's leniency class accepts them. Prefix enforcement belongs
        # at the parser layer, not at the test fixture layer.
        raw = name.encode("utf-8") + b"\x00" + account_name.encode("utf-8") + b"\x00"
        if subgroup is not None:
            raw += subgroup.encode("utf-8") + b"\x00"
        else:
            raw += b"\x00"
    if len(raw) > AGENT_NAME_SIZE:
        msg = f"name region {len(raw)} bytes exceeds {AGENT_NAME_SIZE}"
        raise ValueError(msg)
    # Null-pad to exactly 72 bytes.
    name_buf = raw + b"\x00" * (AGENT_NAME_SIZE - len(raw))
    assert len(name_buf) == AGENT_NAME_SIZE
    return prefix + name_buf


def _build_skill_record(skill_id: int, name: str) -> bytes:
    """Build one fixed-size 68-byte skill record.

    Layout: skill_id(u32) + name(64-byte null-padded UTF-8 buffer).
    """
    name_bytes = name.encode("utf-8")
    if len(name_bytes) > 64:
        name_bytes = name_bytes[:64]
    name_buf = name_bytes.ljust(64, b"\x00")
    return struct.pack("<I", skill_id) + name_buf


def _build_event_record(
    time_ms: int,
    src_agent: int,
    dst_agent: int,
    value: int,
    skill_id: int = 42,
    *,
    is_statechange: int = 0,
    is_nondamage: int = 0,
    is_cleanup: int = 0,
    is_offcycle: int = 0,
    buff_dmg: int = 0,
) -> bytes:
    """Build one 64-byte cbtevent record matching the arcdps ``cbtevent`` struct.

    Layout (per ``arcdps.h``):
    ``<QQQiiIIHHHbbbbbbbbIIbb`` -- ``time``, ``src_agent``,
    ``dst_agent``, ``value``, ``buff_dmg``, ``overstack_value``,
    ``skillid``, ``src_instid``, ``dst_instid``, ``translocated``,
    ``is_cleanup``, ``is_nondamage``, ``is_statechange``,
    ``is_flanking``, ``is_shields``, ``is_offcycle``, ``pad61``,
    ``pad62``, ``pad63`` (uint32), ``pad64`` (uint32), ``pad65``,
    ``pad66``.
    Total: 24 + 8 + 8 + 6 + 8 + 8 + 2 = 64 bytes.
    """
    fmt = struct.Struct("<QQQiiIIHHHbbbbbbbbIIbb")
    return fmt.pack(
        time_ms,
        src_agent,
        dst_agent,
        value,
        buff_dmg,
        0,  # overstack_value (ignored)
        skill_id,
        0,  # src_instid
        0,  # dst_instid
        0,  # translocated
        is_cleanup,
        is_nondamage,
        is_statechange,
        0,  # is_flanking
        0,  # is_shields
        is_offcycle,
        0,  # pad61
        0,  # pad62
        0,  # pad63 (uint32)
        0,  # pad64 (uint32)
        0,  # pad65
        0,  # pad66
    )


def _build_agent_record_2025(
    agent_id: int,
    prof: int,
    elite: int,
    name: str,
    *,
    account_name: str | None = None,
    subgroup: str | None = None,
) -> bytes:
    """Build one 96-byte EVTC2025+ agent record.

    Layout (per ``arcdps.h`` 2025+):
    ``<IIIIII64sII`` -- iid_low, profession, is_elite, toughness,
    healing, concentration, 64-byte name buffer, subgroup, addr.
    The event address is stored in ``addr`` (offset +92).
    """
    if account_name is None:
        raw = name.encode("utf-8") + b"\x00"
    else:
        raw = name.encode("utf-8") + b"\x00" + account_name.encode("utf-8") + b"\x00"
        if subgroup is not None:
            raw += subgroup.encode("utf-8") + b"\x00"
        else:
            raw += b"\x00"
    if len(raw) > 64:
        msg = f"name region {len(raw)} bytes exceeds 64"
        raise ValueError(msg)
    name_buf = raw + b"\x00" * (64 - len(raw))
    return struct.pack(
        "<IIIIII64sII",
        0,  # iid_low (unused)
        prof,
        elite,
        0,  # toughness
        0,  # healing
        0,  # concentration
        name_buf,
        0,  # subgroup struct field (parser reads subgroup from name buffer)
        agent_id,  # addr (event-matching id)
    )


def _build_event_record_2025(
    time_ms: int,
    src_agent: int,
    dst_agent: int,
    value: int,
    skill_id: int = 42,
    *,
    is_statechange: int = 0,
    is_nondamage: int = 0,
    buff_dmg: int = 0,
    result: int = 0,
) -> bytes:
    """Build one 64-byte EVTC2025+ cbtevent record.

    Layout (per ``arcdps.h`` 2025+):
    ``<QQQiiIIHHHH16B`` -- time, src, dst, value, buff_dmg,
    overstack, skillid, 4x instids, 16 flag bytes.
    Byte 50 (flags index 2) is the ``result`` enum (13/14 = heal);
    byte 56 (flags index 8) is ``is_statechange``.
    """
    flags = bytearray(16)
    if result:
        flags[2] = result
    else:
        flags[2] = 13 if is_nondamage > 0 else 0  # result
    flags[8] = is_statechange
    return struct.pack(
        "<QQQiiIIHHHH16B",
        time_ms,
        src_agent,
        dst_agent,
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


def _build_minimal_evtc(
    agents: list[tuple[int, int, int, str, bool]],
    *,
    build: str = "20240925",
    encounter_id: int = 0,
    skills: list[tuple[int, str]] | None = None,
    events: list[bytes] | None = None,
) -> bytes:
    """Build a synthetic EVTC binary with the given agents, skills, and events.

    Header layout is 24 bytes (see :data:`HEADER_SIZE`): magic + build
    (8 ASCII) + rev + combat_id + unused + agent_count + skill_count.
    Each agent tuple is ``(id, profession_id, elite_id,
    name, is_player)``. Each skill tuple is ``(skill_id, name)``. Each
    event is a full 64-byte cbtevent record pre-built by the caller.
    """
    if len(build) != 8:
        msg = f"build must be exactly 8 ASCII chars (yyyymmdd), got {len(build)}"
        raise ValueError(msg)
    if skills is None:
        skills = []
    if events is None:
        events = []
    is_2025 = int(build[:4]) >= 2025
    header = struct.pack(
        "<4s8sBHBI I",
        b"EVTC",
        build.encode("ascii"),
        0,
        encounter_id,
        0,
        len(agents),
        len(skills),
    )
    assert len(header) == HEADER_SIZE
    body = bytearray()
    for aid, prof, elite, name, is_player in agents:
        if is_2025:
            if is_player:
                rec = _build_agent_record_2025(
                    aid,
                    prof,
                    elite,
                    name,
                    account_name=f":synth.{aid}",
                )
            else:
                rec = _build_agent_record_2025(aid, prof, elite, name)
        elif is_player:
            rec = _build_agent_record(
                aid,
                prof,
                elite,
                name,
                account_name=f":synth.{aid}",
            )
        else:
            rec = _build_agent_record(aid, prof, elite, name)
        body += rec
    # Legacy (<2025) skill table has a count prefix before fixed-size records.
    build_version = int(build[:4])
    if build_version < 2025:
        body += struct.pack("<I", len(skills))
    for skill_id, skill_name in skills:
        body += _build_skill_record(skill_id, skill_name)
    for ev in events:
        assert len(ev) == EVENT_SIZE, f"each event record must be exactly {EVENT_SIZE} bytes"
        body += ev
    return header + bytes(body)


def _wrap_zevtc(evtc: bytes) -> bytes:
    """Wrap an EVTC blob in a minimal ``.zevtc`` zip."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("fight.evtc", evtc)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_synthetic_minimal_evtc_parses() -> None:
    evtc = _build_minimal_evtc([])
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    assert fight.header.build_version == "20240925"
    assert fight.header.agent_count == 0
    assert fight.header.skill_count == 0
    assert fight.header.encounter_id == 0
    assert fight.agents == []
    assert fight.skills == []
    assert fight.id


def test_synthetic_legacy_evtc_with_single_event_parses() -> None:
    """Pre-2025 (legacy) EVTC with a count prefix and a single event round-trips."""
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        build="20240925",
        skills=[(101, "Whirlwind")],
        events=[
            _build_event_record(
                time_ms=42_500,
                src_agent=1,
                dst_agent=2,
                value=1_337,
                skill_id=101,
            ),
        ],
    )
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    assert fight.header.build_version == "20240925"
    assert len(fight.skills) == 1
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 1
    assert isinstance(events[0], DamageEvent)
    assert events[0].damage == 1_337


def test_synthetic_player_agent_has_account_and_is_player() -> None:
    evtc = _build_minimal_evtc(
        [(123456, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Test Guardian", True)],
    )
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert len(fight.agents) == 1
    a = fight.agents[0]
    assert a.name == "Test Guardian"
    assert a.account_name == ":synth.123456"
    assert a.is_player is True
    assert a.subgroup == ""  # empty subgroup is a string
    assert a.profession == Profession.GUARDIAN
    assert a.elite == EliteSpec.DRAGONHUNTER


def test_synthetic_npc_agent_has_no_account() -> None:
    evtc = _build_minimal_evtc(
        [(789012, 99, 99, "Hostile NPC", False)],
    )
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    a = fight.agents[0]
    assert a.name == "Hostile NPC"
    assert a.is_player is False
    assert a.account_name is None
    assert a.subgroup is None
    assert a.profession == Profession.UNKNOWN
    assert a.elite == EliteSpec.UNKNOWN


def test_synthetic_mixed_players_and_npcs() -> None:
    agents = [
        (1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "G1", True),
        (2, Profession.WARRIOR.value, EliteSpec.BERSERKER.value, "W1", True),
        (3, 99, 99, "Mob", False),
    ]
    evtc = _build_minimal_evtc(agents)
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert len(fight.agents) == 3
    players = [a for a in fight.agents if a.is_player]
    npcs = [a for a in fight.agents if not a.is_player]
    assert len(players) == 2
    assert len(npcs) == 1
    for p in players:
        assert p.account_name is not None
        assert p.account_name.startswith(":")
    for n in npcs:
        assert n.account_name is None


def test_synthetic_truncated_blob_raises() -> None:
    short = b"EVTC" + b"\x00" * 10
    with pytest.raises(EvtcParseError, match="header needs 24"):
        list(PythonEvtcParser().parse(short))


def test_synthetic_bad_magic_raises() -> None:
    blob = b"JUNK" + b"\x00" * 21
    with pytest.raises(EvtcParseError, match="magic"):
        list(PythonEvtcParser().parse(blob))


def test_synthetic_truncated_agent_prefix_raises() -> None:
    """Header claims 1 agent but there is no AGENT_SIZE bytes after the header."""
    header = struct.pack("<4s8sBHBI I", b"EVTC", b"20240925", 0, 0, 0, 1, 0)
    blob = header + b"\x00" * 50  # only 50 bytes after header (need 96)
    with pytest.raises(EvtcParseError, match="Truncated agent record"):
        list(PythonEvtcParser().parse(blob))


def test_synthetic_agent_count_lie_raises() -> None:
    """Header claims 99 agents but body has none — first iteration truncates."""
    header = struct.pack("<4s8sBHBI I", b"EVTC", b"20240925", 0, 0, 0, 99, 0)
    with pytest.raises(EvtcParseError, match="Truncated agent record"):
        list(PythonEvtcParser().parse(header))


def test_synthetic_encounter_id_propagates() -> None:
    evtc = _build_minimal_evtc([], encounter_id=0xBEEF)
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    assert fight.header.encounter_id == 0xBEEF


def test_synthetic_agent_count_too_high_raises() -> None:
    blob = bytearray(_build_minimal_evtc([]))
    blob[AGENT_COUNT_OFFSET : AGENT_COUNT_OFFSET + 4] = struct.pack("<I", 100_000)
    with pytest.raises(EvtcParseError, match="safety bound"):
        list(PythonEvtcParser().parse(bytes(blob)))


def test_synthetic_large_map_id_is_ignored() -> None:
    """map_id at offset 20 is read but not validated; parsing succeeds."""
    blob = bytearray(_build_minimal_evtc([]))
    blob[SKILL_COUNT_OFFSET : SKILL_COUNT_OFFSET + 4] = struct.pack("<I", 200_000)
    fights = list(PythonEvtcParser().parse(bytes(blob)))
    assert len(fights) == 1


def test_zevtc_archive_is_unpacked_and_parsed() -> None:
    evtc = _build_minimal_evtc(
        [(1, Profession.MESMER.value, EliteSpec.CHRONOMANCER.value, "Chrono", True)],
    )
    zevtc = _wrap_zevtc(evtc)
    with zipfile.ZipFile(BytesIO(zevtc)) as zf:
        inner = zf.read("fight.evtc")
    fight = next(iter(PythonEvtcParser().parse(inner)))
    assert fight.agents[0].name == "Chrono"
    assert fight.agents[0].profession == Profession.MESMER
    assert fight.agents[0].account_name == ":synth.1"


def test_stable_fight_id_is_sha256_of_input() -> None:
    evtc = _build_minimal_evtc(
        [(1, Profession.RANGER.value, EliteSpec.UNTAMED.value, "R", True)],
    )
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    expected = hashlib.sha256(evtc).hexdigest()
    assert fight.id == expected


def test_layout_constants_match_parser_v1() -> None:
    """Sanity-check the layout constants we publish."""
    assert HEADER_SIZE == 24
    assert AGENT_COUNT_OFFSET == 16
    assert SKILL_COUNT_OFFSET == 20
    assert AGENTS_OFFSET == 24
    assert AGENT_PREFIX_SIZE == 24
    assert AGENT_NAME_SIZE == 72
    assert AGENT_SIZE == 96
    assert EVENT_SIZE == 64


def test_account_name_without_colon_is_accepted_as_player() -> None:
    """A 'player' record whose account_name lacks ``:`` is *not* an error in V1.

    Real arcdps revisions have emitted bare account ids (e.g. ``b'2'``)
    and we accept them. The 3-part combo structure is the authoritative
    player signal; the leading ``:`` is a soft convention we surface
    as ``logger.debug`` rather than reject.
    """
    rec = _build_agent_record(
        1,
        0,
        0,
        "Name",
        account_name="no_colon",
        # subgroup omitted intentionally -> helper writes a single \x00 tail
    )
    assert len(rec) == AGENT_SIZE
    header = struct.pack("<4s8sBHBI I", b"EVTC", b"20240925", 0, 0, 0, 1, 0)
    fight = next(iter(PythonEvtcParser().parse(header + rec)))
    a = fight.agents[0]
    assert a.is_player is True
    assert a.name == "Name"
    assert a.account_name == "no_colon"
    assert a.subgroup == ""


def test_player_with_empty_account_name_and_subgroup() -> None:
    """Real arcdps WvW edge case: account_name is empty but subgroup is set."""
    # Combo string ``Name\0\0sub\0`` -- the empty account_name bytes
    # correspond to a ``None`` account_name at the parser layer; subgroup
    # is what marks this record as a player. Helper reproduces the bytes
    # verbatim.
    rec = _build_agent_record(1, 0, 0, "Name", account_name="", subgroup="sub")
    assert len(rec) == AGENT_SIZE
    header = struct.pack("<4s8sBHBI I", b"EVTC", b"20240925", 0, 0, 0, 1, 0)
    fight = next(iter(PythonEvtcParser().parse(header + rec)))
    a = fight.agents[0]
    assert a.is_player is True
    assert a.name == "Name"
    assert a.account_name is None
    assert a.subgroup == "sub"


def test_player_with_empty_char_name_but_valid_account_and_subgroup() -> None:
    """WvW arcdps edge case: empty ``char_name`` (parts[0]) but a valid
    ``account_name`` (parts[1]) and a non-empty ``subgroup`` (parts[2]).

    Distinct from ``test_player_with_empty_account_name_and_subgroup`` which
    zeroes out parts[1] instead: here parts[0] is empty. Per the parser's
    documented leniency class (parser.py ``_decode_agent``), an agent is
    classified as a player when EITHER ``raw_account`` (parts[1]) OR
    ``raw_subgroup`` (parts[2]) is non-empty -- so an empty char_name
    alone does NOT downgrade the agent to NPC.

    This locks down the real arcdps WvW quirk (a player record whose
    68-byte name buffer starts with a null char-name but carries a
    valid ``:account`` + ``\\subgroup`` tail) at unit-test level so we
    do not rely solely on the ``/tmp/inner_20251002-213519`` integration
    fixture for this coverage.
    """
    # Hand the empty-char-name quirk to the shared helper: an empty
    # ``name`` (parts[0]) followed by ``:account`` (parts[1]) + ``subgroup``
    # (parts[2]) is the same byte sequence as the manual packing below
    # produces -- the helper centralises the null-padded combo string.
    rec = _build_agent_record(
        1,
        0,
        0,
        "",
        account_name=":Account.1234",
        subgroup="subSquad",
    )
    assert len(rec) == AGENT_SIZE
    header = struct.pack("<4s8sBHBI I", b"EVTC", b"20240925", 0, 0, 0, 1, 0)
    fight = next(iter(PythonEvtcParser().parse(header + rec)))
    a = fight.agents[0]
    assert a.is_player is True
    assert a.name == ""
    assert a.account_name == ":Account.1234"
    assert a.subgroup == "subSquad"


def test_npc_with_fully_null_tail_after_name_is_npc() -> None:
    rec = _build_agent_record(1, 0, 0, "Mob")
    assert len(rec) == AGENT_SIZE
    header = struct.pack("<4s8sBHBI I", b"EVTC", b"20240925", 0, 0, 0, 1, 0)
    fight = next(iter(PythonEvtcParser().parse(header + rec)))
    a = fight.agents[0]
    assert a.is_player is False
    assert a.name == "Mob"
    assert a.account_name is None
    assert a.subgroup is None


# ---------------------------------------------------------------------------
# EVTC2025+ format tests
# ---------------------------------------------------------------------------


def test_synthetic_minimal_evtc_2025_parses() -> None:
    evtc = _build_minimal_evtc([], build="20250925")
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    assert fight.header.build_version == "20250925"
    assert fight.header.agent_count == 0
    assert fight.header.skill_count == 0
    assert fight.agents == []
    assert fight.skills == []
    assert fight.id


def test_evtc2025_boundary_zero_events_parses() -> None:
    """EVTC2025+ with skills but no events must still parse cleanly."""
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        build="20250925",
        skills=[(101, "Whirlwind")],
        events=[],
    )
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    assert fight.header.build_version == "20250925"
    assert fight.header.agent_count == 1
    assert len(fight.skills) == 1
    assert fight.skills[0].id == 101
    events = list(PythonEvtcParser().parse_events(evtc))
    assert events == []


def test_evtc2025_boundary_zero_events_with_small_skill_id_parses() -> None:
    """EVTC2025+ with skill_id that looks like a small legacy count.

    A skill_id of 1 is the most ambiguous legacy-count lookalike,
    because the first 4 bytes could also be read as a legacy
    skill_count. The parser must still identify the EVTC2025+ format.
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        build="20250925",
        skills=[(1, "Whirlwind")],
        events=[],
    )
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    assert fight.header.agent_count == 1
    assert len(fight.skills) == 1
    assert fight.skills[0].id == 1
    events = list(PythonEvtcParser().parse_events(evtc))
    assert events == []


def test_evtc2025_boundary_one_event_parses() -> None:
    """EVTC2025+ with a single event must locate the event stream."""
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        build="20250925",
        skills=[(101, "Whirlwind")],
        events=[
            _build_event_record_2025(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=100,
                skill_id=101,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 1
    assert isinstance(events[0], DamageEvent)
    assert events[0].time_ms == 1_000
    assert events[0].damage == 100


def test_evtc2025_boundary_two_events_parses() -> None:
    """EVTC2025+ with two events must parse both in order."""
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        build="20250925",
        skills=[(101, "Whirlwind")],
        events=[
            _build_event_record_2025(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=100,
                skill_id=101,
            ),
            _build_event_record_2025(
                time_ms=2_000,
                src_agent=1,
                dst_agent=2,
                value=200,
                skill_id=101,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 2
    assert isinstance(events[0], DamageEvent)
    assert events[0].time_ms == 1_000
    assert events[0].damage == 100
    assert isinstance(events[1], DamageEvent)
    assert events[1].time_ms == 2_000
    assert events[1].damage == 200


def test_synthetic_player_agent_2025_has_account_and_is_player() -> None:
    evtc = _build_minimal_evtc(
        [(123456, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Test Guardian", True)],
        build="20250925",
    )
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert len(fight.agents) == 1
    a = fight.agents[0]
    assert a.id == 123456
    assert a.name == "Test Guardian"
    assert a.account_name == ":synth.123456"
    assert a.is_player is True
    assert a.subgroup == ""
    assert a.profession == Profession.GUARDIAN
    assert a.elite == EliteSpec.DRAGONHUNTER


def test_synthetic_npc_agent_2025_has_no_account() -> None:
    evtc = _build_minimal_evtc(
        [(789012, 99, 99, "Hostile NPC", False)],
        build="20250925",
    )
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    a = fight.agents[0]
    assert a.id == 789012
    assert a.name == "Hostile NPC"
    assert a.is_player is False
    assert a.account_name is None
    assert a.subgroup is None


def test_synthetic_skill_table_2025_parses_without_count_prefix() -> None:
    # EVTC2025+ has no skill count prefix; the parser discovers the
    # skill-to-event boundary by inspecting the event stream. Include
    # at least two events so the boundary validator can confirm the
    # event stream (it needs >=2 known-agent matches).
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        build="20250925",
        skills=[(101, "Whirlwind"), (202, "Burning Precision")],
        events=[
            _build_event_record_2025(
                time_ms=1_000, src_agent=1, dst_agent=2, value=100, skill_id=101
            ),
            _build_event_record_2025(
                time_ms=2_000, src_agent=1, dst_agent=2, value=200, skill_id=202
            ),
        ],
    )
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    assert fight.header.skill_count == 2
    assert len(fight.skills) == 2
    assert fight.skills[0].id == 101
    assert fight.skills[0].name == "Whirlwind"
    assert fight.skills[1].id == 202
    assert fight.skills[1].name == "Burning Precision"


def test_parse_events_2025_single_damage_round_trips() -> None:
    # Include two events so the EVTC2025+ boundary validator (which
    # requires >=2 known-agent matches) can locate the event stream.
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        build="20250925",
        skills=[(101, "Whirlwind")],
        events=[
            _build_event_record_2025(
                time_ms=42_500,
                src_agent=1,
                dst_agent=2,
                value=1_337,
                skill_id=101,
            ),
            _build_event_record_2025(
                time_ms=43_500,
                src_agent=1,
                dst_agent=2,
                value=2_000,
                skill_id=101,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 2
    e = events[0]
    assert isinstance(e, DamageEvent)
    assert e.time_ms == 42_500
    assert e.source_agent_id == 1
    assert e.target_agent_id == 2
    assert e.skill_id == 101
    assert e.damage == 1_337


def test_parse_events_2025_single_event_with_known_agent_is_accepted() -> None:
    """A single-event EVTC2025+ file with a known agent is parsed correctly.

    The boundary validator originally required >=2 known-agent
    matches, which rejected single-event files. This regression test
    locks down the relaxed requirement (1 match when only 1 record
    is readable).
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        build="20250925",
        skills=[(101, "Whirlwind")],
        events=[
            _build_event_record_2025(
                time_ms=42_500,
                src_agent=1,
                dst_agent=2,
                value=1_337,
                skill_id=101,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 1
    assert isinstance(events[0], DamageEvent)
    assert events[0].damage == 1_337


@pytest.mark.parametrize("result_value", [13, 14])
def test_parse_events_2025_yields_healing_event_on_nondamage(result_value: int) -> None:
    # Include two events so the EVTC2025+ boundary validator can
    # locate the event stream. Both result=13 (CBTR_HEAL) and
    # result=14 (CBTR_BUFFHEAL) should be interpreted as healing.
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        build="20250925",
        skills=[(101, "Symbol of Healing")],
        events=[
            _build_event_record_2025(
                time_ms=42_500,
                src_agent=1,
                dst_agent=2,
                value=8_500,
                skill_id=101,
                result=result_value,
            ),
            _build_event_record_2025(
                time_ms=43_500,
                src_agent=1,
                dst_agent=2,
                value=9_000,
                skill_id=101,
                result=result_value,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 2
    e = events[0]
    assert isinstance(e, HealingEvent)
    assert e.time_ms == 42_500
    assert e.source_agent_id == 1
    assert e.target_agent_id == 2
    assert e.skill_id == 101
    assert e.healing == 8_500


# ---------------------------------------------------------------------------
# V1.3 skill table tests
# ---------------------------------------------------------------------------


def test_synthetic_skill_table_parses() -> None:
    """A fight with 2 skills round-trips through the parser.

    skill_count is not stored in the rev>=1 header; the parser
    discovers skills by walking the skill table.
    """
    evtc = _build_minimal_evtc(
        [],
        skills=[(101, "Whirlwind"), (202, "Burning Precision")],
    )
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    # skill_count is derived from the actual skill records parsed
    assert fight.header.skill_count == 2
    assert len(fight.skills) == 2
    assert fight.skills[0].id == 101
    assert fight.skills[0].name == "Whirlwind"
    assert fight.skills[1].id == 202
    assert fight.skills[1].name == "Burning Precision"


def test_synthetic_empty_skill_table_yields_empty_list() -> None:
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "G", True)],
    )
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.skills == []


def test_synthetic_skill_with_empty_name() -> None:
    """A skill record with name_len=0 is valid (just a skill_id, no name)."""
    evtc = _build_minimal_evtc([], skills=[(999, "")])
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert len(fight.skills) == 1
    assert fight.skills[0].id == 999
    assert fight.skills[0].name == ""


def test_synthetic_skill_with_unicode_name() -> None:
    """Skill names can contain non-ASCII (e.g. translated skill names)."""
    evtc = _build_minimal_evtc([], skills=[(42, "Éruption solaire")])
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.skills[0].name == "Éruption solaire"


def test_synthetic_truncated_skill_header_stops_early() -> None:
    """Body is missing the 8-byte skill header after agents.

    The parser is lenient: it logs a warning and yields zero skills
    rather than raising. This is the V1.3 behavior for real arcdps
    files whose skill table is empty.
    """
    header = struct.pack("<4s8sBHBI I", b"EVTC", b"20240925", 0, 0, 0, 0, 0)
    fight = next(iter(PythonEvtcParser().parse(header)))
    assert fight.skills == []


def test_synthetic_truncated_skill_record_stops_early() -> None:
    """Skill data ends before a full 68-byte record is present.

    Lenient: parser yields zero skills and logs a warning.
    """
    header = struct.pack("<4s8sBHBI I", b"EVTC", b"20240925", 0, 0, 0, 0, 0)
    partial = struct.pack("<I", 1) + b"abc"  # only 7 bytes of the 68-byte record
    blob = header + partial
    fight = next(iter(PythonEvtcParser().parse(blob)))
    assert fight.skills == []


def test_synthetic_long_skill_name_is_truncated_to_buffer() -> None:
    """A skill name longer than 64 bytes is truncated to the fixed buffer."""
    long_name = "a" * 100
    evtc = _build_minimal_evtc([], skills=[(1, long_name)])
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert len(fight.skills) == 1
    assert fight.skills[0].id == 1
    assert fight.skills[0].name == "a" * 64


def test_synthetic_skills_and_agents_together() -> None:
    """The full synthetic fight has agents + skills in the right order."""
    evtc = _build_minimal_evtc(
        [
            (1, Profession.WARRIOR.value, EliteSpec.BERSERKER.value, "W", True),
            (2, 99, 99, "Mob", False),
        ],
        skills=[(101, "Whirlwind"), (202, "Burning")],
    )
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    assert fight.header.agent_count == 2
    assert fight.header.skill_count == 2
    assert len(fight.agents) == 2
    assert len(fight.skills) == 2
    assert fight.agents[0].name == "W"
    assert fight.skills[0].name == "Whirlwind"


# ---------------------------------------------------------------------------
# _iter_skill_records helper tests
# ---------------------------------------------------------------------------


def test_iter_skill_records_yields_expected_tuples() -> None:
    """``_iter_skill_records`` exposes cursor, skill_id and name."""
    skill_block = _build_skill_record(101, "Whirlwind") + _build_skill_record(202, "Burning")
    header = struct.pack("<4s8sBHBI I", b"EVTC", b"20240925", 0, 0, 0, 0, 0)
    data = header + skill_block
    records = list(_iter_skill_records(data, AGENTS_OFFSET, 2))
    assert len(records) == 2
    cursor0, skill_id0, name0 = records[0]
    assert skill_id0 == 101
    assert name0 == "Whirlwind"
    assert cursor0 == AGENTS_OFFSET
    cursor1, skill_id1, name1 = records[1]
    assert skill_id1 == 202
    assert name1 == "Burning"
    assert cursor1 == AGENTS_OFFSET + SKILL_RECORD_SIZE


def test_iter_skill_records_empty_count_yields_nothing() -> None:
    """A count of zero yields no records without touching the data."""
    records = list(_iter_skill_records(b"irrelevant", 0, 0))
    assert records == []


def test_iter_skill_records_truncated_record_stops_early(caplog: pytest.LogCaptureFixture) -> None:
    """If a full skill record does not fit, the generator stops and logs a warning."""
    header = struct.pack("<4s8sBHBI I", b"EVTC", b"20240925", 0, 0, 0, 0, 0)
    # Only 20 bytes after the header, not enough for a 68-byte skill record.
    data = header + b"\x00" * 20
    with caplog.at_level("WARNING"):
        records = list(_iter_skill_records(data, AGENTS_OFFSET, 1))
    assert records == []
    assert "Truncated skill table" in caplog.text


def test_iter_skill_records_long_name_truncated_to_buffer(caplog: pytest.LogCaptureFixture) -> None:
    """A name longer than 64 bytes is truncated to the fixed name buffer."""
    header = struct.pack("<4s8sBHBI I", b"EVTC", b"20240925", 0, 0, 0, 0, 0)
    long_name = "a" * 100
    skill_block = _build_skill_record(1, long_name)
    data = header + skill_block
    with caplog.at_level("WARNING"):
        records = list(_iter_skill_records(data, AGENTS_OFFSET, 1))
    assert len(records) == 1
    assert records[0][1] == 1
    assert records[0][2] == "a" * 64


def test_iter_skill_records_empty_name_yields_empty_string() -> None:
    """A skill with an empty name yields an empty string as its name."""
    header = struct.pack("<4s8sBHBI I", b"EVTC", b"20240925", 0, 0, 0, 0, 0)
    skill_block = _build_skill_record(1, "")
    data = header + skill_block
    records = list(_iter_skill_records(data, AGENTS_OFFSET, 1))
    assert len(records) == 1
    assert records[0][1] == 1
    assert records[0][2] == ""


def test_iter_skill_records_stops_when_table_runs_past_end() -> None:
    """The generator yields valid records and stops when data runs out."""
    header = struct.pack("<4s8sBHBI I", b"EVTC", b"20240925", 0, 0, 0, 0, 0)
    # Only 2 skills actually present.
    skill_block = _build_skill_record(101, "A") + _build_skill_record(202, "B")
    data = header + skill_block
    records = list(_iter_skill_records(data, AGENTS_OFFSET, 3))
    assert len(records) == 2
    assert records[0][1] == 101
    assert records[1][1] == 202


# ---------------------------------------------------------------------------
# read_zevtc_bytes
# ---------------------------------------------------------------------------


def test_read_zevtc_bytes_extracts_inner_evtc() -> None:
    inner = _build_minimal_evtc([])
    zevtc = _wrap_zevtc(inner)
    assert read_zevtc_bytes(zevtc) == inner
    fight = next(iter(PythonEvtcParser().parse(read_zevtc_bytes(zevtc))))
    assert fight.header is not None
    assert fight.header.build_version == "20240925"


def test_read_zevtc_bytes_raises_on_bogus_zip() -> None:
    with pytest.raises(EvtcParseError, match="not a valid"):
        read_zevtc_bytes(b"not a zip")


def test_read_zevtc_bytes_raises_on_empty_zip() -> None:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass
    with pytest.raises(EvtcParseError, match="empty"):
        read_zevtc_bytes(buf.getvalue())


# ---------------------------------------------------------------------------
# Phase 7 v1: parse_events (cbtevent stream consumer) tests
# ---------------------------------------------------------------------------


def test_parse_events_empty_event_block_yields_nothing() -> None:
    """Header + agent + skill with NO appending events -> 0 events yielded."""
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "G", True)],
        skills=[(101, "Whirlwind")],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert events == []


def test_parse_events_single_damage_round_trips() -> None:
    """One damage record round-trips into a DamageEvent with all fields preserved."""
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Whirlwind")],
        events=[
            _build_event_record(
                time_ms=42_500,
                src_agent=1,
                dst_agent=2,
                value=1_337,
                skill_id=101,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, DamageEvent)
    assert e.time_ms == 42_500
    assert e.source_agent_id == 1
    assert e.target_agent_id == 2
    assert e.skill_id == 101
    assert e.damage == 1_337


def test_parse_events_truncated_trailing_record_exits_cleanly() -> None:
    """A trailing record whose bytes are shorter than 64 yields a clean stop.

    Layout has TWO events so the first is fully present (yields) and
    the second is partially written (parser stops cleanly without
    raising).
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Whirlwind")],
        events=[
            _build_event_record(time_ms=1_000, src_agent=1, dst_agent=2, value=100),
            _build_event_record(time_ms=2_000, src_agent=1, dst_agent=2, value=200),
        ],
    )
    # Drop 30 bytes from the end -- truncates the second event; the first still fits.
    truncated = evtc[:-30]
    events = list(PythonEvtcParser().parse_events(truncated))
    assert len(events) == 1
    assert events[0].time_ms == 1_000


def test_parse_events_negative_value_is_clamped_to_zero() -> None:
    """Negative ``value`` is clamped via ``max(0, value)`` and yields no event.

    Real arcdps data occasionally surfaces signed-int overflow quirks
    (extreme damage totals wrapping negative). Domain :class:`DamageEvent`
    invariants reject ``damage < 0``; the parser handles this at the
    event-block filter boundary rather than letting negative sums
    corrupt downstream aggregate sums.
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Whirlwind")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=-100,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert events == []


def test_parse_events_clamps_overflow_val_to_zero() -> None:
    """Signed-int-32 minimum (``-2**31``) clamps to ``damage=0`` and is filtered.

    Locks down the validator's ``max(0, value)`` boundary at the
    int32 edge so a future refactor that lifts the clamp cannot silently
    regress to negative aggregate sums.
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Whirlwind")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=-2_147_483_648,  # INT32_MIN sentinel
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert events == []


def test_parse_events_zero_value_yields_nothing() -> None:
    """Mirrors ``test_parse_events_negative_value_is_clamped_to_zero``: val=0 skips."""
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Whirlwind")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=0,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert events == []


def test_parse_events_filters_statechange_skips_damage() -> None:
    """Sequence: statechange record then damage record yields 1 event."""
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Whirlwind")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=99,
                is_statechange=1,
            ),  # filtered (state change)
            _build_event_record(
                time_ms=2_000,
                src_agent=1,
                dst_agent=2,
                value=42,
            ),  # yielded
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 1
    # Rebind to a typed local so mypy narrows ``.damage`` on the
    # ``Event`` discriminated union without losing the narrowing
    # across multiple ``events[i]`` accesses.
    damage_event = events[0]
    assert isinstance(damage_event, DamageEvent)
    assert damage_event.damage == 42
    assert damage_event.time_ms == 2_000


def test_parse_events_skips_statechange_records() -> None:
    """Records with ``is_statechange != 0`` (buff apply / position log) are filtered."""
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Whirlwind")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=999,
                is_statechange=1,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert events == []


def test_parse_events_skips_nondamage_records_damage_path() -> None:
    """Old Phase 7 v1 contract: ``is_nondamage == 1`` was filtered.

    Phase 7 v2 changed the contract: ``is_nondamage > 0`` is the
    HEALING signal (convention A + Elite Insights parity), not the
    filter. ``test_parse_events_yields_healing_event_on_nondamage``
    is the new contract test. This test stays as a regression guard
    on the value-filtering branch: a record with ``value == 0`` and
    ``is_nondamage == 1`` should still skip (zero-magnitude heal).
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Whirlwind")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=0,
                is_nondamage=1,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert events == []


# ---------------------------------------------------------------------------
# Phase 7 v2: HealingEvent extraction tests
# ---------------------------------------------------------------------------


def test_parse_events_yields_healing_event_on_nondamage() -> None:
    """``is_statechange == 0 && is_nondamage > 0 && value > 0`` yields a HealingEvent.

    Convention A (Elite Insights parity): the ``value`` field carries
    the heal magnitude when the non-damage flag is set. The
    HealingEvent.round-trip carries skill_id + source/target agents +
    time_ms + healing.
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Symbol of Healing")],
        events=[
            _build_event_record(
                time_ms=42_500,
                src_agent=1,
                dst_agent=2,
                value=8_500,
                is_nondamage=1,
                skill_id=101,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, HealingEvent)
    assert e.event_type == "HEALING"
    assert e.time_ms == 42_500
    assert e.source_agent_id == 1
    assert e.target_agent_id == 2
    assert e.skill_id == 101
    assert e.healing == 8_500


def test_parse_events_clamps_negative_healing_to_zero() -> None:
    """Negative ``value`` with ``is_nondamage > 0`` clamps via ``max(0, value)`` -> skip.

    Pydantic ``HealingEvent.healing: int >= 0`` enforces the invariant;
    the parser absorbs signed-int32 overflow at the event-block filter
    boundary so negative sums cannot corrupt downstream healing totals.
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Healing Skill")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=-50,
                is_nondamage=1,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert events == []


def test_parse_events_emits_one_event_per_cbtevent_for_damage_plus_heal() -> None:
    """A cbtevent record yields AT MOST ONE event (Convention A).

    When ``is_nondamage == 0`` AND ``value > 0``: yields DamageEvent.
    When ``is_nondamage > 0`` AND ``value > 0``: yields HealingEvent.
    The two conditions are mutually exclusive on a single record; we
    deliberately do NOT also emit a HealingEvent from ``buff_dmg``
    on the same record -- that would double-count.
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Maim")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=2_500,  # direct damage via value
                is_nondamage=0,
                skill_id=101,
            ),
            _build_event_record(
                time_ms=2_000,
                src_agent=1,
                dst_agent=2,
                value=1_250,  # healing via value (is_nondamage flag flips the meaning)
                is_nondamage=1,  # Convention A: is_nondamage > 0 = heal
                skill_id=101,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 2
    # Rebind to typed locals so mypy flow-typing can resolve .damage
    # vs .healing on the Event discriminated union without losing the
    # narrowing across multiple ``events[i]`` accesses.
    e0 = events[0]
    e1 = events[1]
    assert isinstance(e0, DamageEvent), "first record (nondamage=0) yields DamageEvent"
    assert e0.damage == 2_500
    assert isinstance(e1, HealingEvent), "second record (nondamage=1) yields HealingEvent"
    assert e1.healing == 1_250


def test_parse_events_skips_statechange_for_healing() -> None:
    """Statechange records (``is_statechange != 0``) are skipped, even with is_nondamage > 0.

    Phase 8 will revisit ``is_statechange`` records for buff-apply +
    defiance-bar + position events; Phase 7 v2 deliberately skips them
    all.
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Heal Skill")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=9_999,
                is_nondamage=1,
                is_statechange=1,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert events == []


def test_parse_events_skips_statechange_for_damage() -> None:
    """Statechange records (``is_statechange != 0``) are skipped, even with is_nondamage == 0.

    Locks down the post-v2 invariant: regardless of is_nondamage
    flag, ``is_statechange != 0`` always skips. Mirrors the
    healing-side test above.
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Skill")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=9_999,
                is_nondamage=0,
                is_statechange=1,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert events == []


def test_parse_events_emits_heterogeneous_stream_signed_by_event_type() -> None:
    """Mixed damage + heal stream yields DamageEvent + HealingEvent instances.

    Each event's concrete subclass is determined solely by the
    cbtevent ``is_nondamage`` flag; the discriminator field on the
    Pydantic model (``event_type``) reads back from JSONL and is
    consistent with the runtime ``isinstance`` check.
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Skill")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=100,
                is_nondamage=0,
            ),
            _build_event_record(
                time_ms=2_000,
                src_agent=1,
                dst_agent=2,
                value=200,
                is_nondamage=1,
            ),
            _build_event_record(
                time_ms=3_000,
                src_agent=1,
                dst_agent=2,
                value=300,
                is_nondamage=0,
            ),
            _build_event_record(
                time_ms=4_000,
                src_agent=1,
                dst_agent=2,
                value=400,
                is_nondamage=1,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 4
    # Sequence: D, H, D, H -- matches the alternating fixture above.
    assert isinstance(events[0], DamageEvent)
    assert events[0].damage == 100
    assert isinstance(events[1], HealingEvent)
    assert events[1].healing == 200
    assert isinstance(events[2], DamageEvent)
    assert events[2].damage == 300
    assert isinstance(events[3], HealingEvent)
    assert events[3].healing == 400


def test_parse_events_yield_type_is_event_union() -> None:
    """Static-type witness: ``parse_events`` is annotated as ``Iterator[Event]``.

    A caller iterating the result sees instances of either subclass
    (Pydantic v2 discriminated union). This is a smoke test on the
    typing contract -- we measure the Stream-vs-unbound member
    without asserting the return annotation at runtime (the
    annotation is structural; the isinstance ladder proves the
    discriminated-union dispatch was correct).
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Skill")],
        events=[
            _build_event_record(
                time_ms=500,
                src_agent=1,
                dst_agent=2,
                value=10,
                is_nondamage=0,
            ),
            _build_event_record(
                time_ms=1_500,
                src_agent=1,
                dst_agent=2,
                value=20,
                is_nondamage=1,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # The ``Event`` PEP 695 ``type`` declaration is a ``TypeAliasType``
    # at runtime, not a runtime-callable class -- so ``isinstance(e,
    # Event)`` raises ``TypeError``. The two leaf subclasses are
    # themselves, so a tuple-form ``isinstance`` check covers the
    # same contract at runtime + is mypy-clean.
    for e in events:
        assert isinstance(e, (DamageEvent, HealingEvent))


# ---------------------------------------------------------------------------
# Phase 8: BuffRemovalEvent extraction tests
# ---------------------------------------------------------------------------


def test_parse_events_yields_buff_removal_on_nondamage_with_buff_dmg() -> None:
    """``is_nondamage > 0 && value > 0 && buff_dmg > 0`` yields TWO events.

    Locks down the same-record dual-emit contract: a single arcdps
    cbtevent can carry BOTH a heal (``value``) AND a buff-strip
    (``buff_dmg``). The parser yields a ``HealingEvent`` AND a
    ``BuffRemovalEvent`` from the same record. This is the canonical
    case for a corrupting / confusion skill that heals the caster
    and strips a boon from the target.
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Mimic")],
        events=[
            _build_event_record(
                time_ms=42_500,
                src_agent=1,
                dst_agent=2,
                value=8_500,
                buff_dmg=2_250,
                is_nondamage=1,
                skill_id=101,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 2
    heal, strip = events
    assert isinstance(heal, HealingEvent)
    assert heal.time_ms == 42_500
    assert heal.source_agent_id == 1
    assert heal.target_agent_id == 2
    assert heal.skill_id == 101
    assert heal.healing == 8_500
    assert isinstance(strip, BuffRemovalEvent)
    assert strip.event_type == "BUFF_REMOVAL"
    assert strip.time_ms == 42_500
    assert strip.source_agent_id == 1
    assert strip.target_agent_id == 2
    assert strip.skill_id == 101
    assert strip.buff_removal == 2_250


def test_parse_events_yields_buff_removal_only_on_pure_strip() -> None:
    """``is_nondamage > 0 && value == 0 && buff_dmg > 0`` yields ONLY a BuffRemovalEvent.

    The "no-heal + buff-strip" path is the Phase 8 add for skills
    that strip a boon from the target WITHOUT a healing component
    on the caster. The parser must yield a single ``BuffRemovalEvent``
    (no ``HealingEvent``), and the resulting yield list has length
    exactly 1.
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Strip\uff21ura")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=0,
                buff_dmg=750,
                is_nondamage=1,
                skill_id=101,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, BuffRemovalEvent)
    assert e.buff_removal == 750
    assert e.skill_id == 101
    assert e.source_agent_id == 1
    assert e.target_agent_id == 2


def test_parse_events_skips_damage_with_buff_dmg() -> None:
    """``is_nondamage == 0 && buff_dmg > 0`` is silently dropped (no event).

    Pure damage records with non-zero ``buff_dmg`` are a
    parser-version artefact: arcdps only writes ``buff_dmg`` on the
    heal-class event kind, so a damage record with non-zero
    ``buff_dmg`` is NOT a valid Phase 8 buff-strip signal. The parser
    yields no event (the record is fully filtered). This locks down
    the contract that the damage path does NOT inspect ``buff_dmg``
    (only the heal-class path does).
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Spurious")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=2_500,  # direct damage via value
                buff_dmg=999,  # spurious: arcdps does not write this on damage records
                is_nondamage=0,
                skill_id=101,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 1
    e = events[0]
    # The damage record yields a single ``DamageEvent``; the spurious
    # ``buff_dmg`` is silently dropped. No ``BuffRemovalEvent`` is
    # produced from the damage path.
    assert isinstance(e, DamageEvent)
    assert e.damage == 2_500


def test_parse_events_clamps_negative_buff_dmg_to_zero() -> None:
    """Negative ``buff_dmg`` is clamped via ``max(0, buff_dmg)`` and the strip is dropped.

    Pydantic ``BuffRemovalEvent.buff_removal: int >= 0`` enforces the
    invariant; the parser absorbs signed-int32 overflow at the
    event-block filter boundary so negative sums cannot corrupt
    downstream buff-removal totals. The corresponding ``value`` field
    is processed independently.
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Heal Skill")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=8_500,
                buff_dmg=-50,
                is_nondamage=1,
                skill_id=101,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Only the heal is yielded; the negative ``buff_dmg`` clamps to
    # zero and the strip path is skipped.
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, HealingEvent)
    assert e.healing == 8_500


def test_parse_events_skips_statechange_for_buff_strip() -> None:
    """Statechange records with buff_dmg > 0 are skipped (no strip emitted).

    Mirrors ``test_parse_events_skips_statechange_for_healing``:
    regardless of ``is_nondamage`` + ``buff_dmg`` flags,
    ``is_statechange != 0`` always skips. Locks down the post-Phase-8
    invariant that buff-apply / defiance-bar / position events are
    still out of scope.
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Skill")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=8_500,
                buff_dmg=2_250,
                is_nondamage=1,
                is_statechange=1,
                skill_id=101,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert events == []


def test_parse_events_emits_heterogeneous_damage_heal_strip_stream() -> None:
    """Mixed damage + heal + strip stream yields the right three subclasses in order.

    Locks down the runtime ``isinstance`` ladder + ordering for a
    heterogeneous stream. Sequence: D, H+S, D, S-only, H -- the
    second record dual-emits (H + S), the fourth yields only a strip
    (value == 0, buff_dmg > 0), the fifth yields only a heal
    (value > 0, buff_dmg == 0). Total yield count: 6 events.
    """
    evtc = _build_minimal_evtc(
        [(1, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Src", True)],
        skills=[(101, "Skill")],
        events=[
            # 1: pure damage
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=100,
                is_nondamage=0,
            ),
            # 2: heal + strip (dual emit)
            _build_event_record(
                time_ms=2_000,
                src_agent=1,
                dst_agent=2,
                value=200,
                buff_dmg=80,
                is_nondamage=1,
            ),
            # 3: pure damage
            _build_event_record(
                time_ms=3_000,
                src_agent=1,
                dst_agent=2,
                value=300,
                is_nondamage=0,
            ),
            # 4: pure strip (no heal)
            _build_event_record(
                time_ms=4_000,
                src_agent=1,
                dst_agent=2,
                value=0,
                buff_dmg=50,
                is_nondamage=1,
            ),
            # 5: pure heal (no strip)
            _build_event_record(
                time_ms=5_000,
                src_agent=1,
                dst_agent=2,
                value=400,
                is_nondamage=1,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Yield count: 1 (D) + 2 (H+S) + 1 (D) + 1 (S) + 1 (H) = 6.
    assert len(events) == 6
    # Per-event ordering: the dual-emit (H+S) keeps the HealingEvent
    # FIRST, then the BuffRemovalEvent -- the order matches the
    # arcdps convention (heal column then strip column) and is the
    # documented contract for same-record dual-emit.
    assert isinstance(events[0], DamageEvent) and events[0].damage == 100
    assert isinstance(events[1], HealingEvent) and events[1].healing == 200
    assert isinstance(events[2], BuffRemovalEvent) and events[2].buff_removal == 80
    assert isinstance(events[3], DamageEvent) and events[3].damage == 300
    assert isinstance(events[4], BuffRemovalEvent) and events[4].buff_removal == 50
    assert isinstance(events[5], HealingEvent) and events[5].healing == 400


# ---------------------------------------------------------------------------
# Real-file integration (skipped if fixture absent)
# ---------------------------------------------------------------------------


_REAL_FIXTURE = Path("/tmp/inner_20251002-213519")  # noqa: S108 (test-only diagnostic fixture)


@pytest.mark.skipif(not _REAL_FIXTURE.exists(), reason="real EVTC fixture not available")
def test_real_evtc_binary_parses_with_realistic_agent_count() -> None:
    raw = _REAL_FIXTURE.read_bytes()
    fight = next(iter(PythonEvtcParser().parse(raw)))
    assert fight.header is not None
    assert fight.header.agent_count >= 2
    assert len(fight.agents) == fight.header.agent_count
    # Real WvW log: at least one player (account_name present).
    players = [a for a in fight.agents if a.is_player]
    assert len(players) >= 1, f"no players detected among {len(fight.agents)} agents"
    for p in players:
        assert p.account_name is not None
        assert p.account_name, f"player {p.id} has empty account_name"
        # NOTE: we deliberately do NOT assert ``p.name`` here. Real
        # arcdps WvW logs can emit a player record with an empty
        # char-name buffer (the 68-byte name is fully null) but a
        # valid account_name. The account_name is the authoritative
        # player identifier; the char name is best-effort.
    for a in fight.agents:
        if not a.is_player:
            assert a.account_name is None
            assert a.subgroup is None
    # V1.3: skill count is at most the header's claim (the parser is
    # lenient and stops early on a corrupt skill record — a known
    # arcdps quirk where header.skill_count can exceed the actual
    # skill table size).
    assert len(fight.skills) <= fight.header.skill_count
    if fight.header.skill_count > 0:
        assert len(fight.skills) >= 1, (
            f"header claims {fight.header.skill_count} skills but parser read 0"
        )


# ---------------------------------------------------------------------------
# v0.10.2 hotfix followup #9: MAX_EVTC_BYTES cap in ``_read_all``
# ---------------------------------------------------------------------------


def test_read_all_under_cap_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.10.2 hotfix followup #9: a blob under the cap passes through ``_read_all``.

    The 100 MB real cap is monkeypatched down to 1 MB for the
    test (avoids allocating 100 MB real in test memory). A
    512 KB blob round-trips unchanged.
    """

    monkeypatch.setattr(parser_mod, "MAX_EVTC_BYTES", 1024 * 1024)
    data = b"x" * (512 * 1024)
    result = parser_mod._read_all(data)
    assert len(result) == len(data)
    assert result == data


def test_read_all_at_cap_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.10.2 hotfix followup #9: a blob exactly at the cap passes (inclusive).

    The cap is inclusive (the check is ``len(data) > MAX_EVTC_BYTES``,
    not ``>=``). A blob of exactly the cap size round-trips
    unchanged.
    """

    monkeypatch.setattr(parser_mod, "MAX_EVTC_BYTES", 1024)
    data = b"x" * 1024
    result = parser_mod._read_all(data)
    assert len(result) == 1024
    assert result == data


def test_read_all_over_cap_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.10.2 hotfix followup #9: a blob over the cap raises ``EvtcParseError``.

    The cap is exclusive (1 byte over the cap raises). The
    error message includes the actual size + the bound in MB
    + a remediation hint. The test pins the message content
    via ``pytest.raises(match=...)`` so a future regression
    that changes the message (e.g. removes the MB hint) fires.
    """

    monkeypatch.setattr(parser_mod, "MAX_EVTC_BYTES", 1024)
    data = b"x" * 1025
    with pytest.raises(EvtcParseError, match=r"1025 bytes.*exceeds safety bound.*0 MB") as exc_info:
        parser_mod._read_all(data)
    # The remediation hint points at the streaming API.
    assert "parse_events" in str(exc_info.value)
    assert "split the blob" in str(exc_info.value).lower()


def test_read_all_binary_io_over_cap_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.10.2 hotfix followup #9: a ``BinaryIO`` source over the cap raises.

    Mirrors the ``bytes`` over-cap test but with a ``BytesIO``
    source. The cap is checked AFTER the ``source.read()``
    call (Option A in the design -- see the ``_read_all``
    docstring), so the BinaryIO path goes through the same
    check as the bytes path.
    """

    monkeypatch.setattr(parser_mod, "MAX_EVTC_BYTES", 1024)
    data = BytesIO(b"x" * 1025)
    with pytest.raises(EvtcParseError, match=r"1025 bytes.*exceeds safety bound") as exc_info:
        parser_mod._read_all(data)
    assert "parse_events" in str(exc_info.value)


def test_parse_with_oversized_blob_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.10.2 hotfix followup #9: ``PythonEvtcParser.parse()`` propagates the cap.

    The cap is enforced at the ``_read_all`` chokepoint (both
    ``parse()`` and ``parse_events()`` go through it), so the
    cap is enforced exactly once per parse, not duplicated.
    This test pins the propagation through the public
    ``parse()`` API.
    """

    monkeypatch.setattr(parser_mod, "MAX_EVTC_BYTES", 1024)
    data = b"x" * 2048
    with pytest.raises(EvtcParseError, match=r"exceeds safety bound") as exc_info:
        list(PythonEvtcParser().parse(data))
    # The error message is caller-agnostic (doesn't distinguish
    # parse() vs parse_events()) so the streaming-API hint
    # makes sense for both surfaces.
    assert "parse_events" in str(exc_info.value)


def test_parse_events_with_oversized_blob_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.10.2 hotfix followup #9: ``PythonEvtcParser.parse_events()`` propagates the cap.

    Mirrors the ``parse()`` test for ``parse_events()``. The
    cap is enforced at the same ``_read_all`` chokepoint, so
    both public methods share the same protection.
    """

    monkeypatch.setattr(parser_mod, "MAX_EVTC_BYTES", 1024)
    data = b"x" * 2048
    with pytest.raises(EvtcParseError, match=r"exceeds safety bound") as exc_info:
        list(PythonEvtcParser().parse_events(data))
    assert "parse_events" in str(exc_info.value)


def test_max_evtc_bytes_constant_is_500_mb() -> None:
    """v0.10.25: the cap is 500 MB to accommodate large real-world WvW files.

    A 40 MB .zevtc file decompresses to ~221 MB, so the previous 100 MB
    cap rejected real fight logs. 500 MB matches the
    ``_MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE`` zip-bomb defence and
    accommodates the largest known WvW files with headroom. A future
    bump MUST update this test + the :data:`MAX_EVTC_BYTES` constant.
    """
    # ``MAX_EVTC_BYTES`` is now imported at top-of-file (v0.10.5 audit R2.3).
    assert MAX_EVTC_BYTES == 500 * 1024 * 1024
    assert MAX_EVTC_BYTES == 524_288_000


def test_max_evtc_bytes_matches_zip_bomb_defense() -> None:
    """v0.10.25 hardening: post-decompression cap == pre-extraction cap.

    Both safety bounds are intentionally equal (500 MB) by design:

    - ``_MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE`` (pre-extraction, in
      :func:`_first_entry`) rejects any zip entry whose **declared**
      uncompressed size exceeds the bound. This is the zip-bomb DoS
      defence: a 42-byte zip header can claim a 4 GB payload, so the
      check runs BEFORE ``ZipFile.read()`` materialises the bytes.
    - ``MAX_EVTC_BYTES`` (post-decompression, in :func:`_read_all`)
      rejects any blob whose **materialised** size exceeds the bound.
      This is the defence-in-depth backstop for streaming library
      consumers (CLI tools, notebooks, FaaS workers) who bypass the
      API-layer upload cap and could feed 1 GB+ blobs.

    The invariant ``MAX_EVTC_BYTES == _MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE``
    MUST hold because zip compression cannot EXPAND the payload beyond
    its declared uncompressed size: any entry whose declared size is
    <= the zip-bomb bound will decompress to bytes <= the
    post-decompression bound. If a future maintainer raises one cap
    without raising the other (e.g. +200 MB on MAX_EVTC_BYTES only, to
    accommodate a new streaming consumer), the check at
    ``_read_all`` becomes the only line of defence for that consumer
    and the zip-bomb check is bypassable. This test pins the
    relationship so a future delta is a CI-visible diff.
    """
    # ``_MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE`` is private (leading
    # underscore). We access via ``parser_mod`` (the hoisted import at
    # top-of-file per v0.10.5 audit R2.3 PLC0415) rather than adding
    # ``_MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE`` to the from-import list.
    # Keeping the explicit private access signals to future maintainers
    # that the constant is a module-internal invariant + not a public
    # API contract.
    assert parser_mod._MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE == parser_mod.MAX_EVTC_BYTES
    # Both are 500 MB. The literal 500 * 1024 * 1024 (not 500_000_000)
    # avoids confusion with decimal MB (the zip-bomb convention uses
    # binary MiB matching the byte counts in arcdps / GW2 tooling).
    assert parser_mod._MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE == 500 * 1024 * 1024
    assert parser_mod.MAX_EVTC_BYTES == 500 * 1024 * 1024
