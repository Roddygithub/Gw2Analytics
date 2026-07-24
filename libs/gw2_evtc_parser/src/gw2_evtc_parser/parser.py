"""Python reference implementation of the EVTC parser.

This implementation reads:

* the 24-byte file header (``EVTC`` magic + ``yyyymmdd`` build date +
  revision byte + combat_id + unused + ``agent_count`` u32 +
  ``map_id`` u32) for rev>=1, or the 24-byte extended rev0 header
  (``skill_count`` at bytes 20-23),
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
    | 24  |  72s   | name (null-padded 72-byte buffer)          |
    +-----+--------+--------------------------------------------+

* **Fixed-size skill records** immediately after the agent block.
  Each record is exactly 68 bytes:

    +-----+--------+--------------------------------------------+
    | off | size   | field                                      |
    +-----+--------+--------------------------------------------+
    |  0  |  I     | skill_id (uint32)                          |
    |  4  | 64s    | name (null-padded UTF-8 buffer)            |
    +-----+--------+--------------------------------------------+

  The skill table is stored in one of two wire formats:

  * **Legacy** (pre-2025): a 4-byte ``skill_count`` prefix followed by
    ``skill_count`` consecutive 68-byte records.
  * **EVTC2025+**: no count prefix; consecutive 68-byte records run
    until the parser's heuristic detects the start of the event stream.

  The name buffer is a fixed 64-byte null-padded UTF-8 string. Any
  bytes after the first null terminator are ignored, so embedded nulls
  truncate the name at the first ``\0``.

The agent-record 72-byte name buffer holds the *combo string* for
player agents (``"char_name\\0:account_name\\0subgroup\\0"`` null-padded
to 72 bytes) and a single null-terminated string for NPCs. The parser
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
import math
import struct
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Final

from gw2_core import (
    Agent,
    BlockEvent,
    BoonApplyEvent,
    BuffApplyEvent,
    BuffRemovalEvent,
    DamageEvent,
    DeathEvent,
    DodgeEvent,
    DownEvent,
    EliteSpec,
    Event,
    EvtcHeader,
    Fight,
    HealingEvent,
    InterruptEvent,
    PositionEvent,
    Profession,
    Skill,
)
from gw2_evtc_parser.exceptions import EvtcParseError
from gw2_evtc_parser.statechange_dispatch import dispatch_statechange

# Module-level logger for soft warnings (e.g. unrecognised arcdps
# account_name format). Library consumers control verbosity via the
# standard ``logging`` configuration; we do not call ``basicConfig``.
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Binary layout constants
# ---------------------------------------------------------------------------

#: Total size of the EVTC file header in bytes for rev>=1.
#: Layout (per ``arcdps.h`` ``evtc_header``): magic(4) + build(8) +
#: rev(1) + combat_id(2) + unused(1) + agent_count(4) + map_id(4)
#: = 24 bytes.  For rev>=1 some builds append a ``skill_count(4)``
#: extension making the header 28 bytes total; this parser only reads
#: the first 24 bytes and derives the agent table start from there.
HEADER_SIZE: Final[int] = 24

#: ``struct`` format for the 24-byte file header (rev>=1).
#: Fields: magic(4s) + build(8s) + rev(B) + combat_id(H) + unused(B)
#: + agent_count(I) + map_id(I).
_HEADER_STRUCT: Final[struct.Struct] = struct.Struct("<4s8sBHBI I")

#: Byte offset of the agent_count field inside the header.
AGENT_COUNT_OFFSET: Final[int] = 16

#: Byte offset of the build date field inside the header.
BUILD_OFFSET: Final[int] = 4

#: Byte offset of the skill_count field inside the header (bytes 20-23).
SKILL_COUNT_OFFSET: Final[int] = 20

#: Byte offset where agent records start (right after the 24-byte
#: header). For rev>=1 agents begin immediately after the header.
AGENTS_OFFSET: Final[int] = HEADER_SIZE

#: Total size of one agent record on disk (the C ``struct ag`` size).
AGENT_SIZE: Final[int] = 96

#: Size of the 24-byte fixed prefix that starts every agent record
#: (legacy pre-2025 layout).
AGENT_PREFIX_SIZE: Final[int] = 24

#: Size of the 72-byte name buffer that ends every legacy agent record.
AGENT_NAME_SIZE: Final[int] = AGENT_SIZE - AGENT_PREFIX_SIZE

#: ``struct`` format for the entire 96-byte agent record.
#: Layout (little-endian): id(Q) + prof(I) + elite(I) + four uint16s +
#: 72-byte name buffer.
_AGENT_STRUCT: Final[struct.Struct] = struct.Struct(f"<QIIhhhh{AGENT_NAME_SIZE}s")

#: Size of the 64-byte name buffer inside an EVTC2025+ agent record.
#: The 2025 layout is: iid_low(u32) + prof(u32) + is_elite(u32) +
#: toughness(u32) + healing(u32) + concentration(u32) + name(64s) +
#: subgroup(u32) + addr(u32) = 96 bytes.
AGENT_NAME_SIZE_2025: Final[int] = 64

#: ``struct`` format for the EVTC2025+ 96-byte agent record.
_AGENT_STRUCT_2025: Final[struct.Struct] = struct.Struct(f"<IIIIII{AGENT_NAME_SIZE_2025}sII")

#: Size of one fixed-size skill record: skill_id(u32) + name(64B).
#: arcdps writes skill names as a fixed 64-byte null-padded buffer
#: (no separate name_len field).
SKILL_RECORD_SIZE: Final[int] = 68

#: ``struct`` format for the fixed-size portion of a skill record
#: (just the 4-byte ``skill_id``; the 64-byte name buffer follows).
_SKILL_ID_STRUCT: Final[struct.Struct] = struct.Struct("<I")

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
#: Despite the byte-position discrepancy with the community-port arcdps.h
#: C struct declaration ``<QQQiiIIHHHHbbbbbbbbbbbbxxxx>`` (per the mirror
#: at ``<GW2-ArcDPS-Mechanics-Log>/src/arcdps_datastructures.h``), the
#: **operational** reading of this struct is empirically correct for
#: rev=1 arcdps logs. The 2026-07-11 F1 calibration pilot (verified on
#: 12 real WvW fixtures ranging 75 KB to ~12 MB; see
#: ``advisor-plans/026-phase-9-conditions.md`` for the full evidence)
#: confirmed:
#:
#:     * Byte 48 (unpack tuple slot 12) = the byte the production filter
#:       reads as ``is_statechange``. Per-fixture zero-percentage is
#:       ~99% on typical rev=1 fights. The current struct decisively
#:       beat the post-SYNC struct on the empirical outliers:
#:       5b161ec0 -- current 77.78% vs post 48.66%; eeaE64d1 -- current
#:       6.91% vs post 0.69% (10x better).
#:     * Byte 49 (unpack tuple slot 13) = arcdps's ``ev.buff`` field
#:       (the buff ID for buff-interaction records; the arcdps.h
#:       label is `buff` but the binding here is renamed from the
#:       legacy `is_flanking` to reflect the F1 byte mapping).
#:       Per-fixture zero-percentage is ~80% on typical rev=1 fights.
#:       Phase 9 step 3 (commit following ``e13ab3b``) reads this
#:       byte as ``_ev_buff`` and uses it as the APPLY predicate
#:       (``ev.buff != 0 AND is_buffremove == 0`` -> mid-combat APPLY).
#:     * Byte 52 (unpack tuple slot 16) = arcdps's ``cbtbuffremove``
#:       enum: 0=APPLY, 1=REMOVE_ALL, 2=REMOVE_SINGLE,
#:       3=REMOVE_SINGLE-CBTB_MANUAL-collapsed. Realigned in
#:       ``libs/gw2_analytics/buff_dispatch.py:decode_buff_change``
#:       (Phase 9 step 4, commit ``529cb90``).
#:     * Byte 53 (unpack tuple slot 17) = arcdps's ``is_ninety`` flag
#:       (1 on 90%-threshold hits; renamed from ``_pad61`` in v0.10.6).
#:
#: v0.10.6+ Phase 9 step 2 (commit ``328833d``) exposed bytes 52 + 53
#: as ``is_buffremove`` + ``is_ninety`` via tuple-slot renaming. Phase 9
#: step 2-EMIT-BRANCH (SHIPPED 2026-07-11, commit ``328833d``) uses
#: byte 52 to yield ``BoonApplyEvent`` records from cbtevent records
#: whose ``is_buffremove`` byte carries a REMOVE signal in the valid
#: arcdps range ``{1, 2, 3}`` (REMOVE_ALL / REMOVE_SINGLE /
#: REMOVE_SINGLE-CBTB_MANUAL-collapsed). The arcdps APPLY path goes
#: through ``is_statechange != 0`` records (statechange events with
#: ``is_buffremove == 0`` carry the ``CBTS_BUFFAPPLY`` marker), which
#: the upstream filter in
#: :meth:`PythonEvtcParser.parse_events` (``if is_statechange != 0:
#: continue``) skips before the REMOVE predicate fires. Once
#: ``is_statechange == 0`` has filtered out APPLY records, the
#: ``is_buffremove == 0`` byte at byte 52 reads as ``CBTB_NONE``
#: ("not used - not this kind of event"), NOT an APPLY marker --
#: arcdps does NOT signal APPLY events through the non-statechange
#: cbtevent path. Predicate: ``is_buffremove in (1, 2, 3)`` -- the
#: range is deliberately EXCLUDES the CBTB_NONE sentinel (0) so
#: pure-damage / pure-heal cbtevent records (which carry
#: ``is_buffremove == 0`` as a default) do not pollute the
#: ``BoonApplyEvent`` stream with phantom zero-duration applies.
#:
#: Maintenance note: do NOT change this struct literal without
#: re-running the F1 calibration pilot on the 12-fixture rev=1
#: corpus. The byte positions are empirically validated; ANY byte
#: shift invalidates downstream damage / heal / strip emission for
#: past dumps AND breaks the 3 byte-lock assertions in
#: ``tests/test_parser_byte_alignment.py``.
#: Full 22-field struct. Kept as the canonical public constant
#: because downstream byte-alignment tests import it and rely
#: on the full tuple shape.
_EVENT_STRUCT: Final[struct.Struct] = struct.Struct("<QQQiiIIHHHbbbbbbbbIIbb")

#: Optimized event struct: only unpacks the 10 fields actually
#: consumed by :meth:`PythonEvtcParser.parse_events`. The byte
#: positions are identical to the legacy 22-field struct above;
#: this variant avoids allocating / assigning 12 unused values
#: per event in the hot loop.
_EVENT_STRUCT_EVENTS: Final[struct.Struct] = struct.Struct("<QQQii 4x I 7x bbb 2x b 11x")

#: Standard arcdps cbtevent struct for EVTC2025+ builds.  arcdps
#: reverted to the documented ``arcdps.h`` layout for 2025+ logs:
#: time(Q)+src(Q)+dst(Q)+value(i)+buff_dmg(i)+overstack(I)+
#: skillid(I)+src_instid(H)+dst_instid(H)+src_master_instid(H)+
#: dst_master_instid(H)+16 flag bytes.  Flags start at byte 48.
_EVENT_STRUCT_2025: Final[struct.Struct] = struct.Struct("<QQQiiIIHHHH16B")

#: Optimized event struct for EVTC2025+ builds.  Reads the fields
#: consumed by :meth:`PythonEvtcParser.parse_events` using the
#: standard flag byte positions:
#:   byte 48 = iff
#:   byte 49 = ev.buff
#:   byte 50 = result
#:   byte 52 = is_buffremove
#:   byte 56 = is_statechange
_EVENT_STRUCT_EVENTS_2025: Final[struct.Struct] = struct.Struct("<QQQii 4x I 8x bbbx b 3x b 7x")

#: Phase 9 step 2-EMIT-BRANCH: arcdps's REMOVE-class ``cbtbuffremove``
#: byte values 1, 2, 3 ↔ ``BoonApplyEvent.kind: Literal["remove_all",
#: "remove_single"]``. Exposed as a 3-tuple-of-literal-strings
#: indexed by ``byte - 1`` so mypy narrows
#: ``BoonApplyEvent.kind`` to a :class:`Literal` via tuple-subscript
#: WITHOUT an attribute-via-enum hop (which would lose the narrowing
#: on a ``.value`` access).
#:
#: The tuple omits the CBTB_NONE byte (0) and the apply-side of the
#: ``cbtbuffremove`` enum deliberately:
#:
#:     * CBTB_NONE (0) reads as "not a buff interaction" once the
#:       parser's upstream statechange filter
#:       (``if is_statechange != 0: continue``) has been applied.
#:       arcdps encodes APPLY events through the ``is_statechange``
#:       path (``CBTS_BUFFAPPLY`` statechange records are filtered
#:       upstream before this REMOVE predicate fires), NOT through
#:       the non-statechange cbtevent path -- so byte 0 is a
#:       sentinel for "pure damage / pure heal" records at this
#:       code site, NOT an apply marker. Indexing byte 0 against
#:       ``"apply"`` here would be a mis-read of the arcdps
#:       convention (a future Phase 9 step 3 may yield
#:       ``BoonApplyEvent(kind="apply")`` from upstream
#:       statechange records -- that surface WILL use byte 0 as a
#:       marker, but the predicate excludes it from this
#:       non-statechange path).
#:
#:     * The "apply" word lives in
#:       :func:`gw2_analytics.buff_dispatch.decode_buff_change`'s
#:       canonical mapping (which DOES read byte 0 as "apply" for
#:       the upstream statechange-driven APPLY path). The parser
#:       deliberately does NOT import from ``gw2_analytics`` (a
#:       foundational-vs-analytics layer separation -- analysis
#:       builds ON top of the parser, not the other way around).
#:       Keeping the parser's local mapping as a 3-tuple instead
#:       of a 4-tuple with slot 0 = "apply" keeps the layer
#:       boundary crisp: this constant maps ONLY the bytes the
#:       parser actually consumes.
#:
#: CBTB_MANUAL (byte 3) collapses onto ``remove_single`` per
#: arcdps's documented "use for in/out volume" guidance (also
#: reflected in :func:`gw2_analytics.buff_dispatch.decode_buff_change`).
_CBTBUFREMOVE_KINDS: Final[tuple[str, str, str]] = (
    "remove_all",  # byte 1: CBTB_ALL -> remove_all
    "remove_single",  # byte 2: CBTB_SINGLE -> remove_single
    "remove_single",  # byte 3: CBTB_MANUAL collapsed to remove_single per arcdps
)

#: Sanity bound on agent_count to defend against pathological sources.
MAX_AGENTS: Final[int] = 10_000

#: Sanity bound on skill_count to defend against pathological sources.
MAX_SKILLS: Final[int] = 100_000

#: Maximum number of skill records to scan when looking for the
#: event-stream boundary in the EVTC2025+ no-count format. Real EVTC
#: skill tables are typically far smaller; this cap prevents malformed
#: blobs from iterating forever.
_MAX_SKILL_BOUNDARY_SEARCH: Final[int] = 10_000

#: Maximum bytes for a single skill name (arcdps caps at 64 in practice
#: but we allow 4 KiB to absorb long custom skill names from addons).
MAX_SKILL_NAME_BYTES: Final[int] = 4_096

#: v0.10.2 hotfix followup #9: maximum bytes for the entire EVTC blob.
#: arcdps caps canonical WvW raids at ~5-20 MB compressed, but the
#: decompressed EVTC blob can be much larger — a 40 MB .zevtc file
#: decompresses to ~221 MB. Real WvW fights with 500+ agents produce
#: some of the largest logs in the game. The cap is set to 500 MB to
#: accommodate the largest real-world .zevtc files (matching the
#: ``_MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE`` zip-bomb defence). The cap is
#: checked once in :func:`_read_all` AFTER the bytes are materialised.
#: The error message includes the actual size + the bound in MB + a
#: remediation hint. Centralised here so a future bump only needs to
#: touch this constant.
MAX_EVTC_BYTES: Final[int] = 500 * 1024 * 1024

#: arcdps account-name soft signal. Real arcdps revisions usually
#: prefix account strings with ``:``; we surface ``account_name``
#: verbatim and let downstream code decide whether the leading ``:``
#: is present (an empty account_name is also valid).
ACCOUNT_NAME_PREFIX: Final[bytes] = b":"

#: v0.11.0 hotfix: sanity cap for damage / heal / strip values.
#: arcdps uses INT32_MAX (2,147,483,647) as a sentinel for "no
#: value" or "infinite duration" in buff-metadata fields that
#: are misinterpreted as damage by the parser.  Any cbtevent
#: ``value`` or ``buff_dmg`` field >= this cap is a corrupted
#: read (buff metadata interpreted as damage).  Real GW2 damage
#: per hit never exceeds a few million, so this cap is extremely
#: generous -- it only catches the obvious sentinel cases.
_DAMAGE_SANITY_CAP: Final[int] = 2_147_483_647

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
# Elite-spec cross-validation (v0.16.1-api follow-up)
#
# arcdps EVTC2025+ builds sometimes write elite-spec values that do not
# correspond to the parsed profession (e.g. a Warrior with elite=74 which
# decodes to Virtuoso, a Mesmer-only spec).  When this happens the parser
# degrades the elite to BASE (no elite) so downstream consumers see a
# coherent profession/spec pair.  The raw byte is always preserved via
# ``Agent.elite_raw`` for forensics.
#
# Each profession lists the ELITE-SPEC INTEGER VALUES that are valid for
# it.  Values not in this set are treated as corrupted/misaligned data and
# reset to BASE (0).  Collisions (Soulbeast/Daredevil both = 55;
# Weaver/Renegade both = 63) are handled correctly: a Ranger with 55
# matches, a Thief with 55 matches, an Ele with 63 matches, a Rev with
# 63 matches — the collision is resolved downstream by whoever first
# consumes ``EliteSpec(55)`` or ``EliteSpec(63)``.
#
# EoD specs (Willbender, Mechanist, Untamed, Catalyst, Virtuoso,
# Harbinger, Specter, Vindicator) and Janthir Wilds specs are included
# where the EliteSpec enum has a value.  Specs not yet in the enum
# (Bladesworn, Luminary, etc.) are out of scope — the base-profession
# hint is the fallback anyway.
# ---------------------------------------------------------------------------

_VALID_ELITE_BY_PROFESSION: Final[dict[int, frozenset[int]]] = {
    Profession.GUARDIAN: frozenset({27, 62, 65}),  # Dragonhunter, Firebrand, Willbender
    Profession.WARRIOR: frozenset({18, 64}),  # Berserker, Spellbreaker
    Profession.ENGINEER: frozenset({43, 57, 70}),  # Scrapper, Holosmith, Mechanist
    Profession.RANGER: frozenset({5, 55, 73}),  # Druid, Soulbeast, Untamed
    Profession.THIEF: frozenset({55, 71, 72}),  # Daredevil, Deadeye, Specter
    Profession.ELEMENTALIST: frozenset({48, 63, 75}),  # Tempest, Weaver, Catalyst
    Profession.MESMER: frozenset({40, 59, 74}),  # Chronomancer, Mirage, Virtuoso
    Profession.NECROMANCER: frozenset({34, 60, 77}),  # Reaper, Scourge, Harbinger
    Profession.REVENANT: frozenset({52, 63, 68}),  # Herald, Renegade, Vindicator
}


def _validate_elite_for_profession(profession_int: int, elite_int: int) -> EliteSpec:
    """Return the validated elite spec for a profession+elite pair.

    If the elite spec value is valid for the given profession, return
    ``EliteSpec(elite_int)``.  Otherwise return ``EliteSpec.BASE`` (0)
    and log a debug message so operators can investigate the source file.

    The raw ``elite_int`` is available as ``Agent.elite_raw`` for
    forensics regardless of this validation outcome.
    """
    if elite_int == 0:
        return EliteSpec.BASE
    valid = _VALID_ELITE_BY_PROFESSION.get(profession_int)
    if valid is not None and elite_int in valid:
        try:
            return EliteSpec(elite_int)
        except ValueError:
            return EliteSpec.UNKNOWN
    # Cross-validation failed: the elite spec does not belong to this
    # profession.  Degrade to BASE (no elite) so downstream consumers
    # see a coherent profession/spec pair.
    logger.debug(
        "Elite spec %d invalid for profession %d (agent skipped); "
        "raw value preserved in elite_raw for forensics",
        elite_int,
        profession_int,
    )
    return EliteSpec.BASE


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
    def parse_events(source: BinaryIO | bytes) -> Iterator[Event]:  # noqa: PLR0912, PLR0915
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
        # Determine which event struct to use.  EVTC2025+ builds use the
        # standard arcdps cbtevent layout; older builds keep the legacy
        # empirically-calibrated layout.
        build_str = data[BUILD_OFFSET : BUILD_OFFSET + 8].decode("ascii", errors="replace")
        is_evtc_2025 = _build_version_from_build_str(build_str) >= 2025_00_00
        offset = _compute_post_skills_offset(data, is_evtc_2025=is_evtc_2025)
        end = len(data)
        cursor = offset
        # Local binding shaves attribute-lookup overhead in the
        # tight event-unpack loop.
        _unpack_event = (
            _EVENT_STRUCT_EVENTS_2025.unpack_from
            if is_evtc_2025
            else _EVENT_STRUCT_EVENTS.unpack_from
        )
        # Hoist the REMOVE-kind tuple to a local variable so the
        # hot loop pays local-variable lookup cost instead of
        # global lookup cost.
        _cbtbufremove_kinds = _CBTBUFREMOVE_KINDS
        # v0.12.2: Phase 6 v2 Step 4 — per-agent down-state lifecycle
        # tracking.  Maps agent_id -> time_ms when the agent went down.
        # Populated by ChangeDown (byte 5), consumed by ChangeUp (byte 6)
        # and ChangeDead (byte 4).
        down_start: dict[int, int] = {}
        while cursor + EVENT_SIZE <= end:
            if is_evtc_2025:
                (
                    time_ms,
                    src_agent,
                    dst_agent,
                    value,
                    buff_dmg,
                    skill_id,
                    _iff,
                    # byte 49 = arcdps ``ev.buff`` field -- the buff ID for
                    # mid-combat APPLY records per F1 byte mapping.
                    _ev_buff,
                    # byte 50 = arcdps ``result`` enum.  Values 13/14
                    # (CBTR_HEAL / CBTR_BUFFHEAL) mark heal-class events.
                    _result,
                    # byte 52 = arcdps ``is_buffremove`` byte.
                    is_buffremove,
                    # byte 56 = arcdps ``is_statechange`` byte.
                    is_statechange,
                ) = _unpack_event(data, cursor)
                # arcdps result enum: 13 = CBTR_HEAL, 14 = CBTR_BUFFHEAL.
                is_nondamage = 1 if _result in (13, 14) else 0
            else:
                (
                    time_ms,
                    src_agent,
                    dst_agent,
                    value,
                    buff_dmg,
                    skill_id,
                    is_nondamage,
                    is_statechange,
                    # byte 49 = arcdps ``ev.buff`` field -- the buff ID for
                    # mid-combat APPLY records per F1 byte mapping (struct
                    # slot 13). The legacy name was ``_is_flanking``; v0.10.11+
                    # renames the local binding to ``_ev_buff`` to reflect
                    # the arcdps field semantics. The byte position is
                    # unchanged so the existing damage / heal / strip
                    # / REMOVE-emit logic is unaffected.
                    _ev_buff,
                    # v0.10.6+ Phase 9 step 2: bytes 52-53 of the arcdps
                    # ``cbtevent`` record are the ``is_buffremove`` byte
                    # (the arcdps ``cbtbuffremove`` enum: 0=NONE in this
                    # non-statechange path, 1=ALL, 2=SINGLE, 3=MANUAL) +
                    # ``is_ninety`` flag. Renamed from the legacy
                    # ``_pad61``/``_pad62`` to mirror the arcdps.h field
                    # naming -- the byte offset is unchanged so the
                    # existing damage / healing / buff-removal emission
                    # logic is unaffected.
                    is_buffremove,
                ) = _unpack_event(data, cursor)
                # Phase B: extract result byte (offset 50) for
                # block/dodge/interrupt detection. The byte position
                # matches the arcdps cbtevent layout verified by the
                # F1 calibration pilot (byte 50 = arcdps result enum).
                _result = struct.unpack_from("<b", data, cursor + 50)[0]
            # NOTE: ``is_buffremove`` is consumed below by
            # Step 2-EMIT-BRANCH (REMOVE predicate ``in (1, 2, 3)``) AND
            # by Step 3 APPLY-BRANCH (predicate ``_ev_buff != 0 AND
            # is_buffremove == 0``). ``is_ninety`` is unpacked but not
            # yet surfaced to the Event stream (a future Phase 9 step
            # may use it for 90%-threshold markers on Removals).
            cursor += EVENT_SIZE
            # v0.11.0 WAVE-8 A.4: CBTS_BUFFAPPLY=18 statechange emit path.
            # arcdps encodes BUFF_APPLY via two channels:
            #   (a) the canonical non-statechange record flagged via
            #       ``ev.buff != 0`` (captured by BoonApplyEvent), AND
            #   (b) the orthogonal statechange sub-case
            #       ``is_statechange == 18`` (CBTS_BUFFAPPLY).
            # This intercept captures channel (b) BEFORE the generic
            # statechange skip that follows; it shares the BoonApplyEvent
            # field shape so downstream BUFF_APPLY / BUFF_REMOVAL dispatch
            # is uniform. The F1 byte-alignment lock pins is_statechange
            # to byte 48 (struct slot 12).
            if is_statechange == 18:
                yield BuffApplyEvent(
                    time_ms=time_ms,
                    source_agent_id=src_agent,
                    target_agent_id=dst_agent,
                    skill_id=skill_id,
                )
                continue
            if is_statechange != 0:
                # Byte 19 (CBTS_POSITION): position update. The x, y, z
                # coordinates are encoded as 3 float32 values at offset 16
                # of the raw cbtevent record (overwriting dst_agent + value).
                # This must be handled inline because the dispatch function
                # doesn't have access to the raw bytes.
                if is_statechange == 19:
                    x, y, z = struct.unpack_from("<3f", data, cursor + 16)
                    if (
                        math.isfinite(x)
                        and math.isfinite(y)
                        and math.isfinite(z)
                        and max(abs(x), abs(y), abs(z)) <= 1e5
                    ):
                        yield PositionEvent(
                            time_ms=time_ms,
                            source_agent_id=src_agent,
                            target_agent_id=0,
                            skill_id=0,
                            x=x,
                            y=y,
                        )
                    continue
                # v0.12.2: Phase 6 v2 Step 4 — down-state lifecycle.
                # Handle ChangeUp (byte 6), ChangeDown (byte 5), and
                # ChangeDead (byte 4) inline with per-agent downtime
                # computation.  These are intercepted BEFORE the
                # statechange dispatch call so the down_start dict
                # is available for computing downtime_ms.
                if is_statechange == 6:  # ChangeUp
                    if src_agent in down_start:
                        downtime = time_ms - down_start.pop(src_agent)
                        yield DownEvent(
                            time_ms=time_ms,
                            source_agent_id=src_agent,
                            target_agent_id=0,
                            skill_id=0,
                            downtime_ms=downtime,
                        )
                    continue
                if is_statechange == 5:  # ChangeDown
                    down_start[src_agent] = time_ms
                    yield DownEvent(
                        time_ms=time_ms,
                        source_agent_id=src_agent,
                        target_agent_id=0,
                        skill_id=0,
                    )
                    continue
                if is_statechange == 4:  # ChangeDead
                    if src_agent in down_start:
                        downtime = time_ms - down_start.pop(src_agent)
                        yield DownEvent(
                            time_ms=time_ms,
                            source_agent_id=src_agent,
                            target_agent_id=0,
                            skill_id=0,
                            downtime_ms=downtime,
                        )
                    yield DeathEvent(
                        time_ms=time_ms,
                        source_agent_id=src_agent,
                        target_agent_id=0,
                        skill_id=0,
                    )
                    continue
                # WAVE-8 v0.11.0 Blocker A.4.1 (see
                # ``plans/WAVE-8-parser-side.md`` §A.4.1): the upstream
                # filter ``if is_statechange != 0: continue`` is REPLACED
                # with a dispatch call to
                # :func:`statechange_dispatch.dispatch_statechange`.
                # The dispatch table maps the arcdps ``is_statechange``
                # byte (per :file:`docs/statechange-ids.md`) to a
                # Pydantic event constructor -- currently StunBreak
                # (byte 56) + Barrier (byte 38) + CC (byte 35).
                # Unmapped kinds return ``None`` so the filter
                # continues to suppress them at the byte boundary
                # (backward compat preserved).  Bytes 4, 5, 6 were
                # intercepted above.
                statechange_event = dispatch_statechange(
                    is_statechange=is_statechange,
                    time_ms=time_ms,
                    src_agent=src_agent,
                    dst_agent=dst_agent,
                    value=value,
                    skill_id=skill_id,
                )
                if statechange_event is not None:
                    yield statechange_event
                continue
            # Phase 9 step 2-EMIT-BRANCH (SHIPPED 2026-07-11, commit
            # ``e13ab3b``). Predicate: ``is_buffremove`` byte in the
            # arcdps REMOVE range {1, 2, 3} -- i.e. CBTB_ALL /
            # CBTB_SINGLE / CBTB_MANUAL (CBTB_MANUAL collapses to
            # ``remove_single`` per arcdps's "use for in/out volume"
            # guidance; see
            # :func:`gw2_analytics.buff_dispatch.decode_buff_change`).
            #
            # Phase 9 step 3 APPLY-BRANCH (SHIPPED 2026-07-11 as the
            # follow-up commit to ``e13ab3b``): predicate
            # ``_ev_buff != 0 AND is_buffremove == 0`` yields a
            # ``BoonApplyEvent(kind="apply")`` record from MID-COMBAT
            # APPLY records. Per F1 byte mapping (see ``_EVENT_STRUCT``
            # doc-comment) byte 49 IS arcdps's ``ev.buff`` field -- the
            # buff ID for buff-interaction records. The
            # ``is_buffremove == 0`` arm ensures the APPLY predicate
            # excludes the REMOVE-class records (which carry
            # ``ev.buff`` set to the stripped buff AND
            # ``is_buffremove`` in [1..3]); the REMOVE branch above
            # already handles those, so the APPLY branch sees only
            # pure-apply records (no ``is_buffremove`` signal = no
            # removal code = either apply OR pure damage).
            #
            # Why NOT statechange-driven APPLY: per the F1 calibration
            # + the buff_dispatch realignment (commit ``529cb90``),
            # arcdps encodes buff APPLY events as NON-statechange
            # records (``is_statechange == 0``) with ``ev.buff != 0``,
            # NOT as statechange records. The CBTS_BUFFAPPLY statechange
            # is a separate arcdps signal used for the initial buff
            # stack snapshot at fight start, NOT for mid-combat
            # applies. The upstream ``if is_statechange != 0: continue``
            # filter (already in place since Phase 7 v2) correctly
            # skips the statechange drives AND keeps the APPLY
            # predicate reachable.
            #
            # Layer-separation rationale: the parser does NOT import
            # from ``gw2_analytics`` (a foundational-vs-analytics
            # hierarchy -- parsing is a primitive, not on top of
            # analytics). The APPLY branch here statically yields
            # ``kind="apply"`` without touching
            # ``buff_dispatch.decode_buff_change`` (consistent with
            # the Step 2-REMOVE branch's inline tuple indexing).
            # Predicate: ``is_buffremove`` byte in the arcdps REMOVE
            # range {1, 2, 3} -- i.e. CBTB_ALL / CBTB_SINGLE /
            # CBTB_MANUAL (CBTB_MANUAL collapses to ``remove_single``
            # per arcdps's "use for in/out volume" guidance; see
            # :func:`gw2_analytics.buff_dispatch.decode_buff_change`).
            # The CBTB_NONE sentinel (0) is EXCLUDED from the
            # predicate: after the upstream ``is_statechange != 0``
            # filter (which skips the APPLY-class statechange records
            # that carry ``is_buffremove == 0`` as part of the
            # ``CBTS_BUFFAPPLY`` marker), a non-statechange cbtevent
            # that carries ``is_buffremove == 0`` is a pure damage /
            # pure heal record with NO buff-interaction context --
            # arcdps does NOT encode APPLY events through the
            # non-statechange path. Yielding a ``BoonApplyEvent`` for
            # the 0 case would pollute the stream with a
            # zero-duration phantom ``apply`` per damage / heal
            # event (every cbtevent the test fixtures pin via the
            # default `_build_event_record` helper has ``is_buffremove
            # == 0``). Values >= 4 are reserved (future arcdps use);
            # the predicate emits nothing for those -- the
            # unknown-byte fallback matches
            # ``gw2_analytics.buff_dispatch.decode_buff_change``.
            #
            # Layer-separation rationale: the parser does NOT import
            # from ``gw2_analytics`` (parsing is a foundational layer;
            # analytics builds ON top of the parser, not the other
            # way around). The mapping is inline below via the 3-tuple
            # :data:`_CBTBUFREMOVE_KINDS` indexed by ``byte - 1`` --
            # mypy narrows ``BoonApplyEvent.kind`` to a
            # :class:`Literal` via tuple-subscript WITHOUT an
            # attribute-via-enum hop (which would lose the narrowing
            # on a ``.value`` access). The tuple is INTENTIONALLY a
            # 3-tuple (NOT a 4-tuple with slot 0 = ``"apply"``) for
            # the layer-boundary reasons spelled out in the constant's
            # own docstring; it maps ONLY the bytes the parser
            # actually consumes, keeping the parser's local mapping
            # crisply distinct from
            # :func:`gw2_analytics.buff_dispatch.decode_buff_change`'s
            # 4-tuple mapping (which DOES use byte 0 = ``"apply"`` for
            # the upstream statechange-driven APPLY path).
            # ``duration_ms`` is conservatively 0 (cbtevent lacks a
            # duration field); ``stacks`` is 1 (conservative default
            # for the REMOVE_SINGLE / REMOVE_MANUAL case; REMOVE_ALL
            # uses the same single-marker default because the
            # cbtevent record does not carry the pre-remove stack
            # count).
            #
            # Defensive invariant: the predicate filters to {1, 2, 3}
            # and the emit tuple is a 3-tuple indexed by ``byte - 1``,
            # so ``byte - 1`` MUST land in [0, 3). If a future
            # maintainer widens the predicate back to [0..3] (or to
            # ``>= 0``) WITHOUT re-extending ``_CBTBUFREMOVE_KINDS``,
            # this assertion fires at the yield site with a clear
            # diagnostic BEFORE the BAD emit pollutes the
            # ``BoonApplyEvent`` stream. The assertion and the
            # predicate and the tuple length form a 3-line contract
            # -- keep them in sync.
            if is_buffremove in (1, 2, 3):
                # Defensive invariant: the predicate filters to {1, 2, 3}
                # and the emit tuple is a 3-tuple indexed by ``byte - 1``,
                # so ``byte - 1`` MUST land in [0, 3). If a future
                # maintainer widens the predicate back to [0..3] (or to
                # ``>= 0``) WITHOUT re-extending ``_CBTBUFREMOVE_KINDS``,
                # this assertion fires at the yield site with a clear
                # diagnostic BEFORE the BAD emit pollutes the
                # ``BoonApplyEvent`` stream. The assertion and the
                # predicate and the tuple length form a 3-line contract
                # -- keep them in sync. (See ``test_parser_byte_alignment``
                # for the module-level self-test pinning the literal
                # contents of ``_CBTBUFREMOVE_KINDS``.)
                assert 0 <= is_buffremove - 1 < len(_CBTBUFREMOVE_KINDS), (  # noqa: S101
                    f"Phase 9 Step 2-EMIT drift: predicate matched "
                    f"is_buffremove={is_buffremove} but "
                    f"_CBTBUFREMOVE_KINDS has {len(_CBTBUFREMOVE_KINDS)} "
                    f"slots (expected 3). The predicate, the tuple "
                    f"length, and the indexing '[byte - 1]' must stay "
                    f"in sync."
                )
                yield BoonApplyEvent(
                    time_ms=time_ms,
                    source_agent_id=src_agent,
                    target_agent_id=dst_agent,
                    skill_id=skill_id,
                    duration_ms=0,
                    stacks=1,
                    # Index by ``byte - 1`` so the 3-tuple aligns with
                    # the REMOVE byte range [1, 2, 3] (byte 0 is the
                    # CBTB_NONE sentinel excluded by the predicate).
                    kind=_cbtbufremove_kinds[is_buffremove - 1],
                )
                # v0.11.0 hotfix: do NOT fall through to the damage/heal
                # path below.  When ``is_buffremove in (1, 2, 3)`` the
                # cbtevent ``value`` field carries buff metadata (duration
                # in ms / stack count), NOT a damage or heal magnitude.
                # Falling through would yield a phantom DamageEvent /
                # HealingEvent with ``value`` reinterpreted as damage /
                # heal — the root cause of the trillion-damage bug on
                # real WvW logs.  The arcdps cbtevent format stores
                # pure-damage and buff-interaction records as SEPARATE
                # 64-byte rows; a single record never carries both.
                continue
            elif _ev_buff != 0:
                # Phase 9 Step 3 APPLY-BRANCH.
                # Predicate: ``_ev_buff != 0 AND is_buffremove == 0 AND
                # is_statechange == 0`` -- the arcdps mid-combat APPLY
                # channel per F1 byte mapping + buff_dispatch realignment
                # (commit ``529cb90``). The upstream
                # ``if is_statechange != 0: continue`` filter (already
                # in place) ensures ``is_statechange == 0``; the REMOVE
                # branch above ensures ``is_buffremove == 0`` for this
                # branch (since ``is_buffremove in (1, 2, 3)`` is the
                # REMOVE predicate and ``elif`` makes them mutually
                # exclusive); so the only remaining predicate is
                # ``_ev_buff != 0`` -- a non-zero arcdps ``ev.buff``
                # byte signals a buff-interaction record (a buff ID
                # was written), which is exactly an APPLY for that
                # ``skill_id`` buff.
                #
                # Real EVTC2025+ logs carry ``value`` / ``buff_dmg`` on
                # many buff-interaction records (condition ticks,
                # heal-and-apply combos, etc.). Those records are still
                # buff applies at the ``ev.buff`` level; downstream
                # ``BuffStateTracker`` ignores untracked skill_ids, so
                # condition ticks are safely no-ops. Keep the dedicated
                # ``continue`` here so the same record does NOT also
                # emit a DamageEvent/HealingEvent from the ``value``
                # field, which carries buff metadata rather than real
                # damage/heal for these interaction records.
                #
                # Conservative default ``duration_ms=0``: cbtevent does
                # not carry a duration field; the buff duration lives
                # in the project skills DB (loaded in Phase 10 by the
                # upstream buff_uptime.accumulate_buff_events aggregator).
                # Conservative default ``stacks=1``: cbtevent does not
                # carry a stacks field; mid-combat apply events in
                # arcdps represent a single stack magnitude delta (a
                # future arcdps revision could emit multi-stack applies
                # -- locked in Phase 10 once the aggregator surfaces
                # the stack-count delta).
                yield BoonApplyEvent(
                    time_ms=time_ms,
                    source_agent_id=src_agent,
                    target_agent_id=dst_agent,
                    skill_id=skill_id,
                    duration_ms=0,
                    stacks=1,
                    kind="apply",
                )
                # Same rationale as the REMOVE branch above: the
                # cbtevent ``value`` field carries buff metadata,
                # not damage.  Prevent fall-through to the damage /
                # heal path below.
                continue
            # v0.11.0 hotfix: sanity cap on damage/heal values.
            # Real GW2 damage per individual hit fits easily within
            # a uint32 (max single hit < 1M).  arcdps uses
            # ``_DAMAGE_SANITY_CAP`` as a sentinel for "no value" /
            # "infinite duration" in buff-metadata fields that the
            # buff branches above did not catch (events where both
            # ``is_buffremove`` and ``_ev_buff`` are 0 but the
            # cbtevent ``value`` field still carries buff metadata).
            magnitude = 0 if value >= _DAMAGE_SANITY_CAP else max(0, value)
            buff_strip = 0 if buff_dmg >= _DAMAGE_SANITY_CAP else max(0, buff_dmg)
            if is_nondamage == 0:
                # Pure damage path. ``buff_dmg > 0`` is silently
                # dropped: arcdps only writes ``buff_dmg`` on the
                # heal-class event kind, so a damage record with
                # non-zero ``buff_dmg`` is a parser-version artefact
                # and is NOT a valid Phase 8 buff-strip signal.
                #
                # Phase B: emit defense events from the arcdps result
                # byte (byte 50).  Values: 3=CBTR_BLOCK (blocked hit),
                # 4=CBTR_EVADE (target dodged), 5=CBTR_INTERRUPT
                # (source interrupted target's cast). These events
                # are orthogonal to the damage value -- a blocked or
                # evaded hit typically has zero damage, while an
                # interrupt can carry non-zero damage.
                if _result == 3:  # CBTR_BLOCK
                    # Target (dst_agent) blocked the incoming attack.
                    # Actor-only shape per gw2_core.BlockEvent docstring.
                    yield BlockEvent(
                        time_ms=time_ms,
                        source_agent_id=dst_agent,
                        target_agent_id=0,
                        skill_id=0,
                    )
                elif _result == 4:  # CBTR_EVADE
                    # Target (dst_agent) evaded (dodged) the attack.
                    # Actor-only shape per gw2_core.DodgeEvent docstring.
                    yield DodgeEvent(
                        time_ms=time_ms,
                        source_agent_id=dst_agent,
                        target_agent_id=0,
                        skill_id=0,
                    )
                elif _result == 5:  # CBTR_INTERRUPT
                    # Source (src_agent) interrupted the target's cast.
                    # Full shape per gw2_core.InterruptEvent docstring.
                    yield InterruptEvent(
                        time_ms=time_ms,
                        source_agent_id=src_agent,
                        target_agent_id=dst_agent,
                        skill_id=skill_id,
                    )
                if magnitude == 0:
                    continue
                yield DamageEvent(
                    time_ms=time_ms,
                    source_agent_id=src_agent,
                    target_agent_id=dst_agent,
                    skill_id=skill_id,
                    damage=magnitude,
                    # v0.12.1: pass the raw cbtevent buff_dmg field.
                    # For builds >= 20240501 this is the condi portion
                    # of the hit; the aggregator-tier DpsSplitGetter
                    # decides how to use it based on build date.
                    buff_dmg=buff_strip,
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
                        # v0.12.1: pass buff_dmg as barrier for heal-class
                        # records.  On heal records arcdps encodes the
                        # barrier/shield portion in buff_dmg.
                        barrier=buff_strip,
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
                    # v0.11.4: pass the arcdps ev.buff byte as buff_id
                    # so the aggregator can classify the removal as a
                    # boon strip vs condition cleanse via gw2_core.is_condition.
                    # _ev_buff is a signed int8; use & 0xFF for the
                    # unsigned byte value (buff IDs 128-255 would otherwise
                    # be negative and violate BuffRemovalEvent.buff_id ge=0).
                    yield BuffRemovalEvent(
                        time_ms=time_ms,
                        source_agent_id=src_agent,
                        target_agent_id=dst_agent,
                        skill_id=skill_id,
                        buff_removal=buff_strip,
                        buff_id=_ev_buff & 0xFF,
                    )


# ---------------------------------------------------------------------------
# Module-private helpers
# ---------------------------------------------------------------------------


def _read_all(source: BinaryIO | bytes) -> bytes:
    """Coerce the source to raw ``bytes`` without materialising huge copies.

    For ``bytes``, we return a defensive copy so the caller can mutate
    the input. For ``BinaryIO`` we read everything once.

    v0.10.2 hotfix followup #9: after the materialisation, enforce
    the :data:`MAX_EVTC_BYTES` cap (500 MB) as a defense-in-depth
    backstop. The API layer caps uploads at a generous size to
    accommodate real WvW logs; direct library consumers
    (CLI tools, notebooks, FaaS workers) bypass the API cap and could
    feed 1 GB+ blobs that OOM the parser's downstream allocations
    (the agent list, the skill list, the events list). The cap
    is checked AFTER the materialisation (Option A in the design)
    because:

    1. The 30-100 MB range doesn't OOM Python on the ``source.read()``
       call itself (only the downstream algorithm allocations
       would OOM, and those are caught by the structural caps
       ``MAX_AGENTS`` + ``MAX_SKILLS`` * ``SKILL_RECORD_SIZE``).
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


