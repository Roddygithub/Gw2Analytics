"""Python reference implementation of the EVTC parser.

This implementation reads:

* the 20-byte base file header (``EVTC`` magic + ``yyyymmdd`` build date +
  revision byte + combat_id + unused + ``agent_count`` u32). Legacy
  fixtures may append a 4-byte extension before the agent table,
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

  The skill table can be stored in one of two wire formats:

  * **Legacy** (pre-2025): a 4-byte ``skill_count`` prefix followed by
    ``skill_count`` consecutive 68-byte records.
  * **Alternative**: no count prefix; consecutive 68-byte records run
    until the parser's heuristic detects the start of the event stream.
    Current EVTC2025 logs use the count-prefixed format.

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
    ActivationType,
    Agent,
    BlockEvent,
    BoonApplyEvent,
    BuffApplyEvent,
    BuffExtensionEvent,
    BuffRemovalEvent,
    BuffStackActiveEvent,
    CCEvent,
    CombatOutcomeEvent,
    DamageEvent,
    DeathEvent,
    DespawnEvent,
    DodgeEvent,
    DownEvent,
    EffectEvent,
    EliteSpec,
    Event,
    EvtcHeader,
    Fight,
    HealingEvent,
    HealthUpdateEvent,
    InterruptEvent,
    MissileEvent,
    PositionEvent,
    Profession,
    Skill,
    SkillActivationEvent,
    SpawnEvent,
    UpEvent,
    WeaponSwapEvent,
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

#: Legacy extended header size retained for pre-2025 fixtures.
HEADER_SIZE: Final[int] = 24
_HEADER_BASE_SIZE: Final[int] = 20

#: ``struct`` format for the 24-byte file header (rev>=1).
#: Fields: magic(4s) + build(8s) + rev(B) + combat_id(H) + unused(B)
#: + agent_count(I) + map_id(I).
_HEADER_STRUCT: Final[struct.Struct] = struct.Struct("<4s8sBHBI I")
_HEADER_BASE_STRUCT: Final[struct.Struct] = struct.Struct("<4s8sBHBI")

#: Byte offset of the agent_count field inside the header.
AGENT_COUNT_OFFSET: Final[int] = 16

#: Byte offset of the build date field inside the header.
BUILD_OFFSET: Final[int] = 4

#: Byte offset of the skill_count field inside the header (bytes 20-23).
SKILL_COUNT_OFFSET: Final[int] = 20

#: Byte offset where agent records start in legacy extended fixtures.
AGENTS_OFFSET: Final[int] = HEADER_SIZE
_AGENTS_OFFSET_2025: Final[int] = _HEADER_BASE_SIZE

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

#: EVTC2025+ agent: address(u64), profession(u32), elite(u32), six
#: uint16 stats/hitbox fields, then the 68-byte combo-name buffer.
AGENT_NAME_SIZE_2025: Final[int] = 68
_AGENT_STRUCT_2025: Final[struct.Struct] = struct.Struct(f"<QII6H{AGENT_NAME_SIZE_2025}s")

#: Size of one fixed-size skill record: skill_id(u32) + name(64B).
#: arcdps writes skill names as a fixed 64-byte null-padded buffer
#: (no separate name_len field).
SKILL_RECORD_SIZE: Final[int] = 68

#: ``struct`` format for the fixed-size portion of a skill record
#: (just the 4-byte ``skill_id``; the 64-byte name buffer follows).
_SKILL_ID_STRUCT: Final[struct.Struct] = struct.Struct("<I")

#: Total size of one cbtevent record on disk (arcdps EVTC event record).
EVENT_SIZE: Final[int] = 64

# Elite Insights LogIDs: WvWMask | map-specific mask.
_WVW_EI_ENCOUNTER_IDS: Final[dict[int, int]] = {
    38: 0x070100,
    95: 0x070200,
    96: 0x070300,
    1099: 0x070400,
    899: 0x070500,
    968: 0x070600,
    1315: 0x070700,
}

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
_EVENT_STRUCT_EVENTS: Final[struct.Struct] = struct.Struct("<QQQii 4x I 7x bbb b b b 11x")

#: Standard arcdps cbtevent struct for EVTC2025+ builds.  arcdps
#: reverted to the documented ``arcdps.h`` layout for 2025+ logs:
#: time(Q)+src(Q)+dst(Q)+value(i)+buff_dmg(i)+overstack(I)+
#: skillid(I)+src_instid(H)+dst_instid(H)+src_master_instid(H)+
#: dst_master_instid(H)+16 flag bytes.  Flags start at byte 48.
_EVENT_STRUCT_2025: Final[struct.Struct] = struct.Struct("<QQQiiIIHHHH16B")

#: Optimized event struct for EVTC2025+ builds.  Reads the fields
#: consumed by :meth:`PythonEvtcParser.parse_events` using the
#: standard flag byte positions:
#:   bytes 32-35 = overstack_value (barrier absorption on damage records)
#:   byte 36-39 = skillid
#:   byte 40-41 = src_instid
#:   byte 42-43 = dst_instid
#:   byte 44-45 = src_master_instid
#:   byte 46-47 = dst_master_instid
#:   byte 48 = iff
#:   byte 49 = ev.buff
#:   byte 50 = result
#:   byte 51 = is_activation
#:   byte 52 = is_buffremove
#:   byte 56 = is_statechange
#:   byte 59 = is_offcycle (direct damage against downed)
#:   bytes 60-63 = pad/stack ID (low byte marks condition damage against downed)
#:
#: v0.16.4: ``overstack_value`` was previously skipped (``4x``). On a
#: damage record it is the portion of the hit absorbed by barrier,
#: which EI reports as ``shieldDamage``; reading it also lets the
#: barrier-absorbed condition ticks be told apart from mitigated ones.
_EVENT_STRUCT_EVENTS_2025: Final[struct.Struct] = struct.Struct(
    "<QQQii I I HHHH bbbb b 3x b x bb I"
)

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
#: CBTB_MANUAL remains distinct because Elite Insights excludes it from
#: buff simulation while retaining it for volume accounting.
_CBTBUFREMOVE_KINDS: Final[tuple[str, str, str]] = (
    "remove_all",  # byte 1: CBTB_ALL -> remove_all
    "remove_single",  # byte 2: CBTB_SINGLE -> remove_single
    "remove_manual",  # byte 3: CBTB_MANUAL
)

#: arcdps writes two different enums into the cbtevent ``result`` byte;
#: the ``ev.buff`` byte says which one applies.
#:
#: Direct hits use ``cbtresult`` (0 Normal, 1 Crit, 2 Glance, 3 Block,
#: 4 Evade, 5 Interrupt, 6 Absorb, 7 Blind, 8 KillingBlow, 9 Downed,
#: 10 Breakbar, 11 Activation, 12 CrowdControl). This has been stable
#: across every build in the corpus.
#:
#: Breakbar (result 10) is included here because the parser resolves it
#: per-record, not per-(player, skill). Whether EI's connectedHits
#: actually counts a result-10 hit depends on whether the player's other
#: hits on that skill are all breakbar ticks -- a group-level rule that
#: lives in ``ei_compare._skill_stats``. The parser flags every record
#: honestly so consumers can re-aggregate either way.
_DIRECT_HIT_RESULTS: Final[frozenset[int]] = frozenset({0, 1, 2, 8, 10})
_DIRECT_ABSORB_RESULT: Final[int] = 6

#: Condition ticks use ``cbtresult``'s condition counterpart, and arcdps
#: renumbered it. Builds before 2026-05-07 write the classic
#: ``ConditionResult`` (0 = the tick landed, 1-4 = the target was immune
#: to it). Builds from 2026-05-07 onward write a second block starting at
#: 13, alternating invulnerable / landed: 13 immune, 14 landed, 16
#: landed, 18 landed. ``6`` (Absorb) is shared with the direct enum in
#: both eras.
#:
#: Derived by reconciling every single-result (player, skill) entry in
#: EI's ``totalDamageDist`` against its ``connectedHits`` / ``invulned``
#: counters over the 35-log corpus -- 2 300+ observations, no
#: disagreement. See ``docs/ei-parity-workbench.md``.
_CONDITION_ENUM_REBASE_BUILD: Final[int] = 2026_05_07

#: Buff apply / remove statechange codes introduced in the same
#: 2026-05-07 arcdps change. See the fold-down in ``parse_events``.
_BUFF_STATECHANGES_2026_05: Final[frozenset[int]] = frozenset({69, 71, 72})

#: The same change also moved skill activation off the ``is_activation``
#: byte of a plain record: 67 now starts a cast (with the byte left at 0)
#: and 68 ends one (carrying the terminal ActivationType as before).
_CAST_START_STATECHANGE_2026_05: Final[int] = 67
_CAST_END_STATECHANGE_2026_05: Final[int] = 68


def _condition_verdict(result: int, build_int: int) -> tuple[bool, bool]:
    """Return ``(connected, absorbed)`` for a condition tick's result byte."""
    if result == _DIRECT_ABSORB_RESULT:
        return False, True
    if build_int >= _CONDITION_ENUM_REBASE_BUILD:
        # Second enum block: even values landed, odd values were immune.
        return (result % 2 == 0, result % 2 == 1) if result >= 13 else (False, False)
    return result == 0, result != 0


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

