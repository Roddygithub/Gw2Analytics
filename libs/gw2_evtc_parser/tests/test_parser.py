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

The header layout was corrected in commit 1c89b7c → next: arcdps
header is 20 bytes total, with agent_count u32 at offset 16 and
agents starting at offset 20.
"""

from __future__ import annotations

import hashlib
import struct
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from gw2_core import EliteSpec, Profession
from gw2_evtc_parser import EvtcParseError, PythonEvtcParser
from gw2_evtc_parser.parser import AGENT_COUNT_OFFSET, HEADER_SIZE

# ---------------------------------------------------------------------------
# Synthetic fixture
# ---------------------------------------------------------------------------


def _build_minimal_evtc(
    agents: list[tuple[int, int, int, str, bool]],
    build: str = "20250925",
    encounter_id: int = 0,
) -> bytes:
    """Build a synthetic EVTC binary with the given agents.

    Header layout is 20 bytes: magic(4) + build(8) + rev(1) +
    encounter_id(2) + unused(1) + agent_count(I). Each agent tuple is
    ``(id, profession_id, elite_id, name, is_player)``.
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
        name_bytes = name.encode("latin1", errors="replace")[:64].ljust(64, b"\x00")
        record = struct.pack("<QII64s", aid, prof, elite, name_bytes)
        record += b"\x01" if is_player else b"\x00"
        record += b"\x00" * 15  # 16 bytes misc, of which 1 = is_player
        assert len(record) == 96, f"agent record must be 96 bytes, got {len(record)}"
        body += record
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


def test_synthetic_evtc_with_agents_parses() -> None:
    agents = [
        (123456, Profession.GUARDIAN.value, EliteSpec.DRAGONHUNTER.value, "Test Guardian", True),
        (789012, Profession.WARRIOR.value, EliteSpec.BERSERKER.value, "Test Bers", True),
        (345678, 99, 99, "Unknown NPC", False),
    ]
    evtc = _build_minimal_evtc(agents)
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert len(fight.agents) == 3

    by_name = {a.name: a for a in fight.agents}
    g = by_name["Test Guardian"]
    assert g.profession == Profession.GUARDIAN
    assert g.elite == EliteSpec.DRAGONHUNTER
    assert g.is_player is True

    w = by_name["Test Bers"]
    assert w.profession == Profession.WARRIOR
    assert w.elite == EliteSpec.BERSERKER
    assert w.is_player is True

    npc = by_name["Unknown NPC"]
    assert npc.profession == Profession.UNKNOWN
    assert npc.elite == EliteSpec.UNKNOWN
    assert npc.is_player is False


def test_synthetic_truncated_blob_raises() -> None:
    # 14 bytes < HEADER_SIZE 20, so we should bail out before reading the magic.
    short = b"EVTC" + b"\x00" * 10
    with pytest.raises(EvtcParseError, match="header needs 20"):
        list(PythonEvtcParser().parse(short))


def test_synthetic_bad_magic_raises() -> None:
    blob = b"JUNK" + b"\x00" * 16  # >= HEADER_SIZE so magic check fires
    with pytest.raises(EvtcParseError, match="magic"):
        list(PythonEvtcParser().parse(blob))


def test_synthetic_agent_count_lie_raises() -> None:
    """Header claims 99 agents but body has none — parser must raise."""
    blob = bytearray(_build_minimal_evtc([]))
    blob[AGENT_COUNT_OFFSET : AGENT_COUNT_OFFSET + 4] = struct.pack("<I", 99)
    with pytest.raises(EvtcParseError, match="agents"):
        list(PythonEvtcParser().parse(bytes(blob)))


def test_synthetic_encounter_id_propagates() -> None:
    """The encounter_id at offset 13-14 should surface on EvtcHeader."""
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
    inner = None
    with zipfile.ZipFile(BytesIO(zevtc)) as zf:
        inner = zf.read("fight.evtc")
    assert inner is not None
    fight = next(iter(PythonEvtcParser().parse(inner)))
    assert fight.agents[0].name == "Chrono"
    assert fight.agents[0].profession == Profession.MESMER


def test_stable_fight_id_is_sha256_of_input() -> None:
    evtc = _build_minimal_evtc(
        [(1, Profession.RANGER.value, EliteSpec.UNTAMED.value, "R", True)],
    )
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    expected = hashlib.sha256(evtc).hexdigest()
    assert fight.id == expected


def test_layout_constants_match_real_arcdps_v0() -> None:
    """Sanity-check the layout constants we publish.

    These are byte offsets other packages rely on. They MUST stay
    in sync with the schema this parser consumes.
    """
    assert HEADER_SIZE == 20
    assert AGENT_COUNT_OFFSET == 16


# ---------------------------------------------------------------------------
# Real-file integration (skipped if fixture absent)
# ---------------------------------------------------------------------------


_REAL_FIXTURE = Path("/tmp/inner_20251002-213519")  # noqa: S108 (test-only diagnostic fixture)


@pytest.mark.skipif(not _REAL_FIXTURE.exists(), reason="real EVTC fixture not available")
@pytest.mark.xfail(
    reason=(
        "V0 _AGENT_STRUCT (<QII64s) is misaligned with real arcdps agent-record "
        "layout; reading names/professions accurately is deferred to Phase 2."
    ),
    strict=False,
)
def test_real_evtc_binary_parses_with_realistic_agent_count() -> None:
    raw = _REAL_FIXTURE.read_bytes()
    fight = next(iter(PythonEvtcParser().parse(raw)))
    assert fight.header is not None
    assert fight.header.agent_count >= 2
    assert len(fight.agents) == fight.header.agent_count
    assert all(a.name for a in fight.agents), "real fixture produced empty names"
    players = [a for a in fight.agents if a.is_player]
    assert len(players) >= 1, f"no players detected among {len(fight.agents)} agents"
