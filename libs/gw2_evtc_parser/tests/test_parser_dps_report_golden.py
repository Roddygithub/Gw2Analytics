from __future__ import annotations

import os
from pathlib import Path

import pytest

from gw2_core import DamageEvent
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
