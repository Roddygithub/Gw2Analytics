"""v0.10.11 Phase 9 step 2-EMIT-BRANCH predicate tests.

The parser's :meth:`PythonEvtcParser.parse_events` yields
:class:`~gw2_core.BoonApplyEvent` records from cbtevent records whose
``is_buffremove`` byte carries a REMOVE-class signal. The predicate is
``is_buffremove in (1, 2, 3)`` -- the arcdps REMOVE range -- which
deliberately EXCLUDES the CBTB_NONE sentinel (0). The 0 case at the
non-statechange path is a pure-damage / pure-heal record (arcdps
APPLY events go through the ``is_statechange != 0`` path, which the
parser's upstream filter ``if is_statechange != 0: continue`` skips
before the REMOVE predicate fires).

These tests lock the predicate boundary so a future regression that
widens the predicate back to ``[0..3]`` (causing phantom zero-duration
applies to leak into the BoonApplyEvent stream from every damage /
heal record) fires at the unit-test boundary BEFORE the stream
pollution propagates to downstream ``buff_uptime`` aggregators.

Test file split rationale: the byte-alignment tests in
:file:`test_parser_byte_alignment.py` exercise the struct field
extraction (:func:`_unpack_cbtevent`); this file exercises the
predicate + downstream event-yield contract via
:meth:`PythonEvtcParser.parse_events`. The two end-to-end dimensions
are independent -- the byte-alignment suite catches struct
regressions (a future struct reorder); this suite catches predicate
regressions (a future predicate widening/narrowing).

Hermetic-fixture rationale: the build helpers
(:func:`_build_event_record` + :func:`_build_minimal_evtc`) are
duplicated from :file:`test_parser.py` to keep this test file
self-contained -- pytest's collection path (without a ``__init__.py``
in the ``tests/`` directory) cannot resolve cross-test imports like
``from gw2_evtc_parser.tests.test_parser import ...``. The
duplication cost (~50 lines) is cheaper than introducing a package
init OR a shared conftest.py for two consumers.
"""

from __future__ import annotations

import struct
from typing import Final

import pytest

from gw2_core import BoonApplyEvent, BuffRemovalEvent, DamageEvent, HealingEvent
from gw2_evtc_parser import PythonEvtcParser
from gw2_evtc_parser.parser import _EVENT_STRUCT

# ---------------------------------------------------------------------------
# Local copies of build-event fixtures (extended with ``is_buffremove``)
# ---------------------------------------------------------------------------

#: Reused struct format -- mirrors the parser's ``_EVENT_STRUCT`` literal 1:1.
_CBTEVENT_FMT: Final[struct.Struct] = struct.Struct("<QQQiiIIHHHbbbbbbbbIIbb")
_AGENT_NAME_SIZE: Final[int] = 68


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
    is_buffremove: int = 0,
    ev_buff: int = 0,
) -> bytes:
    """Build one 64-byte cbtevent record matching the arcdps ``cbtevent`` struct.

    Extended from the test_parser.py version with ``is_buffremove`` + ``ev_buff``
    keyword parameters so the Phase 9 emit tests can drive both
    REMOVE-class + APPLY-class predicate boundaries without hand-packing
    64-byte fixtures.

    Pack order MUST mirror the parser's unpack order 1:1:
    :data:`_CBTEVENT_FMT` = ``<QQQiiIIHHHbbbbbbbbIIbb`` where the
    8 ``b`` slots (offsets 46-53) unpack as:
    is_cleanup(byte 46), is_nondamage(byte 47), is_statechange(byte 48),
    ev.buff(byte 49 -- arcdps buff ID, F1-validated), result(byte 50),
    is_activation(byte 51), is_buffremove(byte 52 -- arcdps
    cbtbuffremove enum), is_ninety(byte 53).

    The ``is_buffremove`` parameter is written into byte 52 (struct
    member 16), NOT byte 53 -- getting these swapped is an off-by-one
    silent regression. The ``ev_buff`` parameter is written into
    byte 49 (struct member 13), NOT byte 50 -- same caveat. The
    parser-side variable names are ``is_buffremove`` (the 0=NONE/
    1=ALL/2=SINGLE/3=MANUAL enum discriminator) and ``_ev_buff``
    (the buff ID for buff-interaction records).
    """
    return _CBTEVENT_FMT.pack(
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
        is_cleanup,        # byte 46 = is_cleanup
        is_nondamage,      # byte 47 = is_nondamage
        is_statechange,    # byte 48 = is_statechange
        ev_buff,           # byte 49 = ev.buff (arcdps buff ID)
        0,                 # byte 50 = result (was is_shields)
        is_offcycle,       # byte 51 = is_activation (was is_offcycle)
        is_buffremove,     # byte 52 = is_buffremove (arcdps cbtbuffremove)
        0,                 # byte 53 = is_ninety
        0,                 # pad63 (u32 slot 1, offsets 54-57)
        0,                 # pad64 (u32 slot 2, offsets 58-61)
        0,                 # pad65 (byte 62)
        0,                 # pad66 (byte 63)
    )