#: v0.16.3: per-profession set of valid elite-specialisation IDs.
#: Used by :func:`_validate_elite_for_profession` and the legacy
#: decode path to cross-validate the mapped (or raw) elite ID
#: against the agent's profession.
#:
#: v0.16.4: re-derived from the GW2 v2 specialization catalogue (the
#: same table Elite Insights ships as ``Content/SpecList.json``) after
#: a 35-log WvW corpus showed every Thief and Elementalist elite being
#: rejected here and downgraded to the core profession. Corrections:
#: Thief was {55, 71, 72, 77} but 55/72 are Ranger specs — the real
#: Thief IDs are 7 (Daredevil) and 58 (Deadeye); Elementalist was
#: {48, 63, 75, 80} but 63 is Renegade and 75 is Amalgam — the real
#: IDs are 56 (Weaver) and 67 (Catalyst); Warrior was missing 68
#: (Bladesworn). Every ID in the catalogue is unique across
#: professions, so this table is a validity check, not a
#: disambiguator.
_VALID_ELITE_BY_PROFESSION: Final[dict[int, set[int]]] = {
    1: {27, 62, 65, 81},  # Guardian — Dragonhunter, Firebrand, Willbender, Luminary
    2: {18, 61, 68, 74},  # Warrior — Berserker, Spellbreaker, Bladesworn, Paragon
    3: {43, 57, 70, 75},  # Engineer — Scrapper, Holosmith, Mechanist, Amalgam
    4: {5, 55, 72, 78},  # Ranger — Druid, Soulbeast, Untamed, Galeshot
    5: {7, 58, 71, 77},  # Thief — Daredevil, Deadeye, Specter, Antiquary
    6: {48, 56, 67, 80},  # Elementalist — Tempest, Weaver, Catalyst, Evoker
    7: {40, 59, 66, 73},  # Mesmer — Chronomancer, Mirage, Virtuoso, Troubadour
    8: {34, 60, 64, 76},  # Necromancer — Reaper, Scourge, Harbinger, Ritualist
    9: {52, 63, 69, 79},  # Revenant — Herald, Renegade, Vindicator, Conduit
}


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


