from __future__ import annotations

import os
from pathlib import Path

import pytest

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
    assert len(fight.agents) == 13
    assert len([a for a in fight.agents if a.is_player and a.account_name]) == 9
    assert len(fight.skills) == 296
