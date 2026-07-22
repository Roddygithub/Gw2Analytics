"""Wave 4 / Tour 5 tests for :class:`PlayerBoonsAggregator`.

The Boons aggregator groups boon-apply events by the applying and
receiving player, partitions the 6 fixed buff IDs into named
columns, and buckets the remaining buff IDs into ``other_boons_out``.
It also owns the Phase 6 v2 ``strips_received_in`` target-side
strip count.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gw2_analytics.player_boons import (
    PlayerBoonsAggregator,
    PlayerBoonsRow,
)
from gw2_core import BoonApplyEvent, BuffRemovalEvent


def _boon_apply(
    source: int,
    target: int,
    skill_id: int,
    kind: str = "apply",
    time_ms: int = 0,
    duration_ms: int = 5000,
    stacks: int = 1,
) -> BoonApplyEvent:
    return BoonApplyEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=skill_id,
        kind=kind,
        duration_ms=duration_ms,
        stacks=stacks,
    )


def _strip(target: int, source: int = 1, time_ms: int = 0) -> BuffRemovalEvent:
    return BuffRemovalEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=43,
        buff_removal=1,
    )


class TestPlayerBoonsAggregator:
    """Combat readout Boons contract for :class:`PlayerBoonsAggregator`."""

    def test_empty_input_yields_empty_list(self) -> None:
        rows = PlayerBoonsAggregator().aggregate([], duration_s=10.0)
        assert rows == []

    def test_single_apply_yields_one_row(self) -> None:
        rows = PlayerBoonsAggregator().aggregate(
            [_boon_apply(source=7, target=7, skill_id=1122)],
            duration_s=10.0,
        )
        assert len(rows) == 1
        assert rows[0].agent_id == 7
        assert rows[0].boons_out == 1
        assert rows[0].boons_in == 1
        assert rows[0].stability_out == 1
        assert rows[0].boons_out_rate == 0.1
        assert rows[0].boons_in_rate == 0.1

    def test_remove_events_are_ignored(self) -> None:
        rows = PlayerBoonsAggregator().aggregate(
            [
                _boon_apply(source=7, target=7, skill_id=1122, kind="apply"),
                _boon_apply(source=7, target=7, skill_id=1122, kind="remove_single"),
                _boon_apply(source=7, target=7, skill_id=1122, kind="remove_all"),
            ],
            duration_s=10.0,
        )
        assert len(rows) == 1
        assert rows[0].boons_out == 1
        assert rows[0].boons_in == 1

    def test_fixed_and_other_boons_partition(self) -> None:
        rows = PlayerBoonsAggregator().aggregate(
            [
                _boon_apply(source=5, target=5, skill_id=1122),  # stability
                _boon_apply(source=5, target=5, skill_id=30328),  # alacrity
                _boon_apply(source=5, target=5, skill_id=9999),  # other
            ],
            duration_s=10.0,
            name_map={9999: "Might"},
        )
        assert len(rows) == 1
        assert rows[0].boons_out == 3
        assert rows[0].stability_out == 1
        assert rows[0].alacrity_out == 1
        assert rows[0].other_boons_out == {"Might": 1}

    def test_unknown_boon_name_fallback(self) -> None:
        rows = PlayerBoonsAggregator().aggregate(
            [_boon_apply(source=5, target=1, skill_id=8888)],
            duration_s=10.0,
        )
        assert rows[0].other_boons_out == {"Unknown (8888)": 1}

    def test_strips_received_in(self) -> None:
        rows = PlayerBoonsAggregator().aggregate(
            [_boon_apply(source=5, target=7, skill_id=1122)],
            duration_s=10.0,
            buff_removal_events=[_strip(target=7), _strip(target=7), _strip(target=5)],
        )
        by_agent = {r.agent_id: r for r in rows}
        # 7 is the boon target and receives 2 strips; 5 is the boon source and 1 strip.
        assert by_agent[7].strips_received_in == 2
        assert by_agent[5].strips_received_in == 1

    def test_target_only_agent_surfaces_row(self) -> None:
        """A player who only receives boons (never applies) still gets a row."""
        rows = PlayerBoonsAggregator().aggregate(
            [_boon_apply(source=5, target=9, skill_id=1122)],
            duration_s=10.0,
        )
        by_agent = {r.agent_id: r for r in rows}
        assert 9 in by_agent
        assert by_agent[9].boons_out == 0
        assert by_agent[9].boons_in == 1

    def test_deterministic_ordering_boons_out_desc_agent_asc(self) -> None:
        rows = PlayerBoonsAggregator().aggregate(
            [
                _boon_apply(source=5, target=5, skill_id=1122),
                _boon_apply(source=3, target=3, skill_id=1122),
                _boon_apply(source=3, target=3, skill_id=1122),
                _boon_apply(source=8, target=8, skill_id=1122),
            ],
            duration_s=10.0,
        )
        assert [r.agent_id for r in rows] == [3, 5, 8]
        assert [r.boons_out for r in rows] == [2, 1, 1]

    def test_name_map_resolves_to_player_name(self) -> None:
        rows = PlayerBoonsAggregator().aggregate(
            [_boon_apply(source=7, target=1, skill_id=1122)],
            duration_s=10.0,
            name_map={7: "BoonBrand", 9: None},
        )
        assert rows[0].name == "BoonBrand"

    def test_name_map_resolves_other_boons_out_keys(self) -> None:
        """name_map is also used to resolve human-readable names for unknown buff IDs."""
        rows = PlayerBoonsAggregator().aggregate(
            [
                _boon_apply(source=5, target=5, skill_id=8888),
                _boon_apply(source=5, target=5, skill_id=9999),
            ],
            duration_s=10.0,
            name_map={8888: "Might", 9999: None},
        )
        assert rows[0].other_boons_out == {"Might": 1, "Unknown (9999)": 1}

    def test_model_is_frozen_pydantic(self) -> None:
        row = PlayerBoonsRow(
            agent_id=1,
            boons_out=1,
            boons_in=1,
            boons_out_rate=0.1,
            boons_in_rate=0.1,
            stability_out=1,
            alacrity_out=0,
            resistance_out=0,
            aegis_out=0,
            superspeed_out=0,
            stealth_out=0,
        )
        with pytest.raises(ValidationError):
            row.agent_id = 999  # type: ignore[misc]
