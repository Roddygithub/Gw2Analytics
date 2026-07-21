"""Hermetic tests for WAVE-8 v0.11.0 Blocker A.4 statechange event emission.

The A.4 sub-slice wires the parser's ``is_statechange != 0`` filter
into a dispatch table that emits Pydantic domain events for the
arcdps statechange kinds that have a matching subclass in
``libs/gw2_core/src/gw2_core/models.py``. A.4 ships 4 emit entries:
``StunBreakEvent`` (byte 56), ``BarrierEvent`` (byte 38),
``DeathEvent`` (byte 4), ``DownEvent`` (byte 5).

The tests in this file lock the A.4.1 dispatch contract so a future
refactor that:

1. Reverts to the upstream ``is_statechange != 0: continue`` filter
   (loses the StunBreak + Barrier wire-stream integration with the
   downstream aggregator chain),
2. Yields events for unmapped statechange kinds (pollutes the event
   stream with phantom events for the 84 arcdps kinds not yet
   modelled in the domain),
3. Reorders the emit + filter so the REMOVE / APPLY predicates
   accidentally fire on statechange records (the Phase 9 byte
   alignment is sensitive to record-type ordering),

fires at the unit-test boundary BEFORE the regression propagates to
the F1 calibration pilot or downstream ``buff_uptime`` aggregators.

Hermetic-fixture rationale: the build helpers
(:func:`_build_event_record` + :func:`_build_minimal_evtc`) are
duplicated from :file:`test_parser_emit_buff.py` to keep this test
file self-contained -- pytest's collection path (without a
``__init__.py`` in the ``tests/`` directory) cannot resolve
cross-test imports. The duplication cost (~50 lines) is cheaper than
introducing a package init OR a shared conftest.py for two
consumers (this file + ``test_parser_emit_buff.py``).

Test file split rationale: the byte-alignment tests in
:file:`test_parser_byte_alignment.py` exercise the struct field
extraction; the predicate-boundary tests in
:file:`test_parser_emit_buff.py` exercise the REMOVE / APPLY
predicate boundaries; this file exercises the A.4.1 statechange
dispatch boundary. The three end-to-end dimensions are independent.
"""

from __future__ import annotations

import struct
from typing import Final

from gw2_core import BarrierEvent, DamageEvent, DeathEvent, DownEvent, StunBreakEvent
from gw2_evtc_parser import PythonEvtcParser
from gw2_evtc_parser.parser import _EVENT_STRUCT
from gw2_evtc_parser.statechange_dispatch import (
    STATE_CHANGE_BARRIER_UPDATE,
    STATE_CHANGE_DEATH,
    STATE_CHANGE_DOWN,
    STATE_CHANGE_STUN_BREAK,
)

# ---------------------------------------------------------------------------
# Local copies of build-event fixtures (mirrors test_parser_emit_buff.py)
# ---------------------------------------------------------------------------

