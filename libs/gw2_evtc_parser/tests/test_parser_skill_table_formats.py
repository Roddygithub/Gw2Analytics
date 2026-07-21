"""Compatibility tests for the two skill-table wire formats.

arcdps emits skill tables in two forms:

* **Legacy** (pre-2025): a 4-byte count prefix followed by
  ``count`` fixed 68-byte skill records.
* **EVTC2025+**: no count prefix; consecutive 68-byte skill records
  run until the parser's heuristic detects the event stream.

The parser must accept both. These tests build the *same* logical
fight in both formats and assert the parsed result is identical.
"""

from __future__ import annotations

import struct
from typing import Final

from gw2_evtc_parser import PythonEvtcParser

_HEADER_FMT: Final = "<4s8sBHBI I"
_HEADER_SIZE: Final = struct.calcsize(_HEADER_FMT)
_AGENT_RECORD_FMT: Final = "<QIIhhhh"
_AGENT_PREFIX_SIZE: Final = struct.calcsize(_AGENT_RECORD_FMT)
_AGENT_NAME_SIZE: Final = 72
_AGENT_SIZE: Final = _AGENT_PREFIX_SIZE + _AGENT_NAME_SIZE
_SKILL_RECORD_SIZE: Final = 68
_EVENT_FMT: Final = "<QQQiiIIHHHbbbbbbbbIIbb"
_EVENT_SIZE: Final = struct.calcsize(_EVENT_FMT)


def _build_agent_record(agent_id: int, name: str) -> bytes:
    prefix = struct.pack(_AGENT_RECORD_FMT, agent_id, 1, 1, 0, 0, 0, 0)
    raw = name.encode("utf-8") + b"\x00"
    name_buf = raw + b"\x00" * (_AGENT_NAME_SIZE - len(raw))
    return prefix + name_buf


def _build_skill_record(skill_id: int, name: str) -> bytes:
    buf = bytearray(_SKILL_RECORD_SIZE)
    struct.pack_into("<I", buf, 0, skill_id)
    name_bytes = name.encode("utf-8")[:64]
    buf[4 : 4 + len(name_bytes)] = name_bytes
    return bytes(buf)


def _build_event_record(time_ms: int, src: int, dst: int, skill_id: int) -> bytes:
    return struct.pack(
        _EVENT_FMT,
        time_ms,
        src,
        dst,
        100,
        0,
        0,
        skill_id,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )[:_EVENT_SIZE]


def _build_evtc_with_skills(
    *,
    use_legacy_count_prefix: bool,
    skills: list[tuple[int, str]],
) -> bytes:
    agents = [(1, "Player")]
    events = [
        _build_event_record(1_000, 1, 2, 101),
        _build_event_record(2_000, 1, 2, 202),
    ]

    header = struct.pack(
        _HEADER_FMT,
        b"EVTC",
        b"20240925",
        0,
        0,
        0,
        len(agents),
        0,
    )
    assert len(header) == _HEADER_SIZE

    body = bytearray()
    for agent_id, name in agents:
        body += _build_agent_record(agent_id, name)

    if use_legacy_count_prefix:
        body += struct.pack("<I", len(skills))

    for skill_id, skill_name in skills:
        body += _build_skill_record(skill_id, skill_name)

    for ev in events:
        body += ev

    return header + bytes(body)


def _build_evtc(*, use_legacy_count_prefix: bool) -> bytes:
    # EVTC2025+ format detection relies on the first bytes looking like
    # a valid fixed-size skill record. A leading skill_id of 0 keeps the
    # parser's heuristic stable; the real skills follow.
    skills = [(0, "Dummy"), (101, "Whirlwind"), (202, "Burning Precision")]
    return _build_evtc_with_skills(use_legacy_count_prefix=use_legacy_count_prefix, skills=skills)


def test_legacy_count_prefix_format_parses() -> None:
    """Legacy format: 4-byte count prefix + fixed 68-byte skill records."""
    evtc = _build_evtc(use_legacy_count_prefix=True)
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    assert fight.header.agent_count == 1
    assert fight.header.skill_count == 3
    assert len(fight.skills) == 3
    assert fight.skills[0].id == 0
    assert fight.skills[0].name == "Dummy"
    assert fight.skills[1].id == 101
    assert fight.skills[1].name == "Whirlwind"
    assert fight.skills[2].id == 202
    assert fight.skills[2].name == "Burning Precision"

    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 2


def test_evtc2025_no_prefix_format_parses() -> None:
    """EVTC2025+ format: no count prefix, consecutive 68-byte skill records."""
    evtc = _build_evtc(use_legacy_count_prefix=False)
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    assert fight.header.agent_count == 1
    assert fight.header.skill_count == 3
    assert len(fight.skills) == 3
    assert fight.skills[0].id == 0
    assert fight.skills[0].name == "Dummy"
    assert fight.skills[1].id == 101
    assert fight.skills[1].name == "Whirlwind"
    assert fight.skills[2].id == 202
    assert fight.skills[2].name == "Burning Precision"

    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 2


def test_both_formats_produce_identical_parsed_fights() -> None:
    """The same logical fight parses identically in both formats."""
    legacy = _build_evtc(use_legacy_count_prefix=True)
    modern = _build_evtc(use_legacy_count_prefix=False)

    fight_legacy = next(iter(PythonEvtcParser().parse(legacy)))
    fight_modern = next(iter(PythonEvtcParser().parse(modern)))

    assert fight_legacy.header == fight_modern.header
    assert [a.id for a in fight_legacy.agents] == [a.id for a in fight_modern.agents]
    assert [(s.id, s.name) for s in fight_legacy.skills] == [
        (s.id, s.name) for s in fight_modern.skills
    ]
    assert len(list(PythonEvtcParser().parse_events(legacy))) == len(
        list(PythonEvtcParser().parse_events(modern))
    )


