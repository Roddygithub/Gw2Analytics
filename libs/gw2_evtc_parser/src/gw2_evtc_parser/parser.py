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
import struct
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Final

from gw2_core import (
    Agent,
    BoonApplyEvent,
    BuffApplyEvent,
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
from gw2_evtc_parser.statechange_dispatch import dispatch_statechange

# Module-level logger for soft warnings (e.g. unrecognised arcdps
# account_name format). Library consumers control verbosity via the
# standard ``logging`` configuration; we do not call ``basicConfig``.
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Binary layout constants
# ---------------------------------------------------------------------------

#: Total size of the EVTC file header in bytes for rev>=1 (extended).
#: Layout (per ``arcdps.h`` ``evtc_header``): magic(4) + build(8) +
#: rev(1) + combat_id(2) + unused(1) + agent_count(4) + skill_count(4)
#: + lang(1) = 25 bytes.  For rev>=1 the 25-byte layout also holds
#: ``map_id`` at bytes 24-27 as a 4-byte extension, making the header
#: 28 bytes total when present.
HEADER_SIZE: Final[int] = 25

#: ``struct`` format for the 25-byte file header (rev>=1 extended).
#: Fields: magic(4s) + build(8s) + rev(B) + combat_id(H) + unused(B)
#: + agent_count(I) + skill_count(I) + lang(B).
_HEADER_STRUCT: Final[struct.Struct] = struct.Struct("<4s8sBHBI IB")

#: Byte offset of the agent_count field inside the header.
AGENT_COUNT_OFFSET: Final[int] = 16

#: Byte offset of the build date field inside the header.
BUILD_OFFSET: Final[int] = 4

#: Byte offset of the skill_count field inside the header (bytes 20-23).
SKILL_COUNT_OFFSET: Final[int] = 20

#: Byte offset where agent records start (right after the 25-byte
#: header). For rev>=1 agents begin immediately after the header.
AGENTS_OFFSET: Final[int] = HEADER_SIZE

#: Total size of one agent record on disk (the C ``struct ag`` size).
AGENT_SIZE: Final[int] = 96

#: Size of the 24-byte fixed prefix that starts every agent record.
AGENT_PREFIX_SIZE: Final[int] = 24

#: Size of the 72-byte name buffer that ends every agent record.
AGENT_NAME_SIZE: Final[int] = AGENT_SIZE - AGENT_PREFIX_SIZE

#: ``struct`` format for the entire 96-byte agent record.
#: Layout (little-endian): id(Q) + prof(I) + elite(I) + four uint16s +
#: 72-byte name buffer.
_AGENT_STRUCT: Final[struct.Struct] = struct.Struct(f"<QIIhhhh{AGENT_NAME_SIZE}s")

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
_EVENT_STRUCT_EVENTS: Final[struct.Struct] = struct.Struct(
    "<QQQii 4x I 7x bbb 2x b 11x"
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
        # Local binding shaves attribute-lookup overhead in the
        # tight event-unpack loop.
        _unpack_event = _EVENT_STRUCT_EVENTS.unpack_from
        # Hoist the REMOVE-kind tuple to a local variable so the
        # hot loop pays local-variable lookup cost instead of
        # global lookup cost.
        _cbtbufremove_kinds = _CBTBUFREMOVE_KINDS
        while cursor + EVENT_SIZE <= end:
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
                # WAVE-8 v0.11.0 Blocker A.4.1 (see
                # ``plans/WAVE-8-parser-side.md`` §A.4.1): the upstream
                # filter ``if is_statechange != 0: continue`` is REPLACED
                # with a dispatch call to
                # :func:`statechange_dispatch.dispatch_statechange`.
                # The dispatch table maps the arcdps ``is_statechange``
                # byte (per :file:`docs/statechange-ids.md`) to a
                # Pydantic event constructor -- currently StunBreak
                # (byte 56) + Barrier (byte 38). Unmapped kinds return
                # ``None`` so the filter continues to suppress them at
                # the byte boundary (backward compat preserved).
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
            elif _ev_buff != 0:
                # Phase 9 Step 3 APPLY-BRANCH (SHIPPED 2026-07-11).
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

    magic, build, _rev, encounter_id, _unused, agent_count, skill_count_hdr, _lang = (
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

    agents = list(_iter_agents(data, agent_count))

    # Walk the skill table.  arcdps does not reliably store skill_count
    # in the header for rev>=1; we pass a generous upper bound and let
    # _iter_skill_records stop early via its safety checks.
    skill_offset = AGENTS_OFFSET + agent_count * AGENT_SIZE
    skills = list(_iter_skills(data, skill_offset, MAX_SKILLS))
    actual_skill_count = len(skills)

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


def _iter_agents(data: bytes, count: int) -> Iterator[Agent]:
    """Read ``count`` fixed-size 96-byte agent records starting at ``AGENTS_OFFSET``."""
    if count == 0:
        return
    cursor = AGENTS_OFFSET
    end = len(data)
    for _ in range(count):
        if cursor + AGENT_SIZE > end:
            raise EvtcParseError(
                f"Truncated agent record at offset {cursor}: "
                f"need {AGENT_SIZE} bytes, only {end - cursor} available",
            )
        yield _decode_agent(data, cursor)
        cursor += AGENT_SIZE


def _iter_skill_records(
    data: bytes,
    offset: int,
    count: int,
) -> Iterator[tuple[int, int, int, int]]:
    """Yield ``(cursor, skill_id, name_len, record_size)`` for each valid skill record.

    Reads up to ``count`` variable-size skill records starting at
    ``offset``. Each record has a fixed 8-byte header (``skill_id`` u32 +
    ``name_len`` u32) followed by ``name_len`` bytes of UTF-8 name. arcdps
    writes a trailing null byte after the name, which is included in the
    byte stream but not counted in ``name_len``; the next record starts
    immediately after the null terminator
    (``offset += 8 + name_len + 1``).

    The generator is **lenient**: if the cursor runs past the end of the
    data, or if a record's ``name_len`` exceeds the safety bound (which
    happens when ``header.skill_count`` is larger than the actual number
    of skill records — a known arcdps quirk), the parser stops early and
    emits a warning. The yielded count may therefore be less than
    ``count``. This is preferable to raising, because the alternative
    (reading into the event stream) produces garbage records that pollute
    downstream analytics.
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
        yield cursor, skill_id, name_len, record_size
        cursor += record_size


def _iter_skills(data: bytes, offset: int, count: int) -> Iterator[Skill]:
    """Read up to ``count`` variable-size skill records starting at ``offset``.

    Thin wrapper around :func:`_iter_skill_records` that decodes the
    UTF-8 skill name and yields :class:`Skill` instances.
    """
    for cursor, skill_id, name_len, _record_size in _iter_skill_records(data, offset, count):
        name_bytes = data[
            cursor + _SKILL_HEADER_STRUCT.size : cursor + _SKILL_HEADER_STRUCT.size + name_len
        ]
        name = name_bytes.decode("utf-8", errors="replace")
        yield Skill(id=skill_id, name=name)


def _validate_event_candidate(data: bytes, offset: int) -> bool:
    """Return ``True`` if ``offset`` likely points into the event stream.

    Reads up to 2 consecutive 64-byte event records and requires:
    * Each has ``time_ms < 86_400_000`` (24 hours).
    * At least one has a non-zero ``src_agent`` or ``dst_agent``
      (eliminates pure-zero-byte false positives).
    """
    max_time_ms = 86_400_000
    saw_agent = False
    for i in range(2):
        ev_offset = offset + i * EVENT_SIZE
        if ev_offset + EVENT_SIZE > len(data):
            break
        ev = _EVENT_STRUCT.unpack_from(data, ev_offset)
        if ev[0] > max_time_ms:
            return False
        if ev[1] or ev[2]:
            saw_agent = True
    return saw_agent


def _compute_post_skills_offset(data: bytes) -> int:
    """Return the byte offset where the event stream starts.

    Strategy:

    1. Read ``skill_count`` from the 25-byte header (bytes 20-23).
       If 0, return ``skill_offset`` immediately (common zero-skills
       case).  If 1..MAX_SKILLS, walk exactly that many records with
       :func:`_iter_skill_records` (no overshoot).  If larger than
       MAX_SKILLS, fall back to the :data:`MAX_SKILLS` walker.

    2. If the walker cursor does not look like a valid event start
       (passes :func:`_validate_event_candidate`), run a backward scan
       from cursor-1 to ``skill_offset``, then a forward scan up to
       ``EVENT_SIZE`` bytes past ``cursor``.

    The header ``skill_count`` is the authoritative source for
    synthetic blobs created by test builders.  Real arcdps rev>=1
    logs store ``map_id`` at bytes 20-23 (read as a large
    ``skill_count``), so they fall through to the MAX_SKILLS walker
    which handles them correctly via safety bounds.
    """
    if len(data) < HEADER_SIZE:
        return len(data)
    unpacked_header = _HEADER_STRUCT.unpack_from(data, 0)
    agent_count = int(unpacked_header[5])
    skill_count_hdr = int(unpacked_header[6])
    skill_offset = AGENTS_OFFSET + agent_count * AGENT_SIZE

    # Pass 1: quick check (most synthetic files have 0 skills)
    if skill_count_hdr == 0 and _validate_event_candidate(data, skill_offset):
        return skill_offset

    # Pass 2: walk the skill table
    count = min(skill_count_hdr, MAX_SKILLS) if skill_count_hdr > 0 else MAX_SKILLS
    cursor = skill_offset
    for record_start, _skill_id, _name_len, record_size in _iter_skill_records(
        data, skill_offset, count
    ):
        cursor = record_start + record_size

    if _validate_event_candidate(data, cursor):
        return cursor

    # Pass 3: backward scan (cursor-1 down to skill_offset).
    for candidate in range(cursor - 1, skill_offset - 1, -1):
        if _validate_event_candidate(data, candidate):
            return candidate

    # Pass 4: forward scan (byte-by-byte, up to EVENT_SIZE bytes)
    max_scan = min(cursor + EVENT_SIZE, len(data))
    for candidate in range(cursor + 1, max_scan):
        if _validate_event_candidate(data, candidate):
            return candidate

    return cursor


def _decode_agent(data: bytes, offset: int) -> Agent:
    """Decode a single 96-byte agent record at ``offset``."""
    aid, prof_raw, elite_raw, _tough, _conc, _heal, _width, name_buf = (
        _AGENT_STRUCT.unpack_from(data, offset)
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
