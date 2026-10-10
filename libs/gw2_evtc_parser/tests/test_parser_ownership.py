"""``scan_ownership_intervals`` reports when an agent was owned by a master.

The scanner had no tests. It feeds ``gw2_core.OwnershipInterval``, which the
product's time-parameterised identity resolution consumes
(``gw2_analytics.temporal_identity``), so a silent change here moves per-player
attribution rather than failing loudly.

The helpers are duplicated from the sibling test modules for the same reason
they are duplicated between those: pytest's collection path has no
``__init__.py`` in ``tests/``, so cross-test imports do not resolve.

These fixtures use the pre-2025 (legacy) EVTC layout, whose event record has no
``src_master_instid`` field. The scanner therefore cannot derive a master from
it -- ownership stays ``None`` and only the lifecycle (spawn/despawn) path is
exercised. That is a real limitation of the scanner on legacy logs, not of the
test, and it is why every interval below has ``owner_agent_id is None``.
"""

from __future__ import annotations

import struct

from gw2_core import OwnershipInterval
from gw2_evtc_parser import scan_ownership_intervals

_LEGACY_STRUCT = struct.Struct("<QQQii4xI7xbbbbbb11x")
_AGENT_NAME_SIZE = 72


def _event(time_ms: int, src_agent: int, dst_agent: int, is_statechange: int = 0) -> bytes:
    """One 64-byte cbtevent carrying timestamp, actors, and statechange."""
    # is_statechange is tuple index 7 in the legacy unpack struct:
    # (time, src, dst, val, buff_dmg, skill, is_nondamage, is_statechange, ...)
    return _LEGACY_STRUCT.pack(
        time_ms, src_agent, dst_agent, 0, 0, 0, 0, is_statechange, 0, 0, 0, 0
    )


def _evtc(events: list[bytes]) -> bytes:
    """One legacy-layout agent, an empty skill table, then the event block."""
    build = b"20240925"
    header = struct.pack("<4s8sBHBI I", b"EVTC", build, 0, 0, 0, 1, 0)
    agent = struct.pack("<QIIhhhh", 1, 1, 0, 0, 0, 0, 0) + b"\x00" * _AGENT_NAME_SIZE
    skill_table = struct.pack("<I", 0)
    return header + agent + skill_table + b"".join(events)


def test_interval_is_half_open_between_spawn_and_despawn() -> None:
    raw = _evtc([_event(1_000, 10, 0, is_statechange=0), _event(3_000, 10, 0, is_statechange=1)])

    intervals = scan_ownership_intervals(raw)

    assert intervals == [
        OwnershipInterval(
            agent_id=10,
            owner_agent_id=None,
            instance_id=0,
            species_id=None,
            start_ms=0,
            end_ms=2_000,
            is_player=False,
        )
    ]
    # Times are fight-relative: the first non-zero record is the origin.
    assert intervals[0].start_ms == 0


def test_open_interval_is_closed_at_fight_end() -> None:
    """An agent that never despawns still gets an interval, up to the last sighting."""
    raw = _evtc([_event(1_000, 10, 0, is_statechange=0), _event(2_000, 20, 0, is_statechange=0)])

    intervals = scan_ownership_intervals(raw)

    # fight_end is the latest fight_time among still-active agents (1_000), so
    # agent 10 closes at 1_000 and agent 20 -- which starts exactly there --
    # produces nothing.
    assert len(intervals) == 1
    assert intervals[0].agent_id == 10
    assert (intervals[0].start_ms, intervals[0].end_ms) == (0, 1_000)


def test_despawn_without_a_spawn_produces_no_interval() -> None:
    raw = _evtc([_event(2_000, 10, 0, is_statechange=1)])

    assert scan_ownership_intervals(raw) == []


def test_non_positive_timestamps_do_not_move_the_origin() -> None:
    """``time == 0`` records are header-ish metadata, not combat activity.

    The zero record sits mid-block: leading the event stream with it also moves
    the parser's skill-table boundary heuristic, which is a separate concern
    (see the sibling ``test_parser_awareness`` module).
    """
    raw = _evtc(
        [
            _event(1_000, 10, 0, is_statechange=0),
            _event(0, 99, 88, is_statechange=0),
            _event(3_000, 10, 0, is_statechange=1),
        ]
    )

    intervals = scan_ownership_intervals(raw)

    assert len(intervals) == 1
    # If the zero-timestamp record had counted, the origin would be 0 and the
    # despawn would land at 3_000 instead of 2_000.
    assert (intervals[0].start_ms, intervals[0].end_ms) == (0, 2_000)


def test_intervals_are_sorted_by_start_then_agent() -> None:
    raw = _evtc(
        [
            _event(1_000, 20, 0, is_statechange=0),
            _event(3_000, 10, 0, is_statechange=0),
            _event(4_000, 20, 0, is_statechange=1),
            _event(4_000, 10, 0, is_statechange=1),
        ]
    )

    intervals = scan_ownership_intervals(raw)

    # Agent 20 owns [0, 3_000), agent 10 owns [2_000, 3_000): sorted by start.
    assert [(iv.agent_id, iv.start_ms, iv.end_ms) for iv in intervals] == [
        (20, 0, 3_000),
        (10, 2_000, 3_000),
    ]


def test_no_events_yields_no_intervals() -> None:
    assert scan_ownership_intervals(_evtc([])) == []
