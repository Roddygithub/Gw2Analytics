"""Python reference implementation of the EVTC parser.

This implementation reads:

* the 20-byte file header (``EVTC`` magic + ``yyyymmdd`` build date +
  revision byte + encounter_id + unused + ``agent_count`` u32),
* ``agent_count`` **fixed-size** agent records of 96 bytes each,
  matching the C ``struct ag`` in ``arcdps.h`` exactly:

    +-----+--------+--------------------------------------------+
    | off | size   | field                                      |
    +-----+--------+--------------------------------------------+
    |  0  |  Q     | id (uint64)                                |
    |  8  |  I     | profession (uint32)                        |
    | 12  |  I     | is_elite (uint32)                          |
    | 16  |  H     | toughness (uint16)                         |
    | 18  |  H     | concentration (uint16)                     |
    | 20  |  H     | healing (uint16)                           |
    | 22  |  H     | hitbox_width (uint16)                      |
    | 24  |  H     | condition (uint16)                         |
    | 26  |  H     | hitbox_padding (uint16)                    |
    | 28  |  68s   | name (null-padded 68-byte buffer)          |
    +-----+--------+--------------------------------------------+

  The 68-byte ``name`` buffer holds the *combo string* for player
  agents (``"char_name\\0:account_name\\0subgroup\\0"`` null-padded to
  68 bytes) and a single null-terminated string for NPCs. The parser
  splits the buffer on null bytes; presence of a second non-empty
  part marks the agent as a player.

  The V0/V1 assumption that the on-disk record is variable-size (the
  name ends at the *first* null and the cursor advances just past
  it) was incorrect: the in-memory struct is fixed, and arcdps
  serialises the whole 96-byte block including the trailing nulls.
  Trying to walk variable offsets loses alignment on the next
  record.

Skill and event streams are left to later phases.

This module conforms to :class:`~gw2_evtc_parser.interface.EvtcParser`.
"""

from __future__ import annotations

import hashlib
import io
import logging
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

# Module-level logger for soft warnings (e.g. unrecognised arcdps
# account_name format). Library consumers control verbosity via the
# standard ``logging`` configuration; we do not call ``basicConfig``.
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Binary layout constants
# ---------------------------------------------------------------------------

#: Total size of the EVTC file header + agent_count preamble in bytes.
HEADER_SIZE: Final[int] = 20

#: ``struct`` format for the file header + agent_count.
_HEADER_STRUCT: Final[struct.Struct] = struct.Struct("<4s8sBHBI")

#: Byte offset of the agent_count field inside the header.
AGENT_COUNT_OFFSET: Final[int] = 16

#: Byte offset of the build date field inside the header.
BUILD_OFFSET: Final[int] = 4

#: Total size of one agent record on disk (the C ``struct ag`` size).
AGENT_SIZE: Final[int] = 96

#: Size of the 28-byte fixed prefix that starts every agent record.
AGENT_PREFIX_SIZE: Final[int] = 28

#: Size of the 68-byte name buffer that ends every agent record.
AGENT_NAME_SIZE: Final[int] = AGENT_SIZE - AGENT_PREFIX_SIZE

#: ``struct`` format for the entire 96-byte agent record.
#: Layout (little-endian): id(Q) + prof(I) + elite(I) + six uint16s +
#: 68-byte name buffer.
_AGENT_STRUCT: Final[struct.Struct] = struct.Struct(f"<QIIhhhhhh{AGENT_NAME_SIZE}s")

#: Sanity bound on agent_count to defend against pathological sources.
MAX_AGENTS: Final[int] = 10_000

#: arcdps account-name soft signal. Real arcdps revisions usually
#: prefix account strings with ``:``; we surface ``account_name``
#: verbatim and let downstream code decide whether the leading ``:``
#: is present (an empty account_name is also valid).
ACCOUNT_NAME_PREFIX: Final[bytes] = b":"


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


