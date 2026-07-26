from __future__ import annotations

import os
from pathlib import Path

import pytest

from gw2_analytics.buff_state import BuffStateTracker
from gw2_core import (
    BlockEvent,
    BoonApplyEvent,
    BuffApplyEvent,
    BuffRemovalEvent,
    DamageEvent,
    HealingEvent,
    StunBreakEvent,
)
from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive

_DEFAULT_LOG = Path(
    "/home/roddy/Projects/WvW/WvW (1)/Ess Kitable/20250928-230925.zevtc"
)


def _golden_log_path() -> Path:
    return Path(os.environ.get("GW2ANALYTICS_GOLDEN_LOG", str(_DEFAULT_LOG)))


@pytest.mark.skipif(
    not _golden_log_path().exists(),
    reason="golden WvW log unavailable; set GW2ANALYTICS_GOLDEN_LOG",
)
def test_dps_report_20250928_230925_metadata_matches_parser() -> None:
    """Golden metadata from dps.report upload 9wGp-20250928-230925."""
    raw = read_zevtc_archive(_golden_log_path())
    fight = next(PythonEvtcParser().parse(raw))

    assert fight.header is not None
    assert fight.header.build_version == "20250925"
    assert fight.header.encounter_id == 1
    assert fight.header.gw2_build == 188004
    assert fight.header.map_id == 96
    assert fight.header.arc_revision == 162433
    assert fight.header.duration_ms == 11789
    assert fight.success is True
    assert fight.ei_encounter_id == 459520
    assert len(fight.agents) == 13
    accounts_by_agent = {
        a.id: a.account_name.lstrip(":") for a in fight.agents if a.is_player and a.account_name
    }
    assert accounts_by_agent == {
        2_000: "esskape.5047",
        45_822: "krill le faucheur.1679",
        45_830: "LuiStheGamers.5132",
        45_859: "Lullupa.5768",
        45_874: "talon.6751",
        45_944: "Kurupt.6378",
        45_945: "Fabzzz.1439",
        45_946: "EstaticFear.7692",
        45_947: "Demandred.9035",
    }
    players_by_account = {
        a.account_name.lstrip(":"): (a.instance_id, a.team_id)
        for a in fight.agents
        if a.account_name
    }
    assert players_by_account["esskape.5047"] == (2_924, 2_763)
    assert players_by_account["Lullupa.5768"] == (3_201, 2_763)
    assert players_by_account["krill le faucheur.1679"] == (2_356, 2_763)
    assert players_by_account["EstaticFear.7692"] == (4_240, 2_763)
    assert players_by_account["Demandred.9035"] == (4_882, 2_763)
    assert len(fight.skills) == 168

    damage = [
        event
        for event in PythonEvtcParser().parse_events(raw)
        if isinstance(event, DamageEvent) and event.source_agent_id == 45_947
    ]
    assert sum(event.damage for event in damage) == 27_214
    assert sum(event.buff_dmg for event in damage) == 1_130

    events = list(PythonEvtcParser().parse_events(raw))
    lullupa_id = 45_859
    assert sum(
        event.damage
        for event in events
        if isinstance(event, DamageEvent) and event.target_agent_id == lullupa_id
    ) == 771
    assert sum(
        isinstance(event, BlockEvent) and event.source_agent_id == 45_822 for event in events
    ) == 1
    assert not any(isinstance(event, HealingEvent) for event in events)
    assert not any(isinstance(event, BuffRemovalEvent) for event in events)
    ei_player_ids = {2_000, 45_822, 45_859, 45_946, 45_947}
    assert not any(
        isinstance(event, StunBreakEvent) and event.source_agent_id in ei_player_ids
        for event in events
    )

    demandred_quickness = [
        event
        for event in events
        if isinstance(event, BoonApplyEvent)
        and event.target_agent_id == 45_947
        and event.skill_id == 1_187
        and event.kind == "apply"
    ]
    assert [(event.time_ms - 42_047_693, event.duration_ms) for event in demandred_quickness] == [
        (5_647, 3_000),
        (8_645, 3_000),
        (11_640, 3_000),
    ]
    assert any(
        isinstance(event, BuffApplyEvent)
        and event.target_agent_id == 45_822
        and event.skill_id == 743
        and event.initial
        for event in events
    )

    tracker = BuffStateTracker(start_time_ms=min(event.time_ms for event in events))
    for event in events:
        if isinstance(event, (BoonApplyEvent, BuffApplyEvent)):
            tracker.process(event)

    lullupa = tracker.compute_player_uptimes(45_859, 11_789)
    krill = tracker.compute_player_uptimes(45_822, 11_789)
    demandred = tracker.compute_player_uptimes(45_947, 11_789)
    assert lullupa["resolution"] == pytest.approx(97.54, abs=0.001)
    assert krill["aegis"] == pytest.approx(39.002, abs=0.001)
    assert krill["resolution"] == pytest.approx(60.998, abs=0.001)
    assert demandred["quickness"] == pytest.approx(52.099, abs=0.001)
    assert demandred["might"] == pytest.approx(3.917, abs=0.001)
    assert demandred["stability"] == pytest.approx(0.763, abs=0.001)
