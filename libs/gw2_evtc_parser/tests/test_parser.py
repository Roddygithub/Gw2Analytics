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
"""

from __future__ import annotations

import hashlib
import struct
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from gw2_core import EliteSpec, Profession
from gw2_evtc_parser import EvtcParseError, PythonEvtcParser, read_zevtc_bytes
from gw2_evtc_parser.parser import (
    ACCOUNT_NAME_PREFIX,
    AGENT_COUNT_OFFSET,
    AGENT_NAME_SIZE,
    AGENT_PREFIX_SIZE,
    AGENT_SIZE,
    HEADER_SIZE,
)

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

    The 68-byte name buffer is filled with the combo string
    (player) or single name (NPC) null-padded to 68 bytes. arcdps
    fills the full buffer unconditionally, so we mirror that.
    """
    prefix = struct.pack(
        "<QIIhhhhhh",
        agent_id,
        prof,
        elite,
        0,  # toughness
        0,  # concentration
        0,  # healing
        0,  # hitbox_width
        0,  # condition
        0,  # hitbox_padding
    )
    if account_name is None:
        # NPC: single null-terminated string, null-padded to 68 bytes.
        raw = name.encode("utf-8") + b"\x00"
    else:
        if not account_name.startswith(":"):
            msg = f"account_name must start with {ACCOUNT_NAME_PREFIX!r}"
            raise ValueError(msg)
        raw = name.encode("utf-8") + b"\x00" + account_name.encode("utf-8") + b"\x00"
        if subgroup is not None:
            raw += subgroup.encode("utf-8") + b"\x00"
        else:
            raw += b"\x00"
    if len(raw) > AGENT_NAME_SIZE:
        msg = f"name region {len(raw)} bytes exceeds {AGENT_NAME_SIZE}"
        raise ValueError(msg)
    # Null-pad to exactly 68 bytes.
    name_buf = raw + b"\x00" * (AGENT_NAME_SIZE - len(raw))
    assert len(name_buf) == AGENT_NAME_SIZE
    return prefix + name_buf


def _build_minimal_evtc(
    agents: list[tuple[int, int, int, str, bool]],
    build: str = "20250925",
    encounter_id: int = 0,
) -> bytes:
    """Build a synthetic EVTC binary with the given agents.

    Header layout is 20 bytes (see :data:`HEADER_SIZE`). Each agent
    tuple is ``(id, profession_id, elite_id, name, is_player)``. For
    is_player=True agents, a default account_name of ``:synth.<id>`` and
    no subgroup is added. NPCs have no account/subgroup.
    """
    if len(build) != 8:
        msg = f"build must be exactly 8 ASCII chars (yyyymmdd), got {len(build)}"
        raise ValueError(msg)
    header = struct.pack(
        "<4s8sBHBI",
        b"EVTC",
        build.encode("ascii"),
        0,
        encounter_id,
        0,
        len(agents),
    )
    body = bytearray()
    for aid, prof, elite, name, is_player in agents:
        if is_player:
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
    assert fight.header.build_version == "20250925"
    assert fight.header.agent_count == 0
    assert fight.header.skill_count == 0
    assert fight.header.encounter_id == 0
    assert fight.agents == []
    assert fight.skills == []


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
    with pytest.raises(EvtcParseError, match="header needs 20"):
        list(PythonEvtcParser().parse(short))


def test_synthetic_bad_magic_raises() -> None:
    blob = b"JUNK" + b"\x00" * 16
    with pytest.raises(EvtcParseError, match="magic"):
        list(PythonEvtcParser().parse(blob))


def test_synthetic_truncated_agent_prefix_raises() -> None:
    """Header claims 1 agent but there is no AGENT_SIZE bytes after the header."""
    header = struct.pack("<4s8sBHBI", b"EVTC", b"20250925", 0, 0, 0, 1)
    blob = header + b"\x00" * 50  # only 50 bytes after header (need 96)
    with pytest.raises(EvtcParseError, match="Truncated agent record"):
        list(PythonEvtcParser().parse(blob))


def test_synthetic_agent_count_lie_raises() -> None:
    """Header claims 99 agents but body has none — first iteration truncates."""
    header = struct.pack("<4s8sBHBI", b"EVTC", b"20250925", 0, 0, 0, 99)
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


def test_layout_constants_match_arcdps_v1() -> None:
    """Sanity-check the layout constants we publish."""
    assert HEADER_SIZE == 20
    assert AGENT_COUNT_OFFSET == 16
    assert AGENT_PREFIX_SIZE == 28
    assert AGENT_NAME_SIZE == 68
    assert AGENT_SIZE == 96


