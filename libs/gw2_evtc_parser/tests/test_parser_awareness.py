"""``scan_agent_awareness`` reports each agent's first/last mention.

Awareness bounds an actor's buff simulation: Elite Insights stops accruing
uptime once the log stops seeing an actor, so an agent that drops off the
log mid-fight must not keep its still-active boons running to the end. The
span has to come from the *raw* cbtevent stream rather than the events the
parser emits -- the emitted stream lands a median 181 ms early on the WvW
corpus, enough to shift every uptime by ~0.1 points.

The helpers here are duplicated from the sibling test modules for the same
reason they are duplicated between those: pytest's collection path has no
``__init__.py`` in ``tests/``, so cross-test imports do not resolve.
"""

from __future__ import annotations

import struct

from gw2_evtc_parser import scan_agent_awareness

_CBTEVENT_FMT = struct.Struct("<QQQiiIIHHHBBBBBBBBIIBB")
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


def test_scan_agent_awareness_spans_first_to_last_mention() -> None:
    raw = _evtc(
        [
            _event(1_000, 10, 20),
            _event(1_500, 20, 30),
            _event(4_000, 10, 0),
        ]
    )
    awareness = scan_agent_awareness(raw)

    # Times are fight-relative: the earliest non-zero record is the origin.
    assert awareness[10] == (0, 3_000)
    assert awareness[20] == (0, 500)
    assert awareness[30] == (500, 500)


def test_scan_agent_awareness_counts_an_agent_as_target_too() -> None:
    raw = _evtc([_event(1_000, 10, 20), _event(2_000, 30, 20)])
    awareness = scan_agent_awareness(raw)

    # 20 never acts, but the log keeps mentioning it, so it stays aware.
    assert awareness[20] == (0, 1_000)


def test_scan_agent_awareness_skips_zero_timestamp_metadata() -> None:
    """``time == 0`` records are header-ish metadata, not combat activity."""
    # The zero-timestamp record sits mid-block: leading it would also move
    # the parser's skill-table boundary heuristic, which is a separate concern.
    raw = _evtc([_event(1_000, 10, 20), _event(0, 99, 88), _event(2_000, 10, 20)])
    awareness = scan_agent_awareness(raw)

    assert 99 not in awareness
    assert awareness[10] == (0, 1_000)


def test_scan_agent_awareness_ignores_absent_agent_ids() -> None:
    raw = _evtc([_event(1_000, 10, 0)])
    awareness = scan_agent_awareness(raw)

    assert 0 not in awareness
    assert awareness == {10: (0, 0)}


def test_scan_agent_awareness_excludes_healthupdate_and_stackactive() -> None:
    """HealthUpdate (8) and StackActive (27) carry stale agent mentions post-despawn."""
    raw = _evtc([
        _event(1_000, 10, 0, is_statechange=0),
        _event(2_000, 10, 0, is_statechange=8),   # HealthUpdate — skipped
        _event(3_000, 10, 0, is_statechange=27),  # StackActive — skipped
        _event(4_000, 10, 0, is_statechange=0),
    ])
    awareness = scan_agent_awareness(raw)

    # 2_000 and 3_000 events are skipped, so span runs 1_000 to 4_000 (relative: 0 to 3_000)
    assert awareness[10] == (0, 3_000)

    # If all non-first events are skipped statechanges, the agent only stays aware at 1_000
    raw_only_skipped = _evtc([
        _event(1_000, 10, 0, is_statechange=0),
        _event(5_000, 10, 0, is_statechange=8),
        _event(6_000, 10, 0, is_statechange=27),
    ])
    awareness_skipped = scan_agent_awareness(raw_only_skipped)
    assert awareness_skipped[10] == (0, 0)

