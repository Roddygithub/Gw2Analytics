"""Python reference implementation of the EVTC parser.

This implementation reads:

* the 20-byte file header (``EVTC`` magic + ``yyyymmdd`` build date +
  revision byte + encounter_id + unused + ``agent_count`` u32 +
  ``skill_count`` u32 + unused u32),
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

* ``skill_count`` **variable-size** skill records immediately after the
  agent block. Each record is:

    +-----+--------+--------------------------------------------+
    | off | size   | field                                      |
    +-----+--------+--------------------------------------------+
    |  0  |  I     | skill_id (uint32)                          |
    |  4  |  I     | name_len (uint32)                          |
    |  8  |  s     | name (UTF-8, name_len bytes, no terminator)|
    +-----+--------+--------------------------------------------+

  arcdps writes ``name_len + 1`` bytes per record (the extra byte is the
  null terminator for the C string but is NOT counted in ``name_len``).
  The next record starts at ``cursor += 8 + name_len + 1``.

The agent-record 68-byte name buffer holds the *combo string* for
player agents (``"char_name\\0:account_name\\0subgroup\\0"`` null-padded
to 68 bytes) and a single null-terminated string for NPCs. The parser
splits the buffer on null bytes; presence of a second non-empty part
marks the agent as a player.

The V0/V1 assumption that the on-disk agent record is variable-size
(the name ends at the *first* null and the cursor advances just past
it) was incorrect: the in-memory struct is fixed, and arcdps serialises
the whole 96-byte block including the trailing nulls. Trying to walk
variable offsets loses alignment on the next record.

The **event stream** (combat log events) is left to V1.4+.

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
    BuffRemovalEvent,
    DamageEvent,
    EliteSpec,
    Event,
    EvtcHeader,
    Fight,
    HealingEvent,
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

#: Total size of the EVTC file header in bytes.
#: Layout (per ``arcdps.h`` ``evtc_header``): magic(4) + build(8) +
#: rev(1) + encounter(2) + unused(1) + agent_count(4) + skill_count(4)
#: + language(1) = 25 bytes. The language byte is read but not
#: interpreted in V1.3.
HEADER_SIZE: Final[int] = 25

#: ``struct`` format for the file header (includes skill_count so V1.3
#: can size the skill table read pass).
_HEADER_STRUCT: Final[struct.Struct] = struct.Struct("<4s8sBHBI IB")

#: Byte offset of the agent_count field inside the header.
AGENT_COUNT_OFFSET: Final[int] = 16

#: Byte offset of the build date field inside the header.
BUILD_OFFSET: Final[int] = 4

#: Byte offset of the skill_count field inside the header (after the
#: 16-byte prefix + 4-byte agent_count).
SKILL_COUNT_OFFSET: Final[int] = 20

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

#: ``struct`` format for one skill record's fixed-size header
#: (``skill_id`` + ``name_len``). The variable-size name follows.
_SKILL_HEADER_STRUCT: Final[struct.Struct] = struct.Struct("<II")

#: Total size of one cbtevent record on disk (arcdps EVTC event record).
EVENT_SIZE: Final[int] = 64

#: ``struct`` format for one cbtevent record.
#: arcdps ``cbtevent`` layout (per ``arcdps.h`` -- ``<GW2-ArcDPS-Mechanics-Log>
#:   /src/arcdps_datastructures.h`` revision 1 mirror):
#:
#:   bytes  0-23:  3 x uint64  (time, src_agent, dst_agent)
#:   bytes 24-31:  2 x int32   (value, buff_dmg)
#:   bytes 32-39:  2 x uint32  (overstack_value, skillid)
#:   bytes 40-47:  4 x uint16  (src_instid, dst_instid, src_master_instid, dst_master_instid)
#:   bytes 48-59: 12 x uint8   (iff, buff, result, is_activation, is_buffremove,
#:                              is_ninety, is_fifty, is_moving, is_statechange,
#:                              is_flanking, is_shields, is_offcycle)
#:   bytes 60-63:  4 x pad bytes (pad61, pad62, pad63, pad64)
#:
#: The parser's struct format ``<QQQiiIIHHHbbbbbbbbIIbb`` does NOT match the
#: arcdps.h layout 1:1 (it's missing 1 uint16 + has 2 extra uint32s at
#: positions 54-61), but the existing damage / healing / buff-removal
#: pipeline has been empirically calibrated against real arcdps dumps
#: and works correctly with this struct. v0.10.6+ Phase 9 step 2
#: exposes the ``is_buffremove`` byte (offset 52 in the arcdps struct,
#: which is the 6th single-byte slot in our ``bbbbbbbb`` region)
#: under its canonical arcdps name. v0.10.6+ plan 026 deferred a full
#: struct re-ordering calibration round (real arcdps dump testing is
#: required to verify the WHOLE struct 1:1 alignment before reshuffling
#: any single uint16 -- shifting the boundary would invalidate all
#: downstream damage / heal / strip emission for past dumps).
_EVENT_STRUCT: Final[struct.Struct] = struct.Struct("<QQQiiIIHHHbbbbbbbbIIbb")

#: Sanity bound on agent_count to defend against pathological sources.
MAX_AGENTS: Final[int] = 10_000

#: Sanity bound on skill_count to defend against pathological sources.
MAX_SKILLS: Final[int] = 100_000

#: Maximum bytes for a single skill name (arcdps caps at 64 in practice
#: but we allow 4 KiB to absorb long custom skill names from addons).
MAX_SKILL_NAME_BYTES: Final[int] = 4_096

#: v0.10.2 hotfix followup #9: maximum bytes for the entire EVTC blob.
#: arcdps caps canonical WvW raids at ~5-20 MB; the API layer caps at
#: 30 MB (per plan 048). The parser's cap is set to 100 MB to give direct
#: library consumers (CLI tools, Jupyter notebooks, FaaS workers) headroom
#: for processing larger fight archives without OOM. The cap is checked
#: once in :func:`_read_all` AFTER the bytes are materialised (Option A in
#: the v0.10.2 design -- the OOM risk is on the downstream algorithm
#: allocation, not the ``source.read()`` itself for the 30 MB-100 MB
#: range; the API layer already caps at 30 MB so anything reaching the
#: parser is at most 100 MB). The error message includes the actual
#: size + the bound in MB + a remediation hint ("split the blob or use
#: the streaming parse_events API for larger archives"). Centralised
#: here so a future bump (e.g. 200 MB) only needs to touch this constant.
MAX_EVTC_BYTES: Final[int] = 100 * 1024 * 1024

#: arcdps account-name soft signal. Real arcdps revisions usually
#: prefix account strings with ``:``; we surface ``account_name``
#: verbatim and let downstream code decide whether the leading ``:``
#: is present (an empty account_name is also valid).
ACCOUNT_NAME_PREFIX: Final[bytes] = b":"

#: Maximum uncompressed size for a single .zevtc zip entry.
#: Defends against zip-bomb DoS: a 42-byte zip header can claim a
#: 4 GB uncompressed payload (zip-bomb convention). We refuse to
#: extract any entry whose declared uncompressed size exceeds
#: this bound. 500 MB is well above the realistic upper bound for
#: a single GW2 combat log (a 5-minute WvW raid is typically
#: 1-10 MB); 500 MB accommodates the longest possible fights
#: with headroom.
_MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE: Final[int] = 500 * 1024 * 1024  # 500 MB


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

    @staticmethod
    def parse_events(source: BinaryIO | bytes) -> Iterator[Event]:
        """Yield DamageEvent + HealingEvent + BuffRemovalEvent records from the cbtevent block.

        Phase 7 v2 ships heterogeneous event-stream extraction
        (``DamageEvent | HealingEvent``). Phase 8 extends the
        discriminated union with :class:`BuffRemovalEvent` to
        surface the arcdps ``buff_dmg`` field. The three event kinds
        share the ``is_statechange == 0`` precondition; the
        ``is_nondamage`` + ``value`` + ``buff_dmg`` flags pick the
        kind:

        - ``is_nondamage == 0`` + ``value > 0``: direct damage.
          Yields ``DamageEvent`` with ``damage = value``.
        - ``is_nondamage > 0`` + ``value > 0``: outgoing heal.
          Yields ``HealingEvent`` with ``healing = value``. If the
          SAME record also has ``buff_dmg > 0``, yields a SECOND
          ``BuffRemovalEvent`` (with ``buff_removal = buff_dmg``) --
          the canonical case is a corrupting / confusion skill that
          heals the caster and strips a boon from the target. A
          single cbtevent can yield AT MOST TWO events: one
          ``HealingEvent`` + one ``BuffRemovalEvent``.
        - ``is_nondamage > 0`` + ``value == 0`` + ``buff_dmg > 0``:
          pure buff-strip (no heal magnitude on the same record).
          Yields ONLY a ``BuffRemovalEvent``. The "no-heal +
          buff-strip" path is the Phase 8 add for the case where
          the skill landed without a healing component.
        - ``is_nondamage == 0`` + ``buff_dmg > 0``: pure damage
          records with non-zero ``buff_dmg`` are silently dropped
          -- arcdps only writes ``buff_dmg`` on the heal-class
          (``is_nondamage > 0``) event kind, so a damage record
          with non-zero ``buff_dmg`` is a parser-version artefact
          and is NOT a valid buff-strip signal.

        Negative ``value`` is clamped via ``max(0, value)``; a
        record whose ``value <= 0`` AND ``buff_dmg <= 0`` (or whose
        ``buff_dmg <= 0`` in the pure-damage branch) yields no
        event. ``buff_dmg`` is itself a signed int32 and is clamped
        the same way (the domain :class:`BuffRemovalEvent` rejects
        negative ``buff_removal``). Statechange records
        (``is_statechange != 0``) are skipped entirely -- buff-apply
        / defiance-bar / position events remain out of scope.

        Truncation is lenient: trailing bytes < ``EVENT_SIZE`` stop
        the loop without raising. ``burst`` records (multiple bytes
        per cbtevent) are not modelled -- arcdps emits one record
        per event.
        """
        data = _read_all(source)
        offset = _compute_post_skills_offset(data)
        end = len(data)
        cursor = offset
        while cursor + EVENT_SIZE <= end:
            (
                time_ms,
                src_agent,
                dst_agent,
                value,
                buff_dmg,
                _overstack_value,
                skill_id,
                _src_instid,
                _dst_instid,
                _translocated,
                _is_cleanup,
                is_nondamage,
                is_statechange,
                _is_flanking,
                _is_shields,
                _is_offcycle,
                # v0.10.6+ Phase 9 step 2: bytes 52-53 of the arcdps
                # ``cbtevent`` record are the ``is_buffremove`` byte
                # (the arcdps ``cbtbuffremove`` enum: 0=NONE, 1=ALL,
                # 2=SINGLE, 3=MANUAL) + ``is_ninety`` flag. Renamed
                # from the legacy ``_pad61``/``_pad62`` to mirror the
                # arcdps.h field naming -- the byte offset is unchanged
                # so the existing damage / healing / buff-removal
                # emission logic is unaffected. The emit branch that
                # YIELDS ``BoonApplyEvent`` records is deferred
                # pending real arcdps dump calibration (see plan 026
                # for the deferred scope + the calibration risk).
                is_buffremove,
                is_ninety,
                _pad63,
                _pad64,
                _pad65,
                _pad66,
            ) = _EVENT_STRUCT.unpack_from(data, cursor)
            # Phase 9 step 2-EMIT-BRANCH is deferred. The ``is_buffremove`` +
            # ``is_ninety`` bytes are surfaced (with their canonical arcdps.h
            # names) so the byte-alignment tests in
            # ``test_parser_byte_alignment.py`` can lock the offsets. The
            # ``del`` below consumes the values to suppress ruff's
            # ``RUF059`` (unpacked-but-unused) until the emit branch ships;
            # remove this ``del`` together with the ``is_buffremove``
            # branch in step 2-EMIT.
            del is_buffremove, is_ninety
            cursor += EVENT_SIZE
            if is_statechange != 0:
                continue
            magnitude = max(0, value)
            buff_strip = max(0, buff_dmg)
            if is_nondamage == 0:
                # Pure damage path. ``buff_dmg > 0`` is silently
                # dropped: arcdps only writes ``buff_dmg`` on the
                # heal-class event kind, so a damage record with
                # non-zero ``buff_dmg`` is a parser-version artefact
                # and is NOT a valid Phase 8 buff-strip signal.
                if magnitude == 0:
                    continue
                yield DamageEvent(
                    time_ms=time_ms,
                    source_agent_id=src_agent,
                    target_agent_id=dst_agent,
                    skill_id=skill_id,
                    damage=magnitude,
                )
            else:
                # ``is_nondamage > 0`` is the healing-class signal. We
                # do NOT filter further on the specific value of
                # ``is_nondamage`` -- some arcdps revisions set it to
                # 2, 3, etc. for sub-kinds of heal; the aggregator
                # gets one event per heuristic-clamped heal.
                if magnitude > 0:
                    yield HealingEvent(
                        time_ms=time_ms,
                        source_agent_id=src_agent,
                        target_agent_id=dst_agent,
                        skill_id=skill_id,
                        healing=magnitude,
                    )
                # Phase 8 buff-strip emission. Yields a SEPARATE
                # ``BuffRemovalEvent`` event alongside the heal (or
                # standalone if the record had no ``value``). This
                # is the second-half of the same-record dual-emit:
                # the heal amount (``value``) and the strip amount
                # (``buff_dmg``) are independent fields on the
                # arcdps cbtevent record, and a single skill can
                # both heal the caster AND strip a boon from the
                # target. A single cbtevent can yield at most TWO
                # events: one ``HealingEvent`` (above) + one
                # ``BuffRemovalEvent`` (below).
                if buff_strip > 0:
                    yield BuffRemovalEvent(
                        time_ms=time_ms,
                        source_agent_id=src_agent,
                        target_agent_id=dst_agent,
                        skill_id=skill_id,
                        buff_removal=buff_strip,
                    )


# ---------------------------------------------------------------------------
# Module-private helpers
# ---------------------------------------------------------------------------


def _read_all(source: BinaryIO | bytes) -> bytes:
    """Coerce the source to raw ``bytes`` without materialising huge copies.

    For ``bytes``, we return a defensive copy so the caller can mutate
    the input. For ``BinaryIO`` we read everything once.

    v0.10.2 hotfix followup #9: after the materialisation, enforce
    the :data:`MAX_EVTC_BYTES` cap (100 MB) as a defense-in-depth
    backstop. The API layer caps at 30 MB (per plan 048), so anything
    reaching the parser is at most 100 MB; direct library consumers
    (CLI tools, notebooks, FaaS workers) bypass the API cap and could
    feed 1 GB+ blobs that OOM the parser's downstream allocations
    (the agent list, the skill list, the events list). The cap
    is checked AFTER the materialisation (Option A in the design)
    because:

    1. The 30-100 MB range doesn't OOM Python on the ``source.read()``
       call itself (only the downstream algorithm allocations
       would OOM, and those are caught by the structural caps
       ``MAX_AGENTS`` + ``MAX_SKILLS`` + ``MAX_SKILL_NAME_BYTES``).
    2. Reading in chunks + raising mid-read (Option B) would
       complicate the error path without meaningfully reducing the
       peak memory (Python still has the partial buffer).
    3. ``source.seek(0, 2) + source.tell()`` (Option C) requires a
       seekable stream and would break for ``stdin``-style
       BinaryIO sources.

    The error message is operator-friendly: it includes the
    actual size + the bound in MB + a remediation hint pointing
    at the streaming ``parse_events`` API.
    """
    if isinstance(source, bytes):
        data = bytes(source)
    elif hasattr(source, "read"):
        data = source.read()
    else:
        msg = f"Expected bytes or BinaryIO, got {type(source).__name__}"
        raise TypeError(msg)

    # v0.10.2 hotfix followup #9: enforce the 100 MB cap AFTER
    # the materialisation. The check is intentionally at the
    # chokepoint (both ``parse()`` and ``parse_events()`` go
    # through ``_read_all``) so the cap is enforced exactly once
    # per parse, not duplicated in each public method.
    if len(data) > MAX_EVTC_BYTES:
        raise EvtcParseError(
            f"EVTC blob is {len(data)} bytes, exceeds safety bound "
            f"{MAX_EVTC_BYTES} bytes ({MAX_EVTC_BYTES // (1024 * 1024)} MB); "
            f"refusing to allocate. Split the blob or use the streaming "
            f"parse_events API for larger archives."
        )
    return data


def _iter_fights(data: bytes) -> Iterator[Fight]:
    """Parse the EVTC blob and yield a single :class:`Fight`."""
    if len(data) < HEADER_SIZE:
        raise EvtcParseError(f"EVTC blob is {len(data)} bytes, header needs {HEADER_SIZE}")

    magic, build, _rev, encounter_id, _unused, agent_count, skill_count, _lang = (
        _HEADER_STRUCT.unpack_from(data, 0)
    )
    del _lang  # language byte is read but not interpreted in V1.3

    if magic != b"EVTC":
        raise EvtcParseError(f"Bad magic bytes: {magic!r} (expected b'EVTC')")

    try:
        build_str = build.decode("ascii")
    except UnicodeDecodeError as exc:
        raise EvtcParseError(f"Build bytes are not pure ASCII: {build!r}") from exc

    if agent_count > MAX_AGENTS:
        raise EvtcParseError(f"agent_count={agent_count} exceeds safety bound {MAX_AGENTS}")

    if skill_count > MAX_SKILLS:
        raise EvtcParseError(f"skill_count={skill_count} exceeds safety bound {MAX_SKILLS}")

    header = EvtcHeader(
        build_version=build_str,
        encounter_id=encounter_id,
        skill_count=skill_count,
        agent_count=agent_count,
    )

    agents = list(_iter_agents(data, agent_count))
    skills = list(_iter_skills(data, HEADER_SIZE + agent_count * AGENT_SIZE, skill_count))

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


def _iter_skills(data: bytes, offset: int, count: int) -> Iterator[Skill]:
    """Read up to ``count`` variable-size skill records starting at ``offset``.

    Each record has a fixed 8-byte header (``skill_id`` u32 + ``name_len``
    u32) followed by ``name_len`` bytes of UTF-8 name. arcdps writes a
    trailing null byte after the name, which is included in the byte
    stream but not counted in ``name_len``; the next record starts
    immediately after the null terminator (``offset += 8 + name_len + 1``).

    The function is **lenient**: if the cursor runs past the end of the
    data, or if a record's ``name_len`` exceeds the safety bound (which
    happens when ``header.skill_count`` is larger than the actual number
    of skill records — a known arcdps quirk), the parser stops early
    and emits a warning. The yielded count may therefore be less than
    ``count``. This is preferable to raising, because the alternative
    (reading into the event stream) produces garbage records that
    pollute downstream analytics.
    """
    if count == 0:
        return
    cursor = offset
    end = len(data)
    for skill_index in range(count):
        if cursor + _SKILL_HEADER_STRUCT.size > end:
            logger.warning(
                "Truncated skill table at skill %d: header would read at offset %d "
                "but only %d bytes remain; stopping early (claimed %d skills)",
                skill_index,
                cursor,
                end - cursor,
                count,
            )
            return
        skill_id, name_len = _SKILL_HEADER_STRUCT.unpack_from(data, cursor)
        if name_len > MAX_SKILL_NAME_BYTES:
            logger.warning(
                "Skill %d at offset %d has name_len=%d exceeding safety bound %d; "
                "the skill table likely ends here (header claimed %d skills, "
                "but the next bytes look like event-stream data)",
                skill_index,
                cursor,
                name_len,
                MAX_SKILL_NAME_BYTES,
                count,
            )
            return
        # 8 bytes header + name_len bytes name + 1 byte null terminator.
        record_size = _SKILL_HEADER_STRUCT.size + name_len + 1
        if cursor + record_size > end:
            logger.warning(
                "Truncated skill body at skill %d offset %d: "
                "need %d bytes, only %d available; stopping early",
                skill_index,
                cursor,
                record_size,
                end - cursor,
            )
            return
        name_bytes = data[
            cursor + _SKILL_HEADER_STRUCT.size : cursor + _SKILL_HEADER_STRUCT.size + name_len
        ]
        name = name_bytes.decode("utf-8", errors="replace")
        yield Skill(id=skill_id, name=name)
        cursor += record_size


def _compute_post_skills_offset(data: bytes) -> int:
    """Return the byte offset where the event stream starts.

    Mirrors :func:`_iter_skills` cursor logic without yielding Skill
    records, so :meth:`PythonEvtcParser.parse_events` can advance past
    the skill table deterministically. Truncation behaviour matches
    :func:`_iter_skills`: stops at the cursor it would have stopped at
    when iterating, returning either the start of the event block OR
    ``len(data)`` if the skill table ate the entire blob.
    """
    if len(data) < HEADER_SIZE:
        return len(data)
    unpacked_header = _HEADER_STRUCT.unpack_from(data, 0)
    agent_count = int(unpacked_header[5])
    skill_count = int(unpacked_header[6])
    cursor = HEADER_SIZE + agent_count * AGENT_SIZE
    end = len(data)
    for _ in range(skill_count):
        if cursor + _SKILL_HEADER_STRUCT.size > end:
            return cursor
        unpacked_skill = _SKILL_HEADER_STRUCT.unpack_from(data, cursor)
        name_len = int(unpacked_skill[1])
        if name_len > MAX_SKILL_NAME_BYTES:
            return cursor
        record_size = _SKILL_HEADER_STRUCT.size + name_len + 1
        if cursor + record_size > end:
            return cursor
        cursor += record_size
    return cursor


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
    """Return the bytes of the first entry in an open zip.

    v0.9.6 plan 020: refuse to extract any entry whose declared
    uncompressed size exceeds ``_MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE``
    (zip-bomb DoS defence). ``ZipFile.getinfo(...).file_size`` is
    the declared uncompressed size on the central directory --
    reading it does NOT materialise the payload, so the check is
    O(1).
    """
    names = zf.namelist()
    if not names:
        raise EvtcParseError("zevtc has no entries (empty zip)")
    name = names[0]
    info = zf.getinfo(name)
    if info.file_size > _MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE:
        raise EvtcParseError(
            f"zip entry {name!r} declared uncompressed size "
            f"({info.file_size} bytes) exceeds safety bound "
            f"{_MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE} bytes; "
            f"refusing to extract (zip-bomb protection)"
        )
    return zf.read(name)


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
    "MAX_EVTC_BYTES",
    "MAX_SKILLS",
    "MAX_SKILL_NAME_BYTES",
    "SKILL_COUNT_OFFSET",
    "PythonEvtcParser",
    "read_zevtc_archive",
    "read_zevtc_bytes",
]
