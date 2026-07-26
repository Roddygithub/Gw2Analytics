from __future__ import annotations

from gw2_core import EvtcHeader, Fight
from gw2_evtc_parser.__main__ import _build_parser, _compare_ei_metadata


def test_compare_ei_metadata_reports_exact_differences() -> None:
    fight = Fight(
        id="golden",
        success=True,
        ei_encounter_id=459_520,
        header=EvtcHeader(
            build_version="20250925",
            encounter_id=1,
            agent_count=13,
            gw2_build=188_004,
            map_id=96,
            arc_revision=162_433,
            duration_ms=11_789,
        ),
    )
    expected = {
        "arcVersion": "EVTC20250925",
        "triggerID": 1,
        "gW2Build": 188_004,
        "mapID": 96,
        "arcRevision": 162_433,
        "durationMS": 12_000,
        "success": True,
        "eiEncounterID": 459_520,
    }

    result = _compare_ei_metadata(fight, expected)

    assert result["matches"] is False
    assert result["differences"] == {
        "durationMS": {"expected": 12_000, "actual": 11_789}
    }


def test_compare_ei_command_is_registered() -> None:
    args = _build_parser().parse_args(["compare-ei", "fight.zevtc", "ei.json"])

    assert args.cmd == "compare-ei"
