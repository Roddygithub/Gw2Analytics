import json
import os
from pathlib import Path

import pytest

from gw2_analytics.ei_compare import compare_elite_insights
from gw2_core import CombatOutcomeEvent, DownEvent, UpEvent
from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive

_CORPUS = Path("/home/roddy/Projects/WvW/WvW (1)/Sshim Daath")
_EI_CORPUS = os.environ.get("GW2ANALYTICS_EI_CORPUS")


@pytest.mark.parametrize(
    ("name", "duration_ms", "agents", "events", "downs", "ups", "outcomes"),
    [
        ("20251205-211525.zevtc", 69_097, 119, 37_760, 1, 1, 2),
        ("20251207-225200.zevtc", 151_791, 323, 82_586, 47, 34, 19),
        ("20251208-230823.zevtc", 74_837, 115, 19_153, 12, 5, 17),
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


@pytest.mark.parametrize(
    ("log_name", "ei_name", "max_differences"),
    [
        ("20251205-211525.zevtc", "20251205-211525_detailed_wvw_kill.json", 340),
        ("20251207-225200.zevtc", "20251207-225200_detailed_wvw_kill.json", 131),
        ("20251208-230823.zevtc", "20251208-230823_detailed_wvw_kill.json", 114),
    ],
)
def test_elite_insights_multilog_alignment_does_not_regress(
    log_name: str, ei_name: str, max_differences: int
) -> None:
    if _EI_CORPUS is None:
        pytest.skip("set GW2ANALYTICS_EI_CORPUS to official EI JSON exports")
    log_path = _CORPUS / log_name
    ei_path = Path(_EI_CORPUS) / ei_name
    if not log_path.exists() or not ei_path.exists():
        pytest.skip("optional EVTC/EI corpus unavailable")

    raw = read_zevtc_archive(log_path)
    parser = PythonEvtcParser()
    result = compare_elite_insights(
        next(parser.parse(raw)), json.loads(ei_path.read_text()), list(parser.parse_events(raw))
    )
    differences = result["differences"]

    assert isinstance(differences, dict)
    assert len(differences) <= max_differences