class PythonEvtcParser:
    """Pure-Python, stateless implementation of :class:`EvtcParser`.

    Use as a singleton (``PythonEvtcParser()``) — it holds no state.
    """

    @staticmethod
    def supported_versions() -> frozenset[str]:
        """Any arcdps build date with the 96-byte agent-record layout."""
        return frozenset()

    @staticmethod
    def parse(source: BinaryIO | bytes) -> Iterator[Fight]:
        """Yield :class:`Fight` records from a raw EVTC binary stream.

        Yields exactly one Fight per file. The bytes passed in must be
        the *inner* EVTC blob — use :func:`read_zevtc_archive` or
        :func:`read_zevtc_bytes` to unwrap a ``.zevtc`` zip first.
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
    skills: list[Skill] = []  # V1 stops before skill table.

    fight_id = hashlib.sha256(data).hexdigest()
    yield Fight(
        id=fight_id,
        header=header,
        agents=agents,
        skills=skills,
    )


def _iter_agents(data: bytes, count: int) -> Iterator[Agent]:
    """Read ``count`` fixed-size 96-byte agent records starting at ``HEADER_SIZE``."""
    if count == 0:
        return
    cursor = HEADER_SIZE
    end = len(data)
    for _ in range(count):
        if cursor + AGENT_SIZE > end:
            raise EvtcParseError(
                f"Truncated agent record at offset {cursor}: "
                f"need {AGENT_SIZE} bytes, only {end - cursor} available",
            )
        yield _decode_agent(data, cursor)
        cursor += AGENT_SIZE


def _decode_agent(data: bytes, offset: int) -> Agent:
    """Decode a single 96-byte agent record at ``offset``."""
    aid, prof_raw, elite_raw, _tough, _conc, _heal, _width, _cond, _pad, name_buf = (
        _AGENT_STRUCT.unpack_from(data, offset)
    )

    # Split the 68-byte name buffer on null bytes. arcdps writes the
    # combo string ``char\0acc\0sub\0`` null-padded to 68 bytes for
    # players, and a single ``name\0`` null-padded for NPCs.
    parts = name_buf.split(b"\x00")

    # ``split`` always returns at least one element (the empty string
    # if the buffer is all nulls); a fully-null buffer means "no name".
    char_name = parts[0].decode("utf-8", errors="replace") if parts else ""

    # A record is a player if either the account_name (parts[1]) is
    # non-empty OR a non-empty subgroup (parts[2]) is present after an
    # empty account_name. Both empty means NPC. The "empty
    # account_name + non-empty subgroup" branch covers a real arcdps
    # WvW edge case where a player's account was not captured but
    # their squad position was. The "both empty" case is
    # fundamentally indistinguishable from an NPC, so we classify as
    # NPC.
    raw_account = parts[1] if len(parts) >= 2 else b""
    raw_subgroup = parts[2] if len(parts) >= 3 else b""
    is_player = bool(raw_account or raw_subgroup)
    account_name: str | None = None
    subgroup: str | None = None
    if is_player:
        if raw_account and not raw_account.startswith(ACCOUNT_NAME_PREFIX):
            logger.debug(
                "Player account_name lacks %r prefix (arcdps-version variation): %r",
                ACCOUNT_NAME_PREFIX,
                raw_account,
            )
        account_name = raw_account.decode("utf-8", errors="replace") if raw_account else None
        # subgroup is the 3rd part. An empty raw_subgroup means
        # arcdps wrote ``\0\0`` (no subgroup); surface as the empty
        # string so callers can distinguish from a missing subgroup.
        subgroup = raw_subgroup.decode("utf-8", errors="replace")

    try:
        profession = Profession(prof_raw)
    except ValueError:
        profession = Profession.UNKNOWN

    try:
        elite = EliteSpec(elite_raw)
    except ValueError:
        elite = EliteSpec.UNKNOWN

    return Agent(
        id=aid,
        name=char_name,
        profession=profession,
        elite=elite,
        elite_raw=elite_raw,
        is_player=is_player,
        account_name=account_name,
        subgroup=subgroup,
    )


# ---------------------------------------------------------------------------
# Public helpers (used by CLI and downstream packages)
# ---------------------------------------------------------------------------


def _first_entry(zf: zipfile.ZipFile) -> bytes:
    """Return the bytes of the first entry in an open zip."""
    names = zf.namelist()
    if not names:
        raise EvtcParseError("zevtc has no entries (empty zip)")
    return zf.read(names[0])


def read_zevtc_archive(path: Path) -> bytes:
    """Open a ``.zevtc`` (zip) on disk and return the inner EVTC blob.

    The inner file is conventionally named ``fight.evtc`` or — for newer
    arcdps releases — the timestamp string (e.g. ``20251002-213519``).
    We read whichever entry is first.
    """
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return _first_entry(zf)
    except zipfile.BadZipFile as exc:
        raise EvtcParseError(f"{path} is not a valid zip archive: {exc}") from exc


def read_zevtc_bytes(data: bytes) -> bytes:
    """Open an in-memory ``.zevtc`` (zip) blob and return its inner EVTC.

    Bytes-equivalent of :func:`read_zevtc_archive`. Use when callers
    already hold the zip bytes (FastAPI upload handlers, FaaS payloads,
    CLI stdin). Reads the first entry — arcdps ``.zevtc`` files always
    contain exactly one. ``zipfile.is_zipfile`` is used to discriminate
    so we accept zip64 / PK\\x05\\x06 archives too.
    """
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise EvtcParseError("not a valid .zevtc zip archive")
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        return _first_entry(zf)


# Re-export the public header for downstream imports.
__all__ = [
    "ACCOUNT_NAME_PREFIX",
    "AGENT_COUNT_OFFSET",
    "AGENT_NAME_SIZE",
    "AGENT_PREFIX_SIZE",
    "AGENT_SIZE",
    "BUILD_OFFSET",
    "HEADER_SIZE",
    "MAX_AGENTS",
    "PythonEvtcParser",
    "read_zevtc_archive",
    "read_zevtc_bytes",
]