def _build_minimal_evtc(
    agents: list[tuple[int, int, int, str, bool]],
    *,
    build: str = "20250925",
    encounter_id: int = 0,
    skills: list[tuple[int, str]] | None = None,
    events: list[bytes] | None = None,
) -> bytes:
    """Build a synthetic EVTC binary with the given agents, skills, and events.

    Mirrors the helper in :file:`test_parser.py` -- duplicated here
    so this test file stays self-contained (no cross-test imports).
    The agent-record 68-byte name buffer is filled entirely with
    nulls; this test file does NOT exercise the player / NPC split
    (the emit-predicate boundary tests don't depend on agent
    decode). The fixture builder still produces structurally-valid
    96-byte agent records so the parser can locate the event block.
    """
    if len(build) != 8:
        msg = f"build must be exactly 8 ASCII chars (yyyymmdd), got {len(build)}"
        raise ValueError(msg)
    if skills is None:
        skills = []
    if events is None:
        events = []
    header = struct.pack(
        "<4s8sBHBI IB",
        b"EVTC",
        build.encode("ascii"),
        0,
        encounter_id,
        0,
        len(agents),
        len(skills),
        0,  # language
    )
    prefix_fmt = struct.Struct("<QIIhhhhhh")
    name_buf = b"\x00" * _AGENT_NAME_SIZE
    body = bytearray()
    for aid, prof, elite, _name, _is_player in agents:
        # 28-byte prefix + 68-byte all-null name buffer = 96 bytes
        # (struct ag size) per agent record.
        body += prefix_fmt.pack(aid, prof, elite, 0, 0, 0, 0, 0, 0) + name_buf
    for skill_id, skill_name in skills:
        name_bytes = skill_name.encode("utf-8")
        skill_header = struct.pack("<II", skill_id, len(name_bytes))
        body += skill_header + name_bytes + b"\x00"
    for ev in events:
        if len(ev) != 64:  # EVENT_SIZE
            msg = f"each event record must be exactly 64 bytes, got {len(ev)}"
            raise ValueError(msg)
        body += ev
    return header + bytes(body)


# ---------------------------------------------------------------------------
# Predicate boundary tests
# ---------------------------------------------------------------------------