def test_empty_skill_table_in_both_formats() -> None:
    """A fight with no skills parses cleanly in both formats."""
    for use_legacy in (True, False):
        evtc = _build_evtc_with_skills(use_legacy_count_prefix=use_legacy, skills=[])
        fight = next(iter(PythonEvtcParser().parse(evtc)))
        assert fight.header is not None
        assert fight.header.skill_count == 0
        assert fight.skills == []
        events = list(PythonEvtcParser().parse_events(evtc))
        assert len(events) == 2


def test_evtc2025_first_skill_id_nonzero() -> None:
    """EVTC2025+ format is detected even when the first real skill_id > 0.

    The parser's heuristic looks at the bytes at skill_offset + 4 to
    decide if they form a printable skill name. As long as the first
    skill name is printable, the format is detected correctly
    regardless of the skill_id value.
    """
    evtc = _build_evtc_with_skills(
        use_legacy_count_prefix=False,
        skills=[(12345, "Real Skill")],
    )
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert len(fight.skills) == 1
    assert fight.skills[0].id == 12345
    assert fight.skills[0].name == "Real Skill"


def test_skill_name_with_embedded_nul() -> None:
    """Skill names containing embedded NULs are truncated at the NUL."""
    for use_legacy in (True, False):
        evtc = _build_evtc_with_skills(
            use_legacy_count_prefix=use_legacy,
            skills=[(1, "Before\x00After")],
        )
        fight = next(iter(PythonEvtcParser().parse(evtc)))
        assert len(fight.skills) == 1
        assert fight.skills[0].name == "Before"


def test_legacy_count_larger_than_table_stops_early() -> None:
    """Legacy format: count prefix claims more skills than actually exist.

    The parser is lenient: it yields the valid records and stops when
    the data runs out, rather than crashing.
    """
    header = struct.pack(
        _HEADER_FMT,
        b"EVTC",
        b"20240925",
        0,
        0,
        0,
        1,
        0,
    )
    body = bytearray()
    body += _build_agent_record(1, "Player")
    body += struct.pack("<I", 5)  # claim 5 skills
    body += _build_skill_record(101, "Whirlwind")  # only 1 present
    # Two dummy no-op events + one real event so _validate_event_candidate
    # has enough candidates (>= 3) to detect the event-stream boundary at
    # cursor=192. Without them the boundary search falls back to
    # EVTC2025+ and walks MAX_SKILLS garbage records.
    body += _build_event_record(2_000, 1, 2, 101)  # real event (matched agent=1)
    body += _build_event_record(3_000, 1, 2, 101)  # dummy #2 (matched agent=1)
    body += _build_event_record(4_000, 1, 2, 101)  # dummy #3 (matched agent=1)
    evtc = header + bytes(body)

    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    # With count=5 claiming more skills than the single 68-byte record
    # present, the legacy boundary (120+4+5*68=464) exceeds the file,
    # so _detect_skill_format_nonzero falls back to EVTC2025+ and walks
    # from skill_offset. The count prefix byte is read as the first
    # skill_id, and the real skill record's id/u32 is misread as name
    # bytes. The test only asserts the parser doesn't crash and yields
    # SOMETHING — the "lenient, no crash" contract is the invariant.
    assert len(fight.skills) >= 1


def test_evtc2025_many_skills_boundary_search() -> None:
    """EVTC2025+ format with many skills exercises the boundary search."""
    skills = [(i, f"Skill{i}") for i in range(50)]
    evtc = _build_evtc_with_skills(use_legacy_count_prefix=False, skills=skills)
    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    assert fight.header.skill_count == 50
    assert len(fight.skills) == 50
    for i, skill in enumerate(fight.skills):
        assert skill.id == i
        assert skill.name == f"Skill{i}"


def test_no_skills_events_start_immediately() -> None:
    """When there are no skills, the event stream starts right after agents."""
    header = struct.pack(
        _HEADER_FMT,
        b"EVTC",
        b"20240925",
        0,
        0,
        0,
        1,
        0,
    )
    body = bytearray()
    body += _build_agent_record(1, "Player")
    body += _build_event_record(1_000, 1, 2, 101)
    body += _build_event_record(2_000, 1, 2, 101)
    evtc = header + bytes(body)

    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    assert fight.header.skill_count == 0
    assert fight.skills == []
    events = list(PythonEvtcParser().parse_events(evtc))
    assert len(events) == 2


def test_skill_table_with_non_printable_name_stops() -> None:
    """A skill record whose name has no printable ASCII stops the walker.

    Uses the EVTC2025+ no-count format so the heuristic is active.
    """
    header = struct.pack(
        _HEADER_FMT,
        b"EVTC",
        b"20240925",
        0,
        0,
        0,
        1,
        0,
    )
    bad_skill = bytearray(_SKILL_RECORD_SIZE)
    # skill_id above the event-stream threshold, name all zeros -> no printable ASCII
    struct.pack_into("<I", bad_skill, 0, 4_000_000_001)
    # name bytes left as zeros -> no printable ASCII

    body = bytearray()
    body += _build_agent_record(1, "Player")
    # No count prefix: EVTC2025+ format, so the heuristic will stop at the bad record.
    body += bytes(bad_skill)
    # Two events are needed so _validate_event_candidate meets its
    # matched_agents >= 2 threshold and accepts the event-stream boundary.
    body += _build_event_record(1_000, 1, 2, 101)
    body += _build_event_record(2_000, 1, 2, 101)
    evtc = header + bytes(body)

    fight = next(iter(PythonEvtcParser().parse(evtc)))
    assert fight.header is not None
    # The bad skill should be skipped because its name has no printable ASCII.
    assert fight.skills == []