#: Reused struct format -- mirrors the parser's ``_EVENT_STRUCT`` literal 1:1.
_CBTEVENT_FMT: Final[struct.Struct] = struct.Struct("<QQQiiIIHHHbbbbbbbbIIbb")
_AGENT_NAME_SIZE: Final[int] = 72


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

    Mirrors :file:`test_parser_emit_buff.py::_build_event_record`
    1:1 (same pack-order + same byte-position lock for
    ``is_statechange`` (byte 48), ``ev_buff`` (byte 49),
    ``is_buffremove`` (byte 52)) so the A.4.1 dispatch tests use the
    same fixture shape as the REMOVE / APPLY predicate tests.
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
        is_cleanup,  # byte 46 = is_cleanup
        is_nondamage,  # byte 47 = is_nondamage
        is_statechange,  # byte 48 = is_statechange
        ev_buff,  # byte 49 = ev.buff (arcdps buff ID)
        0,  # byte 50 = result (was is_shields)
        is_offcycle,  # byte 51 = is_activation (was is_offcycle)
        is_buffremove,  # byte 52 = is_buffremove (arcdps cbtbuffremove)
        0,  # byte 53 = is_ninety
        0,  # pad63 (u32 slot 1, offsets 54-57)
        0,  # pad64 (u32 slot 2, offsets 58-61)
        0,  # pad65 (byte 62)
        0,  # pad66 (byte 63)
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

    Mirrors the helper in :file:`test_parser.py` -- duplicated here
    so this test file stays self-contained (no cross-test imports).
    The agent-record 72-byte name buffer is filled entirely with
    nulls; this test file does NOT exercise the player / NPC split
    (the dispatch-boundary tests don't depend on agent decode). The
    fixture builder still produces structurally-valid 96-byte agent
    records so the parser can locate the event block.
    """
    if len(build) != 8:
        msg = f"build must be exactly 8 ASCII chars (yyyymmdd), got {len(build)}"
        raise ValueError(msg)
    if skills is None:
        skills = []
    if events is None:
        events = []
    header = struct.pack(
        "<4s8sBHBII",
        b"EVTC",
        build.encode("ascii"),
        0,
        encounter_id,
        0,
        len(agents),
        len(skills),
    )
    prefix_fmt = struct.Struct("<QIIhhhh")
    name_buf = b"\x00" * _AGENT_NAME_SIZE
    body = bytearray()
    for aid, prof, elite, _name, _is_player in agents:
        # 24-byte prefix + 72-byte all-null name buffer = 96 bytes
        # (struct ag size) per agent record.
        body += prefix_fmt.pack(aid, prof, elite, 0, 0, 0, 0) + name_buf
    # Legacy count prefix BEFORE the fixed-size skill records so the
    # parser's _detect_skill_format correctly identifies the format.
    # Without this prefix, the first skill_id (e.g. 42 or 777) is
    # misread as the count, the parser walks inflated skills into
    # event data, and the remaining bytes fall short of EVENT_SIZE.
    body += struct.pack("<I", len(skills))
    for skill_id, skill_name in skills:
        name_bytes = skill_name.encode("utf-8")[:64]
        name_buf = name_bytes.ljust(64, b"\x00")
        body += struct.pack("<I64s", skill_id, name_buf)
    for ev in events:
        if len(ev) != 64:  # EVENT_SIZE
            msg = f"each event record must be exactly 64 bytes, got {len(ev)}"
            raise ValueError(msg)
        body += ev
    return header + bytes(body)


# ---------------------------------------------------------------------------
# A.4 dispatch boundary tests
# ---------------------------------------------------------------------------


def test_parse_events_dispatch_stun_break_yields_event() -> None:
    """Statechange byte 56 (StunBreak) yields ONE StunBreakEvent (actor-only shape).

    Locks the A.4.1 dispatch contract: a hand-crafted cbtevent record
    with ``is_statechange = 56`` (the arcdps ``CBTS_STUNBREAK`` kind
    per :file:`docs/statechange-ids.md`) yields exactly one
    :class:`~gw2_core.StunBreakEvent` instance with the actor-only
    shape (target_agent_id=0, skill_id=0 -- StunBreak is not
    skill-attributable per the :class:`StunBreakEvent` docstring).
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(42, "Skill")],
        events=[
            # Dummy no-op event: value=0, is_statechange=0, buff_dmg=0
            # so parse_events yields nothing.  Required so the parser's
            # _detect_skill_format_nonzero boundary search has enough
            # candidate events (>= 2 EVENT_SIZE-aligned reads) to
            # identify the legacy count prefix.
            _build_event_record(time_ms=1, src_agent=1, dst_agent=1, value=0),
            _build_event_record(
                time_ms=7_500,
                src_agent=42,
                dst_agent=99,  # ignored -- StunBreak is actor-only
                value=0,
                skill_id=777,  # ignored -- StunBreak is actor-only
                is_statechange=STATE_CHANGE_STUN_BREAK,  # byte 56
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Exactly one event: the dispatched StunBreakEvent. The damage /
    # heal / REMOVE / APPLY predicates do NOT fire (the statechange
    # branch ``continue``s after the dispatch).
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, StunBreakEvent)
    assert e.time_ms == 7_500
    assert e.source_agent_id == 42
    # Actor-only shape guarantees (per StunBreakEvent docstring).
    assert e.target_agent_id == 0
    assert e.skill_id == 0


def test_parse_events_dispatch_barrier_update_yields_event() -> None:
    """Statechange byte 38 (BarrierUpdate) yields ONE BarrierEvent.

    The deferred-Phase-6-v2 fields (``barrier_amount`` +
    ``duration_ms``) default to ``0`` per :class:`BarrierEvent`
    design contract (see WAVE-8-parser-side.md §A.4.1).

    Locks the A.4.1 dispatch contract for the Barrier statechange.
    The ``barrier_amount`` + ``duration_ms`` fields default to ``0``
    per the deferred-Phase-6-v2 design (the per-skill barrier table
    is the parser-stream yield; pre-Phase-6-v2 streams parse cleanly
    because both fields default to ``0`` -- matches the
    :class:`BarrierEvent` docstring contract).
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(777, "BarrierSkill")],
        events=[
            # Dummy no-op event (see stun-break test for rationale).
            _build_event_record(time_ms=1, src_agent=1, dst_agent=1, value=0),
            _build_event_record(
                time_ms=8_000,
                src_agent=45,
                dst_agent=99,
                value=0,
                skill_id=777,
                is_statechange=STATE_CHANGE_BARRIER_UPDATE,  # byte 38
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, BarrierEvent)
    assert e.time_ms == 8_000
    assert e.source_agent_id == 45
    assert e.target_agent_id == 99
    assert e.skill_id == 777
    # Deferred Phase 6 v2 fields default to 0 (per BarrierEvent
    # docstring: "pre-Phase-6-v2 streams parse cleanly because both
    # fields default to 0").
    assert e.barrier_amount == 0
    assert e.duration_ms == 0


def test_parse_events_dispatch_death_yields_event() -> None:
    """Statechange byte 4 (ChangeDead) yields ONE DeathEvent (actor-only).

    Locks the A.4.3 dispatch contract: a hand-crafted cbtevent record
    with ``is_statechange = 4`` (the arcdps ``CBTS_CHANGEDEAD`` kind
    per :file:`docs/statechange-ids.md`) yields exactly one
    :class:`~gw2_core.DeathEvent` instance with actor-only shape
    (target_agent_id=0, skill_id=0, killed_by_agent_id=None,
    killing_skill_id=None).
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(42, "Skill")],
        events=[
            _build_event_record(time_ms=1, src_agent=1, dst_agent=1, value=0),
            _build_event_record(
                time_ms=12_000,
                src_agent=77,
                dst_agent=0,
                value=0,
                skill_id=0,
                is_statechange=STATE_CHANGE_DEATH,  # byte 4
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, DeathEvent)
    assert e.time_ms == 12_000
    assert e.source_agent_id == 77
    assert e.target_agent_id == 0
    assert e.skill_id == 0
    # Forward-compat fields: statechange record carries no kill attribution.
    assert e.killed_by_agent_id is None
    assert e.killing_skill_id is None


def test_parse_events_dispatch_down_yields_event() -> None:
    """Statechange byte 5 (ChangeDown) yields ONE DownEvent (actor-only).

    Locks the A.4.3 dispatch contract: a hand-crafted cbtevent record
    with ``is_statechange = 5`` (the arcdps ``CBTS_CHANGEDOWN`` kind
    per :file:`docs/statechange-ids.md`) yields exactly one
    :class:`~gw2_core.DownEvent` instance with actor-only shape
    (target_agent_id=0, skill_id=0, downtime_ms=0).
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(42, "Skill")],
        events=[
            _build_event_record(time_ms=1, src_agent=1, dst_agent=1, value=0),
            _build_event_record(
                time_ms=15_000,
                src_agent=88,
                dst_agent=0,
                value=0,
                skill_id=0,
                is_statechange=STATE_CHANGE_DOWN,  # byte 5
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, DownEvent)
    assert e.time_ms == 15_000
    assert e.source_agent_id == 88
    assert e.target_agent_id == 0
    assert e.skill_id == 0
    # Forward-compat: statechange record carries no downtime duration.
    assert e.downtime_ms == 0


def test_parse_events_dispatch_unmapped_statechange_yields_no_event() -> None:
    """Unmapped statechange bytes (e.g. byte 3 = ChangeUp) yield ZERO events.

    Locks the A.4 dispatch boundary for the arcdps kinds not yet
    modelled in the dispatch table. The upstream filter continues to
    suppress them (the dispatch returns ``None`` so the
    ``if statechange_event is not None: yield`` branch is silent).
    A future refactor that mistakenly yields events for unmapped
    kinds (polluting the event stream with phantom ChangeUp /
    WeaponSwap / etc. records) fires at the unit-test boundary.
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
                is_statechange=3,  # CBTS_CHANGEUP (unmapped in A.4.1)
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Unmapped kind: dispatch returns None, no event yielded. The
    # existing damage path does NOT fire (the statechange filter
    # short-circuits BEFORE the damage predicate).
    assert events == []


def test_parse_events_dispatch_does_not_break_damage_path() -> None:
    """Non-statechange damage records still yield DamageEvent (backward compat pin).

    Companion to :file:`test_parser_emit_buff.py` -- locks the
    backward-compat boundary: the A.4.1 dispatch change does NOT
    regress the existing damage / heal / strip / REMOVE / APPLY
    emit paths. A default-fixture cbtevent (is_statechange=0,
    value>0, is_nondamage=0) still yields ONE DamageEvent via the
    pre-existing Phase 7 v2 emission.
    """
    evtc = _build_minimal_evtc(
        [(1, 1, 1, "Src", True)],
        skills=[(101, "Skill")],
        events=[
            _build_event_record(
                time_ms=1_000,
                src_agent=1,
                dst_agent=2,
                value=500,
                skill_id=101,
                # is_statechange defaults to 0 -- dispatch branch not reached.
            ),
        ],
    )
    events = list(PythonEvtcParser().parse_events(evtc))
    # Pre-A.4.1 surface preserved: 1 DamageEvent yielded.
    assert len(events) == 1
    assert isinstance(events[0], DamageEvent)
    assert events[0].damage == 500


# ---------------------------------------------------------------------------
# F1 byte-mapping lock: byte 48 IS arcdps's is_statechange field
# ---------------------------------------------------------------------------


def test_parse_events_offset_48_is_statechange_empirical_lock_F1() -> None:  # noqa: N802 -- F1 suffix
    """Byte 48 of the cbtevent record reads as ``is_statechange`` (struct slot 12).

    The 2026-07-11 F1 calibration confirmed byte-48 byte-position
    alignment with arcdps's ``is_statechange`` field. The A.4.1
    dispatch predicate (``is_statechange != 0``) reads this byte to
    decide whether to route the record through the dispatch table.
    Renamed from the legacy ``is_statechange`` to reflect the F1
    byte mapping (the byte position is unchanged; the rename has
    zero byte-level impact).
    """
    record = bytearray(64)
    record[48] = 56  # is_statechange = 56 (StunBreak)
    unpacked = _EVENT_STRUCT.unpack_from(bytes(record), 0)
    assert unpacked[12] == 56, (
        f"is_statechange byte should be at offset 48 (struct slot 12). "
        f"Read {unpacked[12]} from slot 12 of the unpack tuple. "
        f"F1 calibration pinned this byte to arcdps's is_statechange field."
    )