def test_parse_events_emit_buff_skipped_for_is_buffremove_zero() -> None:
    """Default-fixture cbtevent with ``is_buffremove == 0`` does NOT yield BoonApplyEvent.

    The default ``_build_event_record`` helper packs ``is_buffremove = 0``
    (the helper's keyword default mirrors test_parser.py's fixture).
    Under the predicate ``is_buffremove in (1, 2, 3)`` this 0-byte
    cbtevent yields ZERO ``BoonApplyEvent`` records -- the existing
    damage / heal emission is unaffected. A future predicate widening
    back to ``[0..3]`` would leak one phantom zero-duration
    ``kind="apply"`` per damage record into the BoonApplyEvent
    stream; this test fires at the unit-test boundary before that
    pollution reaches ``buff_uptime``.
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(101, "Skill")],
        events=[_build_event_record(time_ms=1_000, src_agent=1, dst_agent=2, value=100)],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Predicate in [1..3] -> no BoonApplyEvent. Same yield as
    # pre-Phase-9 (1 DamageEvent).
    assert len(events) == 1
    assert all(not isinstance(e, BoonApplyEvent) for e in events)
    assert isinstance(events[0], DamageEvent)


def test_parse_events_emit_buff_remove_all_yields_boon_apply_event() -> None:
    """``is_buffremove == 1`` (CBTB_ALL) yields ONE BoonApplyEvent with kind="remove_all".

    The extended ``_build_event_record`` helper drives ``is_buffremove=1``
    via its keyword parameter. The result should be 1 BoonApplyEvent
    (the REMOVE_ALL marker) + 1 DamageEvent (the ``value > 0``
    non-statechange record). Total yield: 2 events.

    Dual-emission rationale: Phase 9 tracks buff lifecycle markers
    via BoonApplyEvent; the magnitude of the strip is the
    BuffRemovalEvent (which fires when ``buff_dmg > 0`` -- zero here).
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(42, "Skill")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=100,
                is_buffremove=1,  # CBTB_ALL
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Predicate: BoonApplyEvent REMOVE_ALL fires (kind="remove_all");
    # DamageEvent fires (value > 0, is_nondamage == 0).
    # BuffRemovalEvent does NOT fire (buff_dmg == 0).
    assert len(events) == 2
    boon, damage = events
    assert isinstance(boon, BoonApplyEvent)
    assert boon.kind == "remove_all"
    assert boon.time_ms == 1_000
    assert boon.source_agent_id == 1
    assert boon.target_agent_id == 2
    assert boon.skill_id == 42
    assert boon.duration_ms == 0
    assert boon.stacks == 1
    assert isinstance(damage, DamageEvent)
    assert damage.damage == 100


def test_parse_events_emit_buff_remove_single_yields_three_events() -> None:
    """``is_buffremove == 2 + is_nondamage > 0 + buff_dmg > 0`` yields triple emission.

    The canonical cbtevent record for a corrupting / confusion skill:
    REMOVE-single signal at byte 52, heal magnitude in ``value``,
    strip magnitude in ``buff_dmg``. The parser yields THREE events:
    BoonApplyEvent (kind="remove_single") + HealingEvent +
    BuffRemovalEvent. The triple emission is the Phase 8 + Phase 9
    contract for same-record dual/triple emit.

    This locks the predicate + emission ordering so a future refactor
    that reorders the yields (e.g. BuffRemovalEvent before
    BoonApplyEvent) fires at the unit-test boundary.
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(101, "Mimic")],
        events=[
            _build_event_record(
                time_ms=42_500,
                src_agent=1,
                dst_agent=2,
                value=8_500,        # heal magnitude
                skill_id=101,       # FK to skills table = "Mimic"
                buff_dmg=2_250,     # strip magnitude
                is_nondamage=1,     # heal-class signal
                is_buffremove=2,    # CBTB_SINGLE
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Triple emission: boon-apply + heal + strip.
    assert len(events) == 3
    boon, heal, strip = events
    assert isinstance(boon, BoonApplyEvent)
    assert boon.kind == "remove_single"
    assert boon.time_ms == 42_500
    assert boon.skill_id == 101
    assert isinstance(heal, HealingEvent)
    assert heal.healing == 8_500
    assert isinstance(strip, BuffRemovalEvent)
    assert strip.buff_removal == 2_250


def test_parse_events_emit_buff_remove_manual_collapses_to_remove_single() -> None:
    """``is_buffremove == 3`` (CBTB_MANUAL) yields BoonApplyEvent with kind="remove_single".

    The 4th arcdps ``cbtbuffremove`` enum value (CBTB_MANUAL) collapses
    onto ``remove_single`` per arcdps's documented guidance: "use for
    in/out volume". The parser's inline mapping treats bytes 2 and 3
    identically -- both yield ``kind="remove_single"``. Locks the
    manual-collapse behaviour so a future refactor that distinguishes
    MANUAL from SINGLE fires at the unit-test boundary.
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(42, "Skill")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=100,
                is_buffremove=3,  # CBTB_MANUAL -> collapses to remove_single
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 2  # BoonApplyEvent + DamageEvent
    boon, _damage = events  # _damage intentionally unused
    assert isinstance(boon, BoonApplyEvent)
    assert boon.kind == "remove_single"  # CBTB_MANUAL collapses to SINGLE


