"""Python reference implementation of the EVTC parser.

This implementation is intentionally minimal — V0 only reads:

* the 20-byte file header (``EVTC`` magic + ``yyyymmdd`` build date +
  revision byte + encounter_id + unused + ``agent_count`` u32),
* the agent table (``agent_count`` records of 96 bytes each).

Skill and event streams are left to later phases. The aim of V0 is to
prove the data pipeline end-to-end (given a real ``.zevtc`` file, the
CLI can list every player agent) without committing to the brittle
event-record layout prematurely.

CAVEAT (V0): the agent-record byte layout inside ``_AGENT_STRUCT``
(``<QII64s``) is best-effort and not aligned with the empirical arcdps
file layout. Names and professions of *real* WvW logs may read empty
or mis-mapped. Header parsing (magic, build_version, agent_count)
*is* accurate. A correct agent-record layout is the first task on the
Phase 2 backlog.

This module conforms to :class:`~gw2_evtc_parser.interface.EvtcParser`.
"""

from __future__ import annotations

import hashlib
import struct
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Final

from gw2_core import (
    Agent,
    EliteSpec,
    EvtcHeader,
    Fight,
    Profession,
    Skill,
)
from gw2_evtc_parser.exceptions import EvtcParseError

# ---------------------------------------------------------------------------
# Binary layout constants (V0 schema)
# ---------------------------------------------------------------------------

#: Total size of the EVTC file header + agent_count preamble in bytes.
#: Layout: magic(4) + build(8) + rev(1) + encounter_id(2) + unused(1) +
#: agent_count(I) = 20 bytes.
HEADER_SIZE: Final[int] = 20

#: ``struct`` format for the file header + agent_count.
#: Layout (little-endian): magic(4s) + build(8s) + rev(B) + encounter_id(H)
#: + unused(B) + agent_count(I).
_HEADER_STRUCT: Final[struct.Struct] = struct.Struct("<4s8sBHBI")

#: Byte offset of the agent_count field inside the header.
AGENT_COUNT_OFFSET: Final[int] = 16

#: Byte offset of the build date field inside the header.
BUILD_OFFSET: Final[int] = 4

#: Total size of one agent record in bytes.
AGENT_SIZE: Final[int] = 96

#: ``struct`` format for the fixed prefix of one agent record.
#: Layout (little-endian): id(Q) + profession(I) + elite(I) + name(64s).
_AGENT_STRUCT: Final[struct.Struct] = struct.Struct("<QII64s")

#: Sanity bound on agent_count to defend against pathological sources.
MAX_AGENTS: Final[int] = 10_000


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


class PythonEvtcParser:
    """Pure-Python, stateless implementation of :class:`EvtcParser`.

    Use as a singleton (``PythonEvtcParser()``) — it holds no state.
    """

    @staticmethod
    def supported_versions() -> frozenset[str]:
        """V0 supports any arcdps build date.

        The format has been ``stable-ish`` since 2017 at the byte offsets
        we read (header + agent table). We do not gate on the specific
        yyyymmdd; instead, we surface it in :attr:`EvtcHeader.build_version`.
        """
        return frozenset()

    @staticmethod
    def parse(source: BinaryIO | bytes) -> Iterator[Fight]:
        """Yield :class:`Fight` records from a raw EVTC binary stream.

        V0 yields exactly one Fight per file (arcdps logs record a single
        combat encounter).
        """
        data = _read_all(source)
        return _iter_fights(data)


# ---------------------------------------------------------------------------
# Module-private helpers
# ---------------------------------------------------------------------------


def _read_all(source: BinaryIO | bytes) -> bytes:
    """Coerce the source to raw ``bytes`` without materialising huge copies.

    For ``bytes``, we return a defensive copy so the caller can mutate
    the input. For ``BinaryIO`` we read everything once.
    """
    if isinstance(source, bytes):
        return bytes(source)
    if hasattr(source, "read"):
        return source.read()
    msg = f"Expected bytes or BinaryIO, got {type(source).__name__}"
    raise TypeError(msg)


def _iter_fights(data: bytes) -> Iterator[Fight]:
    """Parse the EVTC blob and yield a single :class:`Fight`."""
    if len(data) < HEADER_SIZE:
        raise EvtcParseError(f"EVTC blob is {len(data)} bytes, header needs {HEADER_SIZE}")

    magic, build, _rev, encounter_id, _unused, agent_count = _HEADER_STRUCT.unpack_from(data, 0)

    if magic != b"EVTC":
        raise EvtcParseError(f"Bad magic bytes: {magic!r} (expected b'EVTC')")

    try:
        build_str = build.decode("ascii")
    except UnicodeDecodeError as exc:
        raise EvtcParseError(f"Build bytes are not pure ASCII: {build!r}") from exc

    if agent_count > MAX_AGENTS:
        raise EvtcParseError(f"agent_count={agent_count} exceeds safety bound {MAX_AGENTS}")

    header = EvtcHeader(
        build_version=build_str,
        encounter_id=encounter_id,
        skill_count=0,
        agent_count=agent_count,
    )

    agents = list(_iter_agents(data, agent_count))
    skills: list[Skill] = []  # V0 stops before skill table.

    fight_id = hashlib.sha256(data).hexdigest()
    yield Fight(
        id=fight_id,
        header=header,
        agents=agents,
        skills=skills,
    )


def _iter_agents(data: bytes, count: int) -> Iterator[Agent]:
    """Read ``count`` agent records starting at offset ``HEADER_SIZE``."""
    if count == 0:
        return
    expected_size = count * AGENT_SIZE
    available = len(data) - HEADER_SIZE
    if available < expected_size:
        raise EvtcParseError(
            f"Need {expected_size} bytes for {count} agents, "
            f"only {available} available after header",
        )
    for i in range(count):
        offset = HEADER_SIZE + i * AGENT_SIZE
        yield _parse_agent(data, offset)


def _parse_agent(data: bytes, offset: int) -> Agent:
    """Decode a single 96-byte agent record."""
    agent_id, prof_raw, elite_raw, name_bytes = _AGENT_STRUCT.unpack_from(data, offset)
    name = name_bytes.split(b"\x00", 1)[0].decode("latin1", errors="replace")

    # ``is_player`` lives at byte 80 of the 96-byte agent record
    # (the field immediately after the 64-byte name region).
    is_player_byte = data[offset + 80]
    is_player = is_player_byte != 0

    try:
        profession = Profession(prof_raw)
    except ValueError:
        profession = Profession.UNKNOWN

    try:
        elite = EliteSpec(elite_raw)
    except ValueError:
        elite = EliteSpec.UNKNOWN

    return Agent(
        id=agent_id,
        name=name,
        profession=profession,
        elite=elite,
        elite_raw=elite_raw,
        is_player=is_player,
    )


# ---------------------------------------------------------------------------
# Public helpers (used by CLI and downstream packages)
# ---------------------------------------------------------------------------


def read_zevtc_archive(path: Path) -> bytes:
    """Open a ``.zevtc`` (zip) and return the inner EVTC blob.

    The inner file is conventionally named ``fight.evtc`` or — for newer
    arcdps releases — the timestamp string (e.g. ``20251002-213519``).
    We read whichever entry is first.
    """
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            if not names:
                raise EvtcParseError(f"{path} is an empty zip")
            return zf.read(names[0])
    except zipfile.BadZipFile as exc:
        raise EvtcParseError(f"{path} is not a valid zip archive: {exc}") from exc


# Re-export the public header for downstream imports.
__all__ = [
    "AGENT_SIZE",
    "HEADER_SIZE",
    "PythonEvtcParser",
    "read_zevtc_archive",
]