def test_account_name_without_colon_is_accepted_as_player() -> None:
    """A 'player' record whose account_name lacks ``:`` is *not* an error in V1.

    Real arcdps revisions have emitted bare account ids (e.g. ``b'2'``)
    and we accept them. The 3-part combo structure is the authoritative
    player signal; the leading ``:`` is a soft convention we surface
    as ``logger.debug`` rather than reject.
    """
    rec = struct.pack("<QIIhhhhhh", 1, 0, 0, 0, 0, 0, 0, 0, 0)
    # b"Name\x00no_colon\x00\x00" is 4 + 1 + 8 + 1 + 1 = 15 bytes.
    name_raw = b"Name\x00no_colon\x00\x00"
    assert len(name_raw) == 15
    name_buf = name_raw + b"\x00" * (AGENT_NAME_SIZE - len(name_raw))
    blob = rec + name_buf
    assert len(blob) == AGENT_SIZE
    header = struct.pack("<4s8sBHBI", b"EVTC", b"20250925", 0, 0, 0, 1)
    fight = next(iter(PythonEvtcParser().parse(header + blob)))
    a = fight.agents[0]
    assert a.is_player is True
    assert a.name == "Name"
    assert a.account_name == "no_colon"
    assert a.subgroup == ""


def test_player_with_empty_account_name_and_subgroup() -> None:
    """Real arcdps WvW edge case: account_name is empty but subgroup is set.

    arcdps writes the combo string ``char\0\0sub\0`` for a player
    whose account was not captured but whose squad position was.
    The parser must classify this as a player (not an NPC) and
    surface ``account_name=None`` while preserving the subgroup.
    """
    rec = struct.pack("<QIIhhhhhh", 1, 0, 0, 0, 0, 0, 0, 0, 0)
    # b"Name\x00\x00sub\x00" is 4 + 1 + 1 + 3 + 1 = 10 bytes.
    name_raw = b"Name\x00\x00sub\x00"
    assert len(name_raw) == 10
    name_buf = name_raw + b"\x00" * (AGENT_NAME_SIZE - len(name_raw))
    blob = rec + name_buf
    assert len(blob) == AGENT_SIZE
    header = struct.pack("<4s8sBHBI", b"EVTC", b"20250925", 0, 0, 0, 1)
    fight = next(iter(PythonEvtcParser().parse(header + blob)))
    a = fight.agents[0]
    assert a.is_player is True
    assert a.name == "Name"
    assert a.account_name is None
    assert a.subgroup == "sub"


def test_npc_with_fully_null_tail_after_name_is_npc() -> None:
    """A record with only a char name and null padding is an NPC.

    This is fundamentally indistinguishable from "player with empty
    account_name AND empty subgroup"; we treat it as NPC. The
    previous edge-case test covers the recoverable case (subgroup
    set after empty account).
    """
    rec = struct.pack("<QIIhhhhhh", 1, 0, 0, 0, 0, 0, 0, 0, 0)
    name_buf = b"Mob\x00" + b"\x00" * (AGENT_NAME_SIZE - 4)
    blob = rec + name_buf
    assert len(blob) == AGENT_SIZE
    header = struct.pack("<4s8sBHBI", b"EVTC", b"20250925", 0, 0, 0, 1)
    fight = next(iter(PythonEvtcParser().parse(header + blob)))
    a = fight.agents[0]
    assert a.is_player is False
    assert a.name == "Mob"
    assert a.account_name is None
    assert a.subgroup is None


# ---------------------------------------------------------------------------
# read_zevtc_bytes
# ---------------------------------------------------------------------------


def test_read_zevtc_bytes_extracts_inner_evtc() -> None:
    inner = _build_minimal_evtc([])
    zevtc = _wrap_zevtc(inner)
    assert read_zevtc_bytes(zevtc) == inner
    fight = next(iter(PythonEvtcParser().parse(read_zevtc_bytes(zevtc))))
    assert fight.header is not None
    assert fight.header.build_version == "20250925"


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
        # arcdps' standard convention starts with ':'; accept any non-empty string
        # because some revisions emit bare ids.
        assert p.account_name, f"player {p.id} has empty account_name"
        # Real names: no longer empty
        assert p.name, f"player {p.id} has empty name"
    # NPCs (if any) have no account
    for a in fight.agents:
        if not a.is_player:
            assert a.account_name is None
            assert a.subgroup is None