@pytest.mark.parametrize("is_buffremove_value", [4, 5, 127, -128])
def test_parse_events_emit_buff_out_of_range_does_not_emit(is_buffremove_value: int) -> None:
    """``is_buffremove`` byte is out of the arcdps REMOVE range yields no BoonApplyEvent.

    The arcdps-spec ``cbtbuffremove`` enum is 4 values (0..3); values
    >= 4 (and < 0) are reserved for future arcdps use. The parser's
    predicate ``in (1, 2, 3)`` requires a known REMOVE range --
    out-of-range bytes do NOT yield ``BoonApplyEvent``. Locks the
    unknown-byte fallback so a future refactor that mistakenly yields
    an event for future-arcdps sentinel bytes (and corrupts
    ``buff_uptime`` aggregation) fires at the unit-test boundary
    BEFORE the stream pollution propagates.

    Bound bounds: ``-128`` is the signed-byte minimum (struct ``b``
    format range); ``=127`` is the signed-byte maximum. Both are
    outside the arcdps REMOVE range so the predicate rejects them.
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(42, "Skill")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=100,
                is_buffremove=is_buffremove_value,
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Predicate excludes out-of-range bytes; only the damage emission
    # fires (value > 0, is_nondamage == 0 -> 1 DamageEvent).
    assert len(events) == 1
    assert isinstance(events[0], DamageEvent)
    assert all(not isinstance(e, BoonApplyEvent) for e in events)


def test_parse_events_emit_buff_statechange_record_filters_upstream() -> None:
    """``is_statechange != 0`` records are filtered upstream (no BoonApplyEvent fires).

    Reinforces the boundary: even if a statechange record carries
    ``is_buffremove`` in [1..3], the upstream ``is_statechange != 0``
    filter skips the record BEFORE the REMOVE predicate fires. APPLY
    events are encoded in statechange records (not in the
    non-statechange cbtevent path) -- the parser does NOT emit
    BoonApplyEvent for them either (Phase 9 step 3+ will).

    Companion test: ``test_parse_events_emit_buff_apply_statechange_marker``
    covers the canonical CBTS_BUFFAPPLY statechange marker
    (``is_statechange=1, is_buffremove=0``) which is the dual of
    the REMOVE case here.
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(42, "Skill")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=100,
                is_statechange=1,  # filtered upstream
                is_buffremove=2,    # REMOVE_SINGLE
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Statechange record is filtered completely -- no damage event
    # AND no BoonApplyEvent.
    assert events == []


def test_parse_events_emit_buff_apply_statechange_marker() -> None:
    """``is_statechange=1, is_buffremove=0`` (CBTS_BUFFAPPLY) yields no events.

    Companion to ``test_parse_events_emit_buff_statechange_record_filters_upstream``
    -- locks the canonical buff-APPLY statechange marker. arcdps
    encodes APPLY events as ``CBTS_BUFFAPPLY`` statechange records
    (with ``is_statechange=1`` and ``is_buffremove=0`` as the
    discriminator triplet). The parser does NOT yet surface these
    records as ``BoonApplyEvent(kind="apply")`` -- Phase 9 step 3+
    will. Until then, the upstream ``is_statechange != 0`` filter
    skips these records entirely, yielding zero events.

    Locks the boundary so Phase 9 step 3+ can safely engage the
    upstream APPLY path without accidentally also aligning the
    non-statechange REMOVE predicate (the predicate
    ``is_buffremove in (1, 2, 3)`` already excludes byte 0 in the
    non-statechange path; the statechange path will be a SEPARATE
    APPLY branch on top of the existing filter).
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(42, "Skill")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=100,
                is_statechange=1,  # CBTS_BUFFAPPLY marker
                is_buffremove=0,    # arcdps cbtbuffremove = NONE for APPLY statechange
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Statechange record is filtered completely -- no events until
    # Phase 9 step 3+ ships the upstream statechange APPLY branch.
    assert events == []


def test_parse_events_emit_buff_remove_with_no_magnitude_still_emits_boon() -> None:
    """REMOVE record (buff_dmg=0, is_nondamage=0) yields BoonApply + Damage (no strip).

    Edge case the plan calls out: REMOVE-class records that have a
    heal/strip of zero are still REMOVE markers from arcdps
    (the ``is_buffremove`` byte is set regardless of magnitude) --
    Phase 9 emits the BoonApplyEvent marker to keep buff-uptime
    aggregation accurate. BuffRemovalEvent does NOT fire (zero
    magnitude strip is meaningless); DamageEvent fires (value > 0,
    is_nondamage == 0).
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(42, "Skill")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=2_500,    # direct damage
                buff_dmg=0,     # no strip
                is_nondamage=0,  # damage-class
                is_buffremove=2, # but REMOVE_SINGLE marker
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Predicate: BoonApplyEvent REMOVE_SINGLE fires; DamageEvent fires.
    # BuffRemovalEvent does NOT fire (buff_dmg == 0).
    assert len(events) == 2
    boon, damage = events
    assert isinstance(boon, BoonApplyEvent)
    assert boon.kind == "remove_single"
    assert isinstance(damage, DamageEvent)
    assert damage.damage == 2_500