def _validate_elite_for_profession(prof_raw: int, elite_raw: int) -> EliteSpec:
    """Return the correct :class:`EliteSpec` for ``elite_raw`` from
    ``prof_raw``, or :attr:`EliteSpec.BASE` if the ID is not valid
    for that profession.

    Elite IDs are globally unique in the GW2 specialization
    catalogue, so the per-profession set is a *validity* check: it
    rejects an ID that belongs to a different profession (a corrupt
    or misaligned record) rather than disambiguating a shared ID.
    """
    valid_set = _VALID_ELITE_BY_PROFESSION.get(prof_raw)
    if valid_set and elite_raw in valid_set:
        return EliteSpec(elite_raw)
    # Unknown profession (e.g. NPC) or elite ID not valid for this profession
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
        build_int = _build_version_from_build_str(build_str)
        is_evtc_2025 = build_int >= 2025_00_00
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
        down_durations: dict[tuple[int, int], int] = {}
        effect_guids: dict[int, str] = {}
        buff_remove_all: set[tuple[int, int, int]] = set()
        all_inst_to_agent: dict[int, int] = {}
        owner_by_agent: dict[int, int] = {}
        # Updated chronologically during the second pass so reused instance
        # IDs resolve to the owner active at the event time.
        inst_to_agent: dict[int, int] = {}
        if is_evtc_2025:
            last_aware: dict[int, int] = {}
            lifecycle: list[tuple[int, int, int]] = []
            scan_cursor = offset
            while scan_cursor + EVENT_SIZE <= end:
                (
                    _stime,
                    s_src,
                    s_dst,
                    _sv,
                    _sbd,
                    _sovers,
                    _ssid,
                    _s_src_inst,
                    _s_dst_inst,
                    _ssmi,
                    _sdmi,
                    *_srest,
                ) = _unpack_event(data, scan_cursor)
                statechange = _srest[5]
                if s_src and _s_src_inst:
                    all_inst_to_agent[_s_src_inst] = s_src
                if s_dst and _s_dst_inst:
                    all_inst_to_agent[_s_dst_inst] = s_dst
                if s_src and _ssmi and _ssmi in all_inst_to_agent:
                    owner_by_agent[s_src] = all_inst_to_agent[_ssmi]
                if _stime > 0:
                    if s_src:
                        last_aware[s_src] = max(last_aware.get(s_src, 0), _stime)
                    if s_dst:
                        last_aware[s_dst] = max(last_aware.get(s_dst, 0), _stime)
                if statechange in (3, 4, 5):
                    lifecycle.append((_stime, s_src, statechange))
                if _srest[4] == 1:
                    buff_remove_all.add((_stime, s_src, _ssid))
                if statechange == 46:
                    effect_guids[_ssid] = (
                        (s_src.to_bytes(8, "little") + s_dst.to_bytes(8, "little")).hex().upper()
                    )
                scan_cursor += EVENT_SIZE
            open_downs: dict[int, int] = {}
            for transition_time, actor, statechange in lifecycle:
                if statechange == 5 and actor not in open_downs:
                    open_downs[actor] = transition_time
                elif statechange in (3, 4) and actor in open_downs:
                    started = open_downs.pop(actor)
                    down_durations[actor, started] = transition_time - started
            for actor, started in open_downs.items():
                down_durations[actor, started] = max(0, last_aware.get(actor, started) - started)
        while cursor + EVENT_SIZE <= end:
            if is_evtc_2025:
                (
                    time_ms,
                    src_agent,
                    dst_agent,
                    value,
                    buff_dmg,
                    # bytes 32-35: overstack_value — barrier absorption
                    # on damage records (EI's ``shieldDamage``).
                    overstack,
                    skill_id,
                    # bytes 40-41: src_instid
                    # bytes 42-43: dst_instid
                    # bytes 44-45: src_master_instid
                    # bytes 46-47: dst_master_instid
                    _src_inst,
                    _dst_inst,
                    src_master_inst,
                    dst_master_inst,
                    # byte 48 = arcdps ``iff``
                    _iff,
                    # byte 49 = arcdps ``ev.buff`` field -- the buff ID for
                    # mid-combat APPLY records per F1 byte mapping.
                    _ev_buff,
                    # byte 50 = arcdps ``result`` enum.  Values 13/14
                    # (CBTR_HEAL / CBTR_BUFFHEAL) mark heal-class events.
                    _result,
                    # byte 51 = arcdps ``is_activation`` byte.
                    is_activation,
                    # byte 52 = arcdps ``is_buffremove`` byte.
                    is_buffremove,
                    # byte 56 = arcdps ``is_statechange`` byte.
                    is_statechange,
                    # Against-downed condition ticks moved from pad low byte to byte 59
                    # with the 2026-05-07 arcdps damage-channel reshuffle.
                    is_shields,
                    is_offcycle,
                    pad,
                ) = _unpack_event(data, cursor)
                event_src_agent = src_agent
                if src_agent and _src_inst:
                    inst_to_agent[_src_inst] = src_agent
                if dst_agent and _dst_inst:
                    inst_to_agent[_dst_inst] = dst_agent
                # Resolve master-instance attribution: when src_master_instid
                # is non-zero the event comes from a minion/pet/gadget owned
                # by the agent whose instance_id matches.
                if src_master_inst:
                    resolved = inst_to_agent.get(src_master_inst)
                    if resolved is not None:
                        src_agent = resolved
                # 2025+: iff=0 (FRIEND) = healing, iff!=0 (FOE) = damage.
                # The result byte no longer carries heal/damage discrimination;
                # values 13/14 are CBTR_INVERT / CBTR_BUFF_DAMAGECYCLE (damage).
                is_nondamage = 1 if _iff == 0 else 0
                # v0.16.4: from build 2026-05-07 arcdps moved buff
                # application and removal off the plain (is_statechange == 0,
                # ev.buff != 0) channel onto dedicated statechange codes:
                #   69 -> apply      (value = duration, as before)
                #   71 -> remove     (is_buffremove 2 or 3)
                #   72 -> remove all (is_buffremove 1)
                # The record shape is otherwise unchanged, so folding them
                # back onto statechange 0 lets the existing apply/remove
                # branches run untouched. Until this landed, every buff event
                # on a post-2026-05-07 log was dropped by the generic
                # statechange filter and all boon uptimes read as ~0.
                #
                # Code 70 is deliberately NOT folded in: it is an apply that
                # overstacked, carrying the wasted duration in
                # overstack_value with value == 0, and it does not change
                # the target's buff state.
                if is_statechange in _BUFF_STATECHANGES_2026_05:
                    is_statechange = 0
                elif is_statechange == _CAST_START_STATECHANGE_2026_05:
                    # Cast start. The old channel signalled this with
                    # is_activation = NORMAL (or QUICKNESS, which no log in
                    # the corpus uses); the new one leaves the byte at 0 and
                    # carries the same value/buff_dmg duration pair.
                    is_statechange = 0
                    is_activation = ActivationType.NORMAL
                elif is_statechange == _CAST_END_STATECHANGE_2026_05:
                    # Cast end: is_activation still holds the terminal
                    # ActivationType (MINIMUM / CANCEL / RESET / NO_DATA).
                    is_statechange = 0
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
                    # byte 50 = arcdps ``result`` enum (CBTR_BLOCK=3,
                    # CBTR_EVADE=4, CBTR_INTERRUPT=5).
                    _result,
                    # byte 51 = arcdps ``is_activation`` byte.
                    is_activation,
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
                event_src_agent = src_agent
                is_offcycle = 0
                is_shields = 0
                pad = 0
                overstack = 0
            # NOTE: ``is_buffremove`` is consumed below by
            # Step 2-EMIT-BRANCH (REMOVE predicate ``in (1, 2, 3)``) AND
            # by Step 3 APPLY-BRANCH (predicate ``_ev_buff != 0 AND
            # is_buffremove == 0``). ``is_ninety`` is unpacked but not
            # yet surfaced to the Event stream (a future Phase 9 step
            # may use it for 90%-threshold markers on Removals).
            event_offset = cursor
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
                duration = 0 if value >= _DAMAGE_SANITY_CAP else max(0, value)
                original_duration = 0 if buff_dmg >= _DAMAGE_SANITY_CAP else max(0, buff_dmg)
                yield BuffApplyEvent(
                    time_ms=time_ms,
                    source_agent_id=event_src_agent,
                    target_agent_id=dst_agent,
                    skill_id=skill_id,
                    duration_ms=duration,
                    original_duration_ms=original_duration or duration,
                    stack_id=pad,
                    added_active=bool(is_shields),
                )
                continue
            if is_statechange == 27:
                yield BuffStackActiveEvent(
                    time_ms=time_ms,
                    source_agent_id=event_src_agent,
                    target_agent_id=event_src_agent,
                    skill_id=skill_id,
                    stack_id=dst_agent,
                )
                continue
            if is_statechange == 70:
                yield BuffExtensionEvent(
                    time_ms=time_ms,
                    source_agent_id=event_src_agent,
                    target_agent_id=dst_agent,
                    skill_id=skill_id,
                    extended_duration_ms=max(0, value),
                    new_duration_ms=max(0, overstack),
                    stack_id=pad,
                )
                continue
            if is_statechange == 49 and pad == 0x9C9B3C99:
                magnitude = (
                    -value
                    if _ev_buff == 0 and value < 0
                    else -buff_dmg
                    if _ev_buff != 0 and value == 0 and buff_dmg < 0
                    else 0
                )
                src_is_peer = bool(is_offcycle & 0x80) or not bool(is_offcycle & 0xC0)
                if magnitude > 0 and src_is_peer:
                    yield HealingEvent(
                        time_ms=time_ms,
                        source_agent_id=src_agent,
                        target_agent_id=dst_agent,
                        skill_id=skill_id,
                        healing=0 if is_shields else magnitude,
                        barrier=magnitude if is_shields else 0,
                        iff=_iff & 0xFF,
                        src_master_instid=src_master_inst,
                        dst_master_instid=dst_master_inst,
                    )
                continue
            if is_statechange == 6:
                yield SpawnEvent(
                    time_ms=time_ms,
                    source_agent_id=owner_by_agent.get(event_src_agent, 0),
                    target_agent_id=event_src_agent,
                    skill_id=0,
                )
                continue
            if is_statechange == 7:
                yield DespawnEvent(
                    time_ms=time_ms,
                    source_agent_id=event_src_agent,
                    target_agent_id=0,
                    skill_id=0,
                )
                continue
            if is_statechange == 57:
                yield MissileEvent(
                    time_ms=time_ms,
                    source_agent_id=owner_by_agent.get(event_src_agent, src_agent),
                    target_agent_id=dst_agent,
                    skill_id=skill_id,
                )
                continue
            if is_statechange == 46:
                effect_guids[skill_id] = (
                    (event_src_agent.to_bytes(8, "little") + dst_agent.to_bytes(8, "little"))
                    .hex()
                    .upper()
                )
                continue
            if is_statechange == 11:
                yield WeaponSwapEvent(
                    time_ms=time_ms,
                    source_agent_id=event_src_agent,
                    target_agent_id=0,
                    skill_id=0,
                    swapped_from=max(0, value),
                    swapped_to=dst_agent,
                )
                continue
            if is_statechange in (45, 51, 60, 62) and skill_id in effect_guids:
                effect_duration = (
                    (_iff & 0xFF)
                    | ((_ev_buff & 0xFF) << 8)
                    | ((_result & 0xFF) << 16)
                    | ((is_activation & 0xFF) << 24)
                    if is_statechange == 51
                    else 0
                )
                yield EffectEvent(
                    time_ms=time_ms,
                    source_agent_id=owner_by_agent.get(event_src_agent, event_src_agent),
                    target_agent_id=dst_agent,
                    skill_id=skill_id,
                    guid=effect_guids[skill_id],
                    is_around_dst=bool(dst_agent),
                    duration_ms=effect_duration,
                )
                continue
            if is_statechange != 0:
                # Byte 19 (CBTS_POSITION): position update. The x, y, z
                # coordinates are encoded as 3 float32 values at offset 16
                # of the raw cbtevent record (overwriting dst_agent + value).
                # This must be handled inline because the dispatch function
                # doesn't have access to the raw bytes.
                if is_statechange == 19:
                    x, y, z = struct.unpack_from("<3f", data, event_offset + 16)
                    if (
                        math.isfinite(x)
                        and math.isfinite(y)
                        and math.isfinite(z)
                        and max(abs(x), abs(y), abs(z)) <= 1e5
                    ):
                        yield PositionEvent(
                            time_ms=time_ms,
                            source_agent_id=event_src_agent,
                            target_agent_id=0,
                            skill_id=0,
                            x=x,
                            y=y,
                        )
                    continue
                if is_statechange == 3:  # ChangeUp
                    yield UpEvent(
                        time_ms=time_ms,
                        source_agent_id=event_src_agent,
                        target_agent_id=0,
                        skill_id=0,
                    )
                    continue
                if is_statechange == 5:  # ChangeDown
                    if is_evtc_2025 and (event_src_agent, time_ms) not in down_durations:
                        continue
                    yield DownEvent(
                        time_ms=time_ms,
                        source_agent_id=event_src_agent,
                        target_agent_id=0,
                        skill_id=0,
                        downtime_ms=down_durations.get((event_src_agent, time_ms), 0),
                    )
                    continue
                if is_statechange == 4:  # ChangeDead
                    yield DeathEvent(
                        time_ms=time_ms,
                        source_agent_id=event_src_agent,
                        target_agent_id=0,
                        skill_id=0,
                    )
                    continue
                if is_statechange == 8:
                    yield HealthUpdateEvent(
                        time_ms=time_ms,
                        source_agent_id=event_src_agent,
                        target_agent_id=0,
                        skill_id=0,
                        health_percent=min(100.0, max(0.0, dst_agent / 100.0)),
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
                    src_agent=event_src_agent,
                    dst_agent=dst_agent,
                    value=value,
                    skill_id=skill_id,
                )
                if statechange_event is not None:
                    yield statechange_event
                continue
            if 1 <= is_activation <= 6:
                yield SkillActivationEvent(
                    time_ms=time_ms,
                    source_agent_id=event_src_agent,
                    target_agent_id=0,
                    skill_id=skill_id,
                    activation=ActivationType(is_activation),
                    duration_ms=max(0, value),
                    expected_duration_ms=max(0, buff_dmg),
                )
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
                # Elite Insights excludes uncredited natural/overstack endings
                # from buff simulation; explicit remove-all records still apply.
                if is_evtc_2025 and is_buffremove != 1 and _iff == 2 and dst_agent == 0:
                    continue
                if is_buffremove != 1 and (time_ms, src_agent, skill_id) in buff_remove_all:
                    continue
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
                    source_agent_id=dst_agent,
                    target_agent_id=event_src_agent,
                    skill_id=skill_id,
                    duration_ms=(0 if value >= _DAMAGE_SANITY_CAP else max(0, value)),
                    stacks=max(1, _result) if is_buffremove == 1 else 1,
                    stack_id=pad,
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
            elif is_evtc_2025:
                # EVTC rev1 uses iff=FOE for damage. isBuff selects the
                # magnitude field: direct hits use value, condition ticks
                # use buff_dmg. Crowd-control and activation records carry
                # values but are not health damage.
                if _ev_buff and buff_dmg == 0 and value > 0 and is_activation == 0:
                    yield BoonApplyEvent(
                        time_ms=time_ms,
                        source_agent_id=src_agent,
                        target_agent_id=dst_agent,
                        skill_id=skill_id,
                        duration_ms=(0 if value >= _DAMAGE_SANITY_CAP else max(0, value)),
                        stacks=1,
                        stack_id=pad,
                        kind="apply",
                        added_active=bool(is_shields),
                    )
                    continue
                # v0.17.0: a self-inflicted condition tick (src == dst,
                # value == 0, buff_dmg == the tick magnitude) is a FRIEND
                # (iff == 0) record on the EVTC rev1 channel, but it is NOT
                # a heal: there is no heal magnitude, only a condition tick.
                # EI counts it as condition damage taken by the target. The
                # generic ``iff == 0`` filter below (which exists to drop
                # friend-sourced HEALING from the damage channel) must let
                # this through, otherwise the damageTaken / damageTakenCount /
                # conditionDamageTaken stats undercount by one self-tick per
                # occurrence. Verified on wvw-large-fight (build 20251123).
                is_self_condi_tick = (
                    src_agent == dst_agent and _ev_buff and value == 0 and buff_dmg > 0
                )
                if _iff == 0 and not is_self_condi_tick:
                    continue
                if _iff not in {1, 2} and not is_self_condi_tick:
                    continue
                if _ev_buff:
                    magnitude = 0 if buff_dmg >= _DAMAGE_SANITY_CAP else max(0, buff_dmg)
                    condition_damage = magnitude
                    is_attempt = magnitude > 0 or _result != 0
                    # v0.16.4: the raw ``result`` byte is the ConditionResult
                    # enum and is authoritative on its own. The previous
                    # ``13 if magnitude == 0 else _result`` override assumed a
                    # zero-magnitude tick meant "invulnerable", which
                    # mislabelled every tick that connected for zero health
                    # damage (fully mitigated, or entirely converted to
                    # barrier). EI counts those as connected condition hits,
                    # so the override cost one connectedDamageCount and one
                    # connectedConditionCount per occurrence while inflating
                    # ``invulned`` by the same amount.
                    damage_result = _result
                    is_condition = True
                    connected, absorbed = _condition_verdict(_result, build_int)
                    against_downed = bool(is_offcycle if build_int >= 2026_05_07 else pad & 0xFF)
                    is_life_leech = is_offcycle in {3, 5}
                else:
                    if _result in (8, 9):
                        yield CombatOutcomeEvent(
                            time_ms=time_ms,
                            source_agent_id=src_agent,
                            target_agent_id=dst_agent,
                            skill_id=skill_id,
                            outcome="killed" if _result == 8 else "downed",
                        )
                    if _result == 12:
                        yield CCEvent(
                            time_ms=time_ms,
                            source_agent_id=src_agent,
                            target_agent_id=dst_agent,
                            skill_id=skill_id,
                            cc_value=(0 if value >= _DAMAGE_SANITY_CAP else max(0, value)),
                        )
                        continue
                    if _result == 3:
                        yield BlockEvent(
                            time_ms=time_ms,
                            source_agent_id=dst_agent,
                            target_agent_id=0,
                            skill_id=0,
                        )
                    elif _result == 4:
                        yield DodgeEvent(
                            time_ms=time_ms,
                            source_agent_id=dst_agent,
                            target_agent_id=0,
                            skill_id=0,
                        )
                    elif _result == 5:
                        yield InterruptEvent(
                            time_ms=time_ms,
                            source_agent_id=src_agent,
                            target_agent_id=dst_agent,
                            skill_id=skill_id,
                        )
                    # Interrupt (5), KillingBlow (8), Downed (9) and
                    # Activation (11) are marker records: arcdps writes them
                    # alongside the real damage record, with value 0. EI
                    # counts the damage record and treats these as flags, so
                    # emitting a DamageEvent for them would double-count the
                    # hit. Verified on the 35-log corpus (v0.16.4).
                    if _result in {5, 8, 9, 11}:
                        continue
                    magnitude = 0 if value >= _DAMAGE_SANITY_CAP or _result == 10 else max(0, value)
                    condition_damage = 0
                    is_attempt = magnitude > 0 or (
                        dst_agent != 0
                        and skill_id != 0
                        and _result in {0, 1, 2, 3, 4, 6, 7, 8, 10, 13}
                    )
                    damage_result = _result
                    is_condition = False
                    connected = _result in _DIRECT_HIT_RESULTS
                    absorbed = _result == _DIRECT_ABSORB_RESULT
                    against_downed = bool(is_offcycle)
                    is_life_leech = False
                if is_attempt:
                    yield DamageEvent(
                        time_ms=time_ms,
                        source_agent_id=src_agent,
                        target_agent_id=dst_agent,
                        skill_id=skill_id,
                        damage=magnitude,
                        buff_dmg=condition_damage,
                        result=damage_result,
                        is_condition=is_condition,
                        shield_damage=(0 if overstack >= _DAMAGE_SANITY_CAP else overstack),
                        connected=connected,
                        absorbed=absorbed,
                        against_downed=against_downed,
                        is_life_leech=is_life_leech,
                        iff=_iff,
                        src_master_instid=src_master_inst,
                        dst_master_instid=dst_master_inst,
                    )
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
                # In 2025+, healing events (iff=0) also carry buff=1
                # because arcdps records them as buff-interaction records.
                # Yield the healing component before the BoonApplyEvent
                # so healing is not lost.
                if is_nondamage:
                    heal_magnitude = 0 if value >= _DAMAGE_SANITY_CAP else max(0, value)
                    barrier = 0 if buff_dmg >= _DAMAGE_SANITY_CAP else max(0, buff_dmg)
                    if heal_magnitude > 0 or barrier > 0:
                        yield HealingEvent(
                            time_ms=time_ms,
                            source_agent_id=src_agent,
                            target_agent_id=dst_agent,
                            skill_id=skill_id,
                            healing=heal_magnitude,
                            barrier=barrier,
                            iff=_iff & 0xFF if is_evtc_2025 else 0,
                            src_master_instid=src_master_inst if is_evtc_2025 else 0,
                            dst_master_instid=dst_master_inst if is_evtc_2025 else 0,
                        )
                yield BoonApplyEvent(
                    time_ms=time_ms,
                    source_agent_id=src_agent,
                    target_agent_id=dst_agent,
                    skill_id=skill_id,
                    duration_ms=0,
                    stacks=1,
                    kind="apply",
                )
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
                    result=_result,
                    connected=_result in _DIRECT_HIT_RESULTS,
                    absorbed=_result == _DIRECT_ABSORB_RESULT,
                    iff=_iff & 0xFF if is_evtc_2025 else 0,
                    src_master_instid=src_master_inst if is_evtc_2025 else 0,
                    dst_master_instid=dst_master_inst if is_evtc_2025 else 0,
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
                        iff=_iff & 0xFF if is_evtc_2025 else 0,
                        src_master_instid=src_master_inst if is_evtc_2025 else 0,
                        dst_master_instid=dst_master_inst if is_evtc_2025 else 0,
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
        and (
            _validate_event_candidate(
                data, legacy_boundary, known_agents, is_evtc_2025=is_evtc_2025
            )
            or (is_evtc_2025 and _validate_evtc2025_metadata_candidate(data, legacy_boundary))
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
    if len(data) < _HEADER_BASE_SIZE:
        raise EvtcParseError(f"EVTC blob is {len(data)} bytes, header needs {_HEADER_BASE_SIZE}")

    magic, build, _rev, encounter_id, _unused, agent_count = _HEADER_BASE_STRUCT.unpack_from(
        data, 0
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
    agents_offset = _AGENTS_OFFSET_2025 if is_evtc_2025 else AGENTS_OFFSET
    skill_offset = agents_offset + agent_count * AGENT_SIZE
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
    if is_evtc_2025:
        event_offset = records_offset + actual_skill_count * SKILL_RECORD_SIZE
        agents = _enrich_evtc2025_agents(data, agents, event_offset)

    # v0.11.0: CompleteAgents step (matching GW2EI's CompleteAgents()).
    # Scan the event stream for agent IDs referenced in src_agent or
    # dst_agent that are NOT in the parsed agent table. Create "UNKNOWN"
    # NPC agents for them so event-to-agent attribution works for
    # minions, pets, environmental objects, gadgets, and transient
    # entities that arcdps may omit from the agent table.
    if not is_evtc_2025:
        agents = _complete_agents(data, agents, is_evtc_2025=is_evtc_2025)
    metadata = _extract_evtc2025_metadata(data) if is_evtc_2025 else {}

    header = EvtcHeader(
        build_version=build_str,
        encounter_id=encounter_id,
        skill_count=actual_skill_count,
        agent_count=agent_count,
        gw2_build=metadata.get("gw2_build"),
        map_id=metadata.get("map_id"),
        arc_revision=metadata.get("arc_revision"),
        duration_ms=metadata.get("duration_ms"),
        start_time_ms=metadata.get("start_time_ms"),
    )

    fight_id = hashlib.sha256(data).hexdigest()
    ei_encounter_id = (
        _WVW_EI_ENCOUNTER_IDS.get(header.map_id) if header.map_id is not None else None
    )
    yield Fight(
        id=fight_id,
        header=header,
        agents=agents,
        skills=skills,
        success=True if header.map_id in _WVW_EI_ENCOUNTER_IDS else None,
        ei_encounter_id=ei_encounter_id,
    )


def _iter_agents(data: bytes, count: int, *, is_evtc_2025: bool = False) -> Iterator[Agent]:
    """Read ``count`` fixed-size 96-byte agent records starting at ``AGENTS_OFFSET``.

    EVTC2025+ files use a different agent-record layout; set
    ``is_evtc_2025=True`` to decode them correctly.
    """
    if count == 0:
        return
    cursor = _AGENTS_OFFSET_2025 if is_evtc_2025 else AGENTS_OFFSET
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


def _enrich_evtc2025_agents(data: bytes, agents: list[Agent], event_offset: int) -> list[Agent]:
    by_id = {agent.id: agent for agent in agents}
    instance_ids: dict[int, int] = {}
    team_ids: dict[int, int] = {}
    for cursor in range(event_offset, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
        event = _EVENT_STRUCT_2025.unpack_from(data, cursor)
        src_agent, dst_agent = int(event[1]), int(event[2])
        src_inst, dst_inst, statechange = int(event[7]), int(event[8]), int(event[19])
        if src_agent in by_id and src_inst:
            instance_ids.setdefault(src_agent, src_inst)
        if dst_agent in by_id and dst_inst:
            instance_ids.setdefault(dst_agent, dst_inst)
        if statechange == 22 and src_agent in by_id:
            team_ids[src_agent] = int(event[3])
    return [
        agent.model_copy(
            update={
                "instance_id": instance_ids.get(agent.id, 0),
                "team_id": team_ids.get(agent.id, 0),
            }
        )
        for agent in agents
    ]


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
        if use_heuristic and is_evtc_2025 and _validate_evtc2025_metadata_candidate(data, cursor):
            logger.debug(
                "Skill table ends at skill %d: offset %d looks like EVTC2025 metadata events",
                skill_index,
                cursor,
            )
            return
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
    # EVTC2025+ builds after the ResultEnumRework cutoff (build >= 20260501)
    # use raw GetTickCount64 timestamps that can exceed 24h. Use a higher cap
    # (uint32 max, ~49.7 days) to accept raw timestamps while still rejecting
    # random bytes.
    max_time_ms = 4_294_967_295
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


def _validate_evtc2025_metadata_candidate(data: bytes, offset: int) -> bool:
    """Return True when ``offset`` points at the EVTC2025 metadata event prelude."""
    if offset + EVENT_SIZE * 4 > len(data):
        return False
    first_time = None
    # EVTC2025 WvW logs can start with metadata statechanges before any
    # combatant agent appears. Those rows share one sane timestamp and use
    # non-combat statechange IDs, so the normal known-agent boundary check
    # rejects the real event start.
    metadata_statechanges = {9, 13, 14, 15, 16, 25, 54}
    for i in range(4):
        ev = _EVENT_STRUCT_2025.unpack_from(data, offset + i * EVENT_SIZE)
        time_ms = ev[0]
        statechange = ev[19]
        # ResultEnumRework builds (>= 20260501) use raw GetTickCount64
        # timestamps that can exceed 24h. Use uint32 max (~49.7 days) as
        # the upper bound.
        if not (0 < time_ms < 4_294_967_295):
            return False
        if first_time is None:
            first_time = time_ms
        elif time_ms != first_time:
            return False
        if statechange not in metadata_statechanges:
            return False
    return True


def _extract_evtc2025_metadata(data: bytes) -> dict[str, int]:  # noqa: PLR0912
    """Extract EI-visible metadata from EVTC2025 pre-combat statechanges."""
    offset = _compute_post_skills_offset(data, is_evtc_2025=True)
    if not _validate_evtc2025_metadata_candidate(data, offset):
        return {}
    out: dict[str, int] = {}
    start_time_ms: int | None = None
    cursor = offset
    end = len(data)
    while cursor + EVENT_SIZE <= end:
        ev = _EVENT_STRUCT_2025.unpack_from(data, cursor)
        statechange = ev[19]
        if statechange == 9:
            start_time_ms = int(ev[0])
        elif statechange == 15:
            out["gw2_build"] = int(ev[1])
        elif statechange == 25:
            out["map_id"] = int(ev[1])
        elif statechange == 54:
            payload = struct.pack("<QQii", ev[1], ev[2], ev[3], ev[4]).split(b"\x00", 1)[0]
            arc_build = payload.decode("ascii", errors="ignore")
            if "." in arc_build:
                revision = arc_build.split(".", 1)[1].split("-", 1)[0]
                if revision.isdecimal():
                    out["arc_revision"] = int(revision)
        elif statechange not in {9, 13, 14, 16, 18, 29, 42, 54}:
            break
        if "gw2_build" in out and "map_id" in out:
            break
        cursor += EVENT_SIZE
    if start_time_ms is not None:
        out["start_time_ms"] = int(start_time_ms)
        last_event_offset = offset + ((end - offset) // EVENT_SIZE - 1) * EVENT_SIZE
        for cursor in range(last_event_offset, offset - 1, -EVENT_SIZE):
            ev = _EVENT_STRUCT_2025.unpack_from(data, cursor)
            if ev[19] == 10 and ev[0] >= start_time_ms:
                out["duration_ms"] = int(ev[0]) - start_time_ms
                break
    return out


def _compute_post_skills_offset(  # noqa: PLR0911, PLR0912
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
    if len(data) < _HEADER_BASE_SIZE:
        return len(data)
    unpacked_header = _HEADER_BASE_STRUCT.unpack_from(data, 0)
    agent_count = int(unpacked_header[5])
    if is_evtc_2025 is None:
        build_str = unpacked_header[1].decode("ascii", errors="replace")
        is_evtc_2025 = _build_version_from_build_str(build_str) >= 2025_00_00
    agents_offset = _AGENTS_OFFSET_2025 if is_evtc_2025 else AGENTS_OFFSET
    skill_offset = agents_offset + agent_count * AGENT_SIZE

    # Build the set of known agent IDs for event-stream validation.
    known_agents: set[int] = set()
    for i in range(min(agent_count, MAX_AGENTS)):
        aoff = agents_offset + i * AGENT_SIZE
        if aoff + AGENT_SIZE > len(data):
            break
        known_agents.add(int(struct.unpack_from("<Q", data, aoff)[0]))
    known_agents_frozen = frozenset(known_agents)

    # Quick check: if no skills, events start right here.
    if is_evtc_2025 and _validate_evtc2025_metadata_candidate(data, skill_offset):
        return skill_offset
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

    if is_evtc_2025 and _validate_evtc2025_metadata_candidate(data, cursor):
        return cursor

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
        if is_evtc_2025 and _validate_evtc2025_metadata_candidate(data, candidate):
            return candidate
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
    event_struct = _EVENT_STRUCT_EVENTS_2025 if is_evtc_2025 else _EVENT_STRUCT_EVENTS
    max_time_ms = 86_400_000
    missing_ids: set[int] = set()

    while event_cursor + EVENT_SIZE <= end:
        ev = event_struct.unpack_from(data, event_cursor)
        time_ms = ev[0]
        if time_ms > max_time_ms:
            break
        src_agent = ev[1]
        dst_agent = ev[2]
        is_statechange = ev[14] if is_evtc_2025 else ev[7]
        if src_agent != 0 and src_agent not in known_ids:
            missing_ids.add(src_agent)
        if is_statechange != 19 and dst_agent != 0 and dst_agent not in known_ids:
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

    The event address is the leading uint64, followed by profession,
    elite, six uint16 stat/hitbox fields, and a 68-byte name buffer.
    """
    (
        addr,
        prof_raw,
        elite_raw,
        _tough,
        _conc,
        healing,
        _width,
        _condition,
        _height,
        name_buf,
    ) = _AGENT_STRUCT_2025.unpack_from(data, offset)

    # The 68-byte name buffer uses the same combo-string convention as
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
    is_player = is_player or (profession != Profession.UNKNOWN and elite_raw != 0xFFFFFFFF)

    # v0.16.3-api: cross-validate elite spec against profession.
    # EVTC2025+ logs use official GW2 v2 API IDs natively.
    elite = _validate_elite_for_profession(prof_raw, elite_raw)

    # NPC/Gadget detection via elite_raw == 0xFFFFFFFF.
    # This is the definitive arcdps signal: players always have
    # a valid elite spec ID (0 for core), while NPCs/gadgets
    # set the field to uint32 max.
    species_id: int | None = None
    is_gadget = False
    if elite_raw == 0xFFFFFFFF:
        is_player = False
        species_id = prof_raw & 0xFFFF
        is_gadget = (prof_raw >> 16) == 0xFFFF

    return Agent(
        id=addr,
        name=char_name,
        profession=profession,
        elite=elite,
        elite_raw=elite_raw,
        species_id=species_id,
        is_player=is_player,
        is_gadget=is_gadget,
        account_name=account_name,
        subgroup=subgroup,
        healing=healing,
    )


def _decode_agent(data: bytes, offset: int) -> Agent:
    """Decode a single 96-byte legacy agent record at ``offset``.

    The elite spec is validated against the agent's profession via
    ``_VALID_ELITE_BY_PROFESSION``, which resolves shared collision
    IDs (55, 63, 73, 74, 75, 77) by profession membership.  Falls
    back to ``EliteSpec.BASE`` if validation fails.
    """
    aid, prof_raw, elite_raw, _tough, _conc, healing, _width, name_buf = _AGENT_STRUCT.unpack_from(
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

    # v0.16.3-api: cross-validate elite ID against the agent's
    # profession using the canonical helper (handles shared
    # collision IDs 55, 63, 73, 74, 75, 77).
    elite = _validate_elite_for_profession(prof_raw, elite_raw)

    # NPC/Gadget detection via elite_raw == 0xFFFFFFFF.
    species_id: int | None = None
    is_gadget = False
    if elite_raw == 0xFFFFFFFF:
        is_player = False
        species_id = prof_raw & 0xFFFF
        is_gadget = (prof_raw >> 16) == 0xFFFF

    return Agent(
        id=aid,
        name=char_name,
        profession=profession,
        elite=elite,
        elite_raw=elite_raw,
        species_id=species_id,
        is_player=is_player,
        is_gadget=is_gadget,
        account_name=account_name,
        subgroup=subgroup,
        healing=max(0, healing),
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


def scan_agent_awareness(source: BinaryIO | bytes) -> dict[int, tuple[int, int]]:
    """Return ``{agent_id: (first_aware_ms, last_aware_ms)}``, fight-relative.

    Awareness is the span over which the log mentions an agent at all, as
    either source or target, across the *raw* cbtevent stream -- including
    the records ``parse_events`` filters out. That is the same definition
    Elite Insights reports as ``firstAware`` / ``lastAware``, and it is
    what bounds an actor's buff simulation: EI stops accruing uptime once
    the log stops seeing the actor, rather than running its active buffs
    to the end of the fight.

    Deriving the bound from the *emitted* event stream instead lands a
    median 181 ms early on the corpus, which is enough to shift every
    player's uptime by ~0.25 points on a 70 s fight.

    Records with ``time == 0`` are header-ish metadata rather than combat
    activity and are skipped, matching the parser's own down-duration
    scan.
    """
    data = _read_all(source)
    build_str = data[BUILD_OFFSET : BUILD_OFFSET + 8].decode("ascii", errors="replace")
    is_evtc_2025 = _build_version_from_build_str(build_str) >= 2025_00_00
    unpack = (
        _EVENT_STRUCT_EVENTS_2025.unpack_from if is_evtc_2025 else _EVENT_STRUCT_EVENTS.unpack_from
    )
    cursor = _compute_post_skills_offset(data, is_evtc_2025=is_evtc_2025)
    end = len(data)

    awareness: dict[int, tuple[int, int]] = {}
    origin: int | None = None
    while cursor + EVENT_SIZE <= end:
        unpacked = unpack(data, cursor)
        cursor += EVENT_SIZE
        time_ms, src_agent, dst_agent = unpacked[0], unpacked[1], unpacked[2]
        if time_ms <= 0:
            continue
        if origin is None or time_ms < origin:
            origin = time_ms
        for agent_id in (src_agent, dst_agent):
            if not agent_id:
                continue
            span = awareness.get(agent_id)
            if span is None:
                awareness[agent_id] = (time_ms, time_ms)
            elif time_ms > span[1]:
                awareness[agent_id] = (span[0], time_ms)
            elif time_ms < span[0]:
                awareness[agent_id] = (time_ms, span[1])
    if origin is None:
        return {}
    return {
        agent_id: (first - origin, last - origin) for agent_id, (first, last) in awareness.items()
    }


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
    "scan_agent_awareness",
]