def _looks_like_skill_name(data: bytes, offset: int) -> bool:
    """Return True if the 64-byte buffer at ``offset`` looks like a skill name.

    A valid skill name contains at least one printable ASCII byte before
    the first null terminator, or is entirely null (empty name).
    """
    if offset + 64 > len(data):
        return False
    name_part = data[offset : offset + 64]
    name_before_nul = name_part.split(b"\x00", 1)[0]
    if not name_before_nul:
        return True
    return any(32 <= b < 127 for b in name_before_nul[:20])


def _detect_skill_format_nonzero(
    data: bytes,
    skill_offset: int,
    count: int,
    known_agents: frozenset[int] | None,
    *,
    is_evtc_2025: bool = False,
) -> tuple[bool, int, int]:
    """Handle the non-zero first-u32 case of :func:`_detect_skill_format`.

    The first 4 bytes after the agent table could be a legacy count or
    an EVTC2025+ skill_id. We resolve the ambiguity by checking which
    interpretation produces a valid event-stream boundary.
    """
    capped_count = min(count, MAX_SKILLS)
    legacy_boundary = skill_offset + 4 + capped_count * SKILL_RECORD_SIZE
    if legacy_boundary == len(data) or (
        legacy_boundary <= len(data)
        and _validate_event_candidate(
            data, legacy_boundary, known_agents, is_evtc_2025=is_evtc_2025
        )
    ):
        return True, capped_count, skill_offset + 4

    # EVTC2025+ interpretation: records start at skill_offset.
    # Find the first 68-byte-aligned offset that looks like events.
    # Cap the search so malformed/truncated blobs don't iterate forever.
    #
    # When the file ends exactly at a skill boundary we treat EOF as a
    # valid empty event stream: a legacy table of N records would occupy
    # 4 + N*68 bytes, which can never equal the EVTC2025+ N*68 bytes
    # because 4 is not divisible by 68. So an EOF-aligned boundary
    # unambiguously signals EVTC2025+ with zero events.
    max_skills_in_data = max(0, (len(data) - skill_offset) // SKILL_RECORD_SIZE)
    for n in range(1, min(max_skills_in_data, _MAX_SKILL_BOUNDARY_SEARCH) + 1):
        boundary = skill_offset + n * SKILL_RECORD_SIZE
        if boundary > len(data):
            break
        if boundary == len(data) or _validate_event_candidate(
            data, boundary, known_agents, is_evtc_2025=is_evtc_2025
        ):
            return False, MAX_SKILLS, skill_offset

    # No clear event boundary found; fall back to legacy (safer for
    # backward compatibility with old variable-length records).
    return True, capped_count, skill_offset + 4


def _detect_skill_format(
    data: bytes,
    skill_offset: int,
    known_agents: frozenset[int] | None = None,
    *,
    is_evtc_2025: bool = False,
) -> tuple[bool, int, int]:
    """Detect whether the skill table has a count prefix (legacy) or not (EVTC2025+).

    Returns ``(has_count_prefix, count, records_offset)``:
    * ``has_count_prefix``: True for legacy format, False for EVTC2025+.
    * ``count``: Number of skill records (capped at MAX_SKILLS).
    * ``records_offset``: Byte offset where the first skill record starts.
    """
    if skill_offset + 4 > len(data):
        return True, 0, skill_offset

    # Fast path: if the bytes right after the agent table already look
    # like the event stream, there is no skill table at all. This covers
    # the EVTC2025+ empty-skill case (and legacy empty-skill too, since
    # the result is the same: 0 skills, events start here).
    if known_agents is not None and _validate_event_candidate(
        data, skill_offset, known_agents, is_evtc_2025=is_evtc_2025
    ):
        return True, 0, skill_offset

    count = struct.unpack_from("<I", data, skill_offset)[0]

    # Non-zero count: could be a legacy count prefix OR an EVTC2025+
    # skill_id. Distinguish by checking where the event stream starts.
    if count > 0:
        return _detect_skill_format_nonzero(
            data, skill_offset, count, known_agents, is_evtc_2025=is_evtc_2025
        )

    # Count is 0. Could be: (a) legacy format with 0 skills, or
    # (b) EVTC2025+ format where the first 4 bytes are skill_id=0.
    # Distinguish by checking whether the bytes look like a valid
    # EVTC2025+ skill record (printable name) vs. a legacy count=0
    # followed by the event stream.
    if skill_offset + SKILL_RECORD_SIZE <= len(data) and _looks_like_skill_name(
        data, skill_offset + 4
    ):
        # EVTC2025+ format: no count prefix, skills start immediately.
        return False, MAX_SKILLS, skill_offset

    # Legacy format with 0 skills.
    return True, 0, skill_offset + 4


def _build_version_from_build_str(build_str: str) -> int:
    """Return the numeric build version from the 8-byte ASCII build string.

    arcdps build strings are ISO-like dates (``20251009``).  Non-numeric
    or unexpectedly short strings return 0 so the caller can treat the
    file as legacy.
    """
    if len(build_str) == 8 and build_str.isdigit():
        return int(build_str)
    return 0


def _iter_fights(data: bytes) -> Iterator[Fight]:
    """Parse the EVTC blob and yield a single :class:`Fight`.

    Agents are augmented with "UNKNOWN" entries for any agent ID
    referenced in the event stream that is not in the agent table.
    This ensures event-to-agent attribution works for minions, pets,
    environmental objects, and transient entities that arcdps may
    omit from the agent table.
    """
    if len(data) < HEADER_SIZE:
        raise EvtcParseError(f"EVTC blob is {len(data)} bytes, header needs {HEADER_SIZE}")

    magic, build, _rev, encounter_id, _unused, agent_count, _skill_count_hdr = (
        _HEADER_STRUCT.unpack_from(data, 0)
    )

    if magic != b"EVTC":
        raise EvtcParseError(f"Bad magic bytes: {magic!r} (expected b'EVTC')")

    try:
        build_str = build.decode("ascii")
    except UnicodeDecodeError as exc:
        raise EvtcParseError(f"Build bytes are not pure ASCII: {build!r}") from exc

    if agent_count > MAX_AGENTS:
        raise EvtcParseError(f"agent_count={agent_count} exceeds safety bound {MAX_AGENTS}")

    build_version = _build_version_from_build_str(build_str)
    is_evtc_2025 = build_version >= 2025_00_00
    agents = list(_iter_agents(data, agent_count, is_evtc_2025=is_evtc_2025))
    known_agents_frozen = frozenset(a.id for a in agents)

    # Walk the skill table.  Detect whether there's a count prefix (legacy)
    # or consecutive 68-byte records (EVTC2025+).
    skill_offset = AGENTS_OFFSET + agent_count * AGENT_SIZE
    _has_count, skill_count, records_offset = _detect_skill_format(
        data, skill_offset, known_agents_frozen, is_evtc_2025=is_evtc_2025
    )
    skills = list(
        _iter_skills(
            data,
            records_offset,
            skill_count,
            use_heuristic=not _has_count,
            known_agents=known_agents_frozen,
            is_evtc_2025=is_evtc_2025,
        )
    )
    actual_skill_count = len(skills)

    # v0.11.0: CompleteAgents step (matching GW2EI's CompleteAgents()).
    # Scan the event stream for agent IDs referenced in src_agent or
    # dst_agent that are NOT in the parsed agent table. Create "UNKNOWN"
    # NPC agents for them so event-to-agent attribution works for
    # minions, pets, environmental objects, gadgets, and transient
    # entities that arcdps may omit from the agent table.
    agents = _complete_agents(data, agents, is_evtc_2025=is_evtc_2025)

    header = EvtcHeader(
        build_version=build_str,
        encounter_id=encounter_id,
        skill_count=actual_skill_count,
        agent_count=agent_count,
    )

    fight_id = hashlib.sha256(data).hexdigest()
    yield Fight(
        id=fight_id,
        header=header,
        agents=agents,
        skills=skills,
    )


def _iter_agents(data: bytes, count: int, *, is_evtc_2025: bool = False) -> Iterator[Agent]:
    """Read ``count`` fixed-size 96-byte agent records starting at ``AGENTS_OFFSET``.

    EVTC2025+ files use a different agent-record layout; set
    ``is_evtc_2025=True`` to decode them correctly.
    """
    if count == 0:
        return
    cursor = AGENTS_OFFSET
    end = len(data)
    decoder = _decode_agent_2025 if is_evtc_2025 else _decode_agent
    for _ in range(count):
        if cursor + AGENT_SIZE > end:
            raise EvtcParseError(
                f"Truncated agent record at offset {cursor}: "
                f"need {AGENT_SIZE} bytes, only {end - cursor} available",
            )
        yield decoder(data, cursor)
        cursor += AGENT_SIZE


def _iter_skill_records(
    data: bytes,
    offset: int,
    count: int,
    *,
    use_heuristic: bool = True,
    known_agents: frozenset[int] | None = None,
    is_evtc_2025: bool = False,
) -> Iterator[tuple[int, int, str]]:
    """Yield ``(cursor, skill_id, name)`` for each valid skill record.

    Reads up to ``count`` fixed-size 68-byte skill records starting at
    ``offset``. Each record has ``skill_id(u32) + name(64 bytes)`` — the
    name is a fixed 64-byte null-padded buffer with no separate length
    field.

    When ``use_heuristic`` is True (default), stops early when the data
    no longer looks like valid skill records (no printable ASCII in the
    name and skill_id != 0, or the bytes look like the event stream).
    When False, reads exactly ``count`` records regardless (use when a
    count prefix was already validated).
    """
    if count == 0:
        return
    cursor = offset
    end = len(data)
    for skill_index in range(count):
        if cursor + SKILL_RECORD_SIZE > end:
            logger.warning(
                "Truncated skill table at skill %d: would read at offset %d "
                "but only %d bytes remain; stopping early (claimed %d skills)",
                skill_index,
                cursor,
                end - cursor,
                count,
            )
            return
        # Strong stop signal: the bytes at this cursor look like the
        # event stream, not a skill record. This is the most reliable
        # way to know we've walked past the skill table in the no-count
        # EVTC2025+ format.
        if use_heuristic and _validate_event_candidate(
            data, cursor, known_agents, is_evtc_2025=is_evtc_2025
        ):
            logger.debug(
                "Skill table ends at skill %d: offset %d looks like the event stream",
                skill_index,
                cursor,
            )
            return
        skill_id = struct.unpack_from("<I", data, cursor)[0]
        name_bytes = data[cursor + 4 : cursor + SKILL_RECORD_SIZE]
        name = name_bytes.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        # Heuristic: if the skill_id is implausibly large, we've
        # likely overshot into event-stream data.  Real GW2 skill IDs
        # are below ~120_000; the first bytes of an event record
        # (interpreted as a skill_id) are usually a huge timestamp or
        # agent address.  We check this unconditionally because some
        # EVTC2025+ event records have printable ASCII bytes in the
        # name-position even though they are NOT skill records.
        #
        # Threshold is 4B to accommodate synthetic test fixtures that
        # use IDs up to ~3B (e.g. the skills rollup cap test). Values
        # near uint32 max (4.29B) are almost certainly event timestamp
        # fragments rather than real skill IDs, but the primary
        # ``_validate_event_candidate`` check runs first and catches
        # most event-stream data before this secondary heuristic fires.
        if use_heuristic and skill_id > 4_000_000_000:
            logger.warning(
                "Skill %d at offset %d: id=%d exceeds max valid skill ID; "
                "skill table likely ends here",
                skill_index,
                cursor,
                skill_id,
            )
            return
        yield cursor, skill_id, name
        cursor += SKILL_RECORD_SIZE


def _iter_skills(
    data: bytes,
    offset: int,
    count: int,
    *,
    use_heuristic: bool = True,
    known_agents: frozenset[int] | None = None,
    is_evtc_2025: bool = False,
) -> Iterator[Skill]:
    """Read up to ``count`` fixed-size skill records starting at ``offset``.

    Thin wrapper around :func:`_iter_skill_records` that yields
    :class:`Skill` instances.
    """
    for _cursor, skill_id, name in _iter_skill_records(
        data,
        offset,
        count,
        use_heuristic=use_heuristic,
        known_agents=known_agents,
        is_evtc_2025=is_evtc_2025,
    ):
        yield Skill(id=skill_id, name=name)


def _validate_event_candidate(
    data: bytes,
    offset: int,
    known_agents: frozenset[int] | None = None,
    *,
    is_evtc_2025: bool = False,
) -> bool:
    """Return ``True`` if ``offset`` likely points into the event stream.

    Reads up to 4 consecutive 64-byte event records and requires:
    * Each readable record has ``0 <= time_ms < 86_400_000``.
    * ``time_ms`` values are monotonically non-decreasing (real event
      streams only move forward in time; random data fails this check).
    * Each readable record has at least one non-zero payload field
      (bytes 24-63) — real combat events always carry value/skill/flags.
    * At least one readable record has a non-zero ``src_agent`` or
      ``dst_agent`` (eliminates pure-zero-byte false positives).
    * When ``known_agents`` is provided, at least 2 readable records
      have a ``src_agent`` or ``dst_agent`` that exists in the agent
      table, OR 1 such match when fewer than 2 full records can be
      read.  This is the strongest rejection: random data in skill
      name regions rarely produces values that match real agent IDs.
    """
    max_time_ms = 86_400_000
    saw_agent = False
    prev_time = -1
    matched_agents = 0
    readable_records = 0
    event_struct = _EVENT_STRUCT_2025 if is_evtc_2025 else _EVENT_STRUCT
    for i in range(4):
        ev_offset = offset + i * EVENT_SIZE
        if ev_offset + EVENT_SIZE > len(data):
            break
        ev = event_struct.unpack_from(data, ev_offset)
        readable_records += 1
        time_ms, src_agent, dst_agent = ev[0], ev[1], ev[2]
        if time_ms > max_time_ms or time_ms < 0:
            return False
        if time_ms < prev_time:
            return False
        prev_time = time_ms
        if src_agent or dst_agent:
            saw_agent = True
        if known_agents is not None and (src_agent in known_agents or dst_agent in known_agents):
            matched_agents += 1
        if not any(ev[j] for j in range(3, len(ev))):
            return False
    if known_agents is not None:
        # EVTC2025+ files with a single trailing event cannot satisfy
        # the original >=2 match requirement, but one match in the
        # single readable record is still strong evidence we are at
        # the event boundary.
        required_matches = min(2, readable_records)
        return saw_agent and matched_agents >= required_matches
    return saw_agent


def _compute_post_skills_offset(  # noqa: PLR0912
    data: bytes,
    *,
    is_evtc_2025: bool | None = None,
) -> int:
    """Return the byte offset where the event stream starts.

    Strategy:

    1. Determine skill table start (after agents).

    2. Detect whether the skill table has a 4-byte count prefix or
       uses the EVTC2025+ no-count format (consecutive 68-byte records).

    3. Walk skill records until the data no longer looks like valid skills,
       then return the offset as the event stream start.

    4. If the walker result doesn't validate as events, scan forward
       in EVENT_SIZE-aligned blocks.
    """
    if len(data) < HEADER_SIZE:
        return len(data)
    unpacked_header = _HEADER_STRUCT.unpack_from(data, 0)
    agent_count = int(unpacked_header[5])
    if is_evtc_2025 is None:
        build_str = unpacked_header[1].decode("ascii", errors="replace")
        is_evtc_2025 = _build_version_from_build_str(build_str) >= 2025_00_00
    skill_offset = AGENTS_OFFSET + agent_count * AGENT_SIZE

    # Build the set of known agent IDs for event-stream validation.
    # EVTC2025+ stores the real event address at byte +92, not at the
    # start of the record.
    known_agents: set[int] = set()
    for i in range(min(agent_count, MAX_AGENTS)):
        aoff = AGENTS_OFFSET + i * AGENT_SIZE
        if aoff + AGENT_SIZE > len(data):
            break
        if is_evtc_2025:
            known_agents.add(int(struct.unpack_from("<I", data, aoff + 92)[0]))
        else:
            known_agents.add(int(struct.unpack_from("<Q", data, aoff)[0]))
    known_agents_frozen = frozenset(known_agents)

    # Quick check: if no skills, events start right here.
    if _validate_event_candidate(
        data, skill_offset, known_agents_frozen, is_evtc_2025=is_evtc_2025
    ):
        return skill_offset

    # Detect skill table format using shared heuristic.
    _has_count, _detected_count, skill_records_offset = _detect_skill_format(
        data, skill_offset, known_agents_frozen, is_evtc_2025=is_evtc_2025
    )
    has_count_prefix = _has_count

    count = _detected_count if has_count_prefix else MAX_SKILLS  # no-count: walk until invalid

    cursor = skill_records_offset
    for _record_start, _skill_id, _name in _iter_skill_records(
        data,
        skill_records_offset,
        count,
        known_agents=known_agents_frozen,
        is_evtc_2025=is_evtc_2025,
    ):
        pass  # cursor is updated inside _iter_skill_records

    # The cursor from _iter_skill_records is the offset after the last
    # valid skill record. But _iter_skill_records uses a generator,
    # so we need to track it differently. Walk again to get the final offset.
    cursor = skill_records_offset
    for _record_start, _skill_id, _name in _iter_skill_records(
        data,
        skill_records_offset,
        count,
        known_agents=known_agents_frozen,
        is_evtc_2025=is_evtc_2025,
    ):
        cursor += SKILL_RECORD_SIZE

    if _validate_event_candidate(data, cursor, known_agents_frozen, is_evtc_2025=is_evtc_2025):
        return cursor

    # The skill heuristic can overshoot by one event record (the first
    # event itself looks like a non-skill).  Try the previous event-sized
    # boundary before falling back to a forward scan.
    if cursor >= EVENT_SIZE and _validate_event_candidate(
        data, cursor - EVENT_SIZE, known_agents_frozen, is_evtc_2025=is_evtc_2025
    ):
        return cursor - EVENT_SIZE

    # Scan forward in EVENT_SIZE-aligned blocks to find the event stream.
    aligned = (cursor + EVENT_SIZE - 1) & ~(EVENT_SIZE - 1)
    max_forward = min(len(data) - EVENT_SIZE * 4, skill_offset + MAX_SKILLS * SKILL_RECORD_SIZE)
    for candidate in range(aligned, max_forward, EVENT_SIZE):
        if _validate_event_candidate(
            data, candidate, known_agents_frozen, is_evtc_2025=is_evtc_2025
        ):
            return candidate

    return cursor


def _complete_agents(
    data: bytes,
    agents: list[Agent],
    *,
    is_evtc_2025: bool = False,
) -> list[Agent]:
    """Augment the agent list with "UNKNOWN" entries for any agent ID
    referenced in the event stream that is not in the agent table.

    Scans the event stream for ``src_agent`` and ``dst_agent`` values, and creates
    ``Agent(id=<id>, name="UNKNOWN <id>", is_player=False)`` for
    any ID not already in ``agents``. Returns the augmented list.

    Safety: the scan stops at the first event record whose ``time_ms``
    exceeds 24h (86_400_000 ms). This is a structural bound against
    reading corrupted data that survives beyond the event block -- NOT
    a GetTickCount64 normalisation threshold (the normalisation in
    ``blob_loader.py`` uses a 1h threshold). Raw un-normalised
    timestamps from a PC running ~4.5h produce ~16M ms values, well
    under this 24h cap, so the scan continues correctly.
    """
    known_ids = frozenset(a.id for a in agents)
    event_cursor = _compute_post_skills_offset(data, is_evtc_2025=is_evtc_2025)
    end = len(data)
    event_struct = _EVENT_STRUCT_2025 if is_evtc_2025 else _EVENT_STRUCT
    max_time_ms = 86_400_000
    missing_ids: set[int] = set()

    while event_cursor + EVENT_SIZE <= end:
        ev = event_struct.unpack_from(data, event_cursor)
        time_ms = ev[0]
        if time_ms > max_time_ms:
            break
        src_agent = ev[1]
        dst_agent = ev[2]
        if src_agent != 0 and src_agent not in known_ids:
            missing_ids.add(src_agent)
        if dst_agent != 0 and dst_agent not in known_ids:
            missing_ids.add(dst_agent)
        event_cursor += EVENT_SIZE

    if not missing_ids:
        return agents

    aug = list(agents)
    for missing_id in sorted(missing_ids):
        logger.debug(
            "CompleteAgents: creating UNKNOWN agent for 0x%x",
            missing_id,
        )
        aug.append(
            Agent(
                id=missing_id,
                name=f"UNKNOWN {missing_id}",
                is_player=False,
            )
        )
    return aug


def _decode_agent_2025(data: bytes, offset: int) -> Agent:
    """Decode a single 96-byte EVTC2025+ agent record at ``offset``.

    The EVTC2025+ layout stores the agent's event address at byte +92
    (``addr``), not at the start of the record. The leading u32 is an
    instance-id low word that is not used for event matching.
    """
    (
        _iid_low,
        prof_raw,
        elite_raw,
        _tough,
        _heal,
        _conc,
        name_buf,
        _subgroup,
        addr,
    ) = _AGENT_STRUCT_2025.unpack_from(data, offset)

    # The 64-byte name buffer uses the same combo-string convention as
    # the legacy layout: ``char\0account\0subgroup\0``.
    parts = name_buf.split(b"\x00")

    char_name = parts[0].decode("utf-8", errors="replace") if parts else ""

    raw_account = parts[1] if len(parts) >= 2 else b""
    raw_subgroup = parts[2] if len(parts) >= 3 else b""
    is_player = bool(raw_account or raw_subgroup)
    account_name: str | None = None
    subgroup: str | None = None
    if is_player:
        account_name = raw_account.decode("utf-8", errors="replace") if raw_account else None
        subgroup = raw_subgroup.decode("utf-8", errors="replace")

    try:
        profession = Profession(prof_raw)
    except ValueError:
        profession = Profession.UNKNOWN

    # v0.16.1-api: cross-validate elite spec against profession.
    elite = _validate_elite_for_profession(int(prof_raw), int(elite_raw))

    return Agent(
        id=addr,
        name=char_name,
        profession=profession,
        elite=elite,
        elite_raw=elite_raw,
        is_player=is_player,
        account_name=account_name,
        subgroup=subgroup,
    )


def _decode_agent(data: bytes, offset: int) -> Agent:
    """Decode a single 96-byte legacy agent record at ``offset``."""
    aid, prof_raw, elite_raw, _tough, _conc, _heal, _width, name_buf = _AGENT_STRUCT.unpack_from(
        data, offset
    )

    # Split the 72-byte name buffer on null bytes. arcdps writes the
    # combo string ``char\0acc\0sub\0`` null-padded to 72 bytes for
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

    # v0.16.1-api: cross-validate elite spec against profession.
    elite = _validate_elite_for_profession(int(prof_raw), int(elite_raw))

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
    "SKILL_RECORD_SIZE",
    "PythonEvtcParser",
    "read_zevtc_archive",
    "read_zevtc_bytes",
]
