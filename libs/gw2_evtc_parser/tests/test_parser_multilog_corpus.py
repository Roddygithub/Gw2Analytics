from pathlib import Path

import pytest

from gw2_core import CombatOutcomeEvent, DownEvent, UpEvent
from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive

_CORPUS = Path("/home/roddy/Projects/WvW/WvW (1)/Sshim Daath")


@pytest.mark.parametrize(
    ("name", "duration_ms", "agents", "events", "downs", "ups", "outcomes"),
    [
        ("20251205-211525.zevtc", 69_097, 119, 51_080, 1, 1, 2),
        ("20251207-225200.zevtc", 151_791, 323, 111_878, 47, 34, 19),
        ("20251208-230823.zevtc", 74_837, 115, 20_786, 12, 5, 7),
    ],
)
def test_evtc_2025_multilog_corpus(
    name: str,
    duration_ms: int,
    agents: int,
    events: int,
    downs: int,
    ups: int,
    outcomes: int,
) -> None:
    path = _CORPUS / name
    if not path.exists():
        pytest.skip("optional local EVTC corpus unavailable")

    raw = read_zevtc_archive(path)
    parser = PythonEvtcParser()
    fight = next(parser.parse(raw))
    parsed = list(parser.parse_events(raw))

    assert fight.header is not None
    assert fight.header.build_version == "20251123"
    assert fight.header.duration_ms == duration_ms
    assert len(fight.agents) == agents
    assert len(parsed) == events
    assert sum(isinstance(event, DownEvent) for event in parsed) == downs
    assert sum(isinstance(event, UpEvent) for event in parsed) == ups
    assert sum(isinstance(event, CombatOutcomeEvent) for event in parsed) == outcomes