# ---------------------------------------------------------------------------
# Phase 9 Step 3 APPLY-BRANCH tests
# ---------------------------------------------------------------------------


def test_parse_events_emit_apply_mid_combat_yields_boon_apply() -> None:
    """Mid-combat APPLY record (ev_buff != 0, is_buffremove == 0) yields BoonApply(kind="apply").

    Per F1 byte mapping + the buff_dispatch realignment (commit
    ``529cb90``), arcdps encodes buff APPLY events as NON-statechange
    records (``is_statechange == 0``) with a non-zero ``ev.buff``
    byte (the buff ID for the applied buff). Phase 9 Step 3 wires
    this channel into the parser's emit branch.
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(101, "Quickness")],
        events=[
            _build_event_record(
                time_ms=10_000,
                src_agent=1,
                dst_agent=2,
                value=0,           # APPLY has no damage magnitude
                skill_id=101,      # the buff being applied
                ev_buff=101,       # arcdps ev.buff = buff_id_being_applied
                # is_buffremove==0 + is_statechange==0 (defaults) trigger the APPLY branch
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Predicate fires: BoonApplyEvent(kind="apply") yielded.
    # No DamageEvent (value == 0). No BuffRemovalEvent (no buff_dmg).
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, BoonApplyEvent)
    assert e.kind == "apply"
    assert e.time_ms == 10_000
    assert e.source_agent_id == 1
    assert e.target_agent_id == 2
    assert e.skill_id == 101
    assert e.duration_ms == 0
    assert e.stacks == 1


def test_parse_events_emit_apply_with_damage_yields_dual_event() -> None:
    """APPLY record with damage co-emits BoonApply(kind="apply") + DamageEvent.

    A single arcdps cbtevent can carry BOTH a buff apply AND a
    damage magnitude (the canonical case is a damage skill that
    also applies a debuff via the same hit). The parser yields both
    events: BoonApplyEvent(kind="apply") for the buff lifecycle
    marker + DamageEvent for the magnitude.
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(42, "Torment")],
        events=[
            _build_event_record(
                time_ms=15_000,
                src_agent=1,
                dst_agent=2,
                value=850,         # damage magnitude
                skill_id=42,       # the buff being applied (Torment)
                ev_buff=42,        # arcdps ev.buff = Torment's buff_id
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Dual emission: BoonApply(apply) + DamageEvent.
    assert len(events) == 2
    boon, damage = events
    assert isinstance(boon, BoonApplyEvent)
    assert boon.kind == "apply"
    assert boon.skill_id == 42
    assert isinstance(damage, DamageEvent)
    assert damage.damage == 850
    assert damage.skill_id == 42


def test_parse_events_emit_apply_excludes_remove_class() -> None:
    """REMOVE-class record (``is_buffremove in (1..3)``) does NOT trigger the APPLY branch.

    Mutual exclusivity: the REMOVE branch (``is_buffremove in (1..3)``)
    handles REMOVE records; the APPLY branch (``elif _ev_buff != 0``)
    handles the rest. A record with ``is_buffremove=2`` AND
    ``ev_buff=42`` (a REMOVE_SINGLE event for buff 42) fires ONLY
    the REMOVE branch, NOT the APPLY branch. The ``elif`` makes the
    branches exclusive.
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(42, "Strip")],
        events=[
            _build_event_record(
                time_ms=20_000,
                src_agent=1,
                dst_agent=2,
                value=100,
                skill_id=42,
                buff_dmg=50,
                ev_buff=42,         # a REMOVE record's ev.buff is the stripped buff ID
                is_buffremove=2,    # REMOVE_SINGLE
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Expected: the REMOVE branch fires (BoonApply kind="remove_single")
    # and the Damage path fires (DamageEvent because value>0 and
    # is_nondamage defaults to 0). The APPLY branch is silent because
    # `is_buffremove == 2` makes the Step 3 `elif _ev_buff != 0`
    # predicate unreachable via short-circuit.
    assert len(events) == 2
    boon = events[0]
    damage = events[1]
    assert isinstance(boon, BoonApplyEvent)
    assert boon.kind == "remove_single"
    assert boon.kind != "apply"  # mutual exclusivity check
    assert isinstance(damage, DamageEvent)


def test_parse_events_emit_apply_zero_ev_buff_does_not_emit() -> None:
    """Default-fixture cbtevent (ev_buff == 0) does NOT yield BoonApply(kind="apply").

    Mirror of ``test_parse_events_emit_buff_skipped_for_is_buffremove_zero``
    but for the APPLY branch. The default ``_build_event_record``
    helper packs ``ev_buff = 0`` (the helper's keyword default).
    Records with both ``ev_buff == 0`` AND ``is_buffremove == 0``
    are pure damage / pure heal records (no buff-interaction
    context) -- no BoonApply event fires.
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(42, "Whirlwind")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=100,
                # ev_buff defaults to 0; no buff interaction.
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Only DamageEvent fires (the existing Phase 7 v2 emission).
    assert len(events) == 1
    assert all(not isinstance(e, BoonApplyEvent) for e in events)
    assert isinstance(events[0], DamageEvent)


def test_parse_events_emit_apply_statechange_filtered_upstream() -> None:
    """APPLY records deliberately do NOT go through the statechange path.

    The upstream ``if is_statechange != 0: continue`` filter (already
    in place since Phase 7 v2) does NOT yield APPLY events from
    statechange records. Per the F1 byte mapping + buff_dispatch
    realignment, APPLY events are encoded as non-statechange cbtevent
    records with ``ev_buff != 0``. CBTS_BUFFAPPLY (statechange
    flavor) is a separate arcdps signal used for INITIAL buff state
    snapshots at fight start, NOT for mid-combat APPLYs.

    This test locks the statechange-filter boundary so a future
    refactor that mistakenly engages statechange as the APPLY
    signal (per the incorrect pre-F1 plan framing) fires at the
    test boundary.
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(42, "Skill")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=0,
                is_statechange=1,  # CBTS_BUFFAPPLY-style marker (NOT mid-combat APPLY)
                ev_buff=42,         # would-be APPLY buff ID
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Statechange record is filtered upstream -- no events.
    # APPLY predicate is unreachable for statechange records.
    assert events == []


# ---------------------------------------------------------------------------
# F1 Byte-mapping lock: byte 49 IS arcdps's ev.buff field
# ---------------------------------------------------------------------------


def test_parse_events_offset_49_is_ev_buff_empirical_lock_F1() -> None:  # noqa: N802 -- F1 calibration suffix
    """Byte 49 of the cbtevent record reads as ``_ev_buff`` (struct slot 13) -- the arcdps buff ID.

    The 2026-07-11 F1 calibration confirmed byte-49 byte-position
    alignment with arcdps's ``ev.buff`` field (per the F1 calibration
    table: byte 49 zero-percentage ~80% on typical rev=1 fights,
    matches arcdps's `buff` byte semantics). Phase 9 Step 3
    consumes this byte as the APPLY-predicate discriminator.
    Renamed from the legacy ``_is_flanking`` to ``_ev_buff`` to
    reflect the F1 byte mapping (the byte position is unchanged;
    the rename has zero byte-level impact).
    """
    record = bytearray(64)
    record[49] = 99  # ev_buff = 99 (non-zero == buff interaction)
    unpacked = _EVENT_STRUCT.unpack_from(bytes(record), 0)
    assert unpacked[13] == 99, (
        f"_ev_buff byte should be at offset 49 (struct slot 13). "
        f"Read {unpacked[13]} from slot 13 of the unpack tuple. "
        f"F1 calibration pinned this byte to arcdps's ev.buff field."
    )
