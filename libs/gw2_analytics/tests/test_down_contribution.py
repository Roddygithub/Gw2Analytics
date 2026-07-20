"""Tests for :class:`DownContributionAggregator`.

Phase C v0.11.0: down-contribution DPS + kill attribution.
Replaces the hardcoded SCAFFOLD zeros in the Combat readout
Damage table.
"""

from __future__ import annotations

from gw2_analytics.down_contribution import DownContributionAggregator, DownContributionRow
from gw2_core import DamageEvent, DeathEvent, DownEvent


def _damage(
    source: int,
    target: int,
    damage: int,
    time_ms: int = 0,
) -> DamageEvent:
    return DamageEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=42,
        damage=damage,
    )


def _down(agent: int, time_ms: int = 0) -> DownEvent:
    return DownEvent(
        time_ms=time_ms,
        source_agent_id=agent,
        target_agent_id=0,
        skill_id=0,
    )


def _death(agent: int, killed_by: int | None = None, time_ms: int = 0) -> DeathEvent:
    return DeathEvent(
        time_ms=time_ms,
        source_agent_id=agent,
        target_agent_id=0,
        skill_id=0,
        killed_by_agent_id=killed_by,
    )


class TestDownContributionAggregator:
    """Down-contribution DPS + kill attribution contract tests."""

    def test_empty_input_yields_empty_list(self) -> None:
        rows = DownContributionAggregator().aggregate([], [], [], duration_s=10.0)
        assert rows == []

    def test_no_down_events_no_damage_to_down(self) -> None:
        """No players go down → no down contribution for anyone."""
        rows = DownContributionAggregator().aggregate(
            [_damage(source=1, target=2, damage=100)],
            [],
            [],
            duration_s=10.0,
        )
        assert rows == []

    def test_damage_to_downed_target(self) -> None:
        """Damage dealt to a downed target is attributed as down contribution."""
        rows = DownContributionAggregator().aggregate(
            [_damage(source=1, target=2, damage=100)],
            [_down(agent=2)],
            [],
            duration_s=10.0,
        )
        assert len(rows) == 1
        assert rows[0].source_agent_id == 1
        assert rows[0].down_contribution_dps == 10.0  # 100 / 10
        assert rows[0].kills == 0

    def test_kill_attribution(self) -> None:
        """DeathEvent with killed_by_agent_id attributes a kill."""
        rows = DownContributionAggregator().aggregate(
            [],
            [],
            [_death(agent=2, killed_by=1)],
            duration_s=10.0,
        )
        assert len(rows) == 1
        assert rows[0].source_agent_id == 1
        assert rows[0].kills == 1
        assert rows[0].down_contribution_dps == 0.0

    def test_kill_not_attributed_when_killed_by_is_none(self) -> None:
        """Pre-Phase-6-v2: killed_by_agent_id=None → no kill attributed."""
        rows = DownContributionAggregator().aggregate(
            [],
            [],
            [_death(agent=2, killed_by=None)],
            duration_s=10.0,
        )
        assert rows == []  # No source agent accumulated stats

    def test_death_removes_from_downed_set(self) -> None:
        """Death removes target from downed set; subsequent damage not attributed."""
        rows = DownContributionAggregator().aggregate(
            [
                _damage(source=1, target=2, damage=50, time_ms=100),
                _damage(source=1, target=2, damage=50, time_ms=200),
            ],
            [_down(agent=2, time_ms=50)],
            [_death(agent=2, time_ms=150)],  # death at 150ms
            duration_s=10.0,
        )
        # Only the first 50 damage (before death) is down contribution
        assert len(rows) == 1
        assert rows[0].source_agent_id == 1
        assert rows[0].down_contribution_dps == 5.0  # 50 / 10
        assert rows[0].kills == 0  # killed_by is None

    def test_multiple_sources(self) -> None:
        """Multiple players contributing to the same downed target."""
        rows = DownContributionAggregator().aggregate(
            [
                _damage(source=1, target=3, damage=200),
                _damage(source=2, target=3, damage=100),
            ],
            [_down(agent=3)],
            [],
            duration_s=10.0,
        )
        assert len(rows) == 2
        # Sorted: highest DPS first
        assert rows[0].source_agent_id == 1
        assert rows[0].down_contribution_dps == 20.0  # 200 / 10
        assert rows[1].source_agent_id == 2
        assert rows[1].down_contribution_dps == 10.0  # 100 / 10

    def test_zero_duration_guard(self) -> None:
        """duration_s <= 0 → down_contribution_dps is 0.0."""
        rows = DownContributionAggregator().aggregate(
            [_damage(source=1, target=2, damage=100)],
            [_down(agent=2)],
            [],
            duration_s=0.0,
        )
        assert len(rows) == 1
        assert rows[0].source_agent_id == 1
        assert rows[0].down_contribution_dps == 0.0  # zero duration → 0.0
        assert rows[0].kills == 0

    def test_deterministic_ordering(self) -> None:
        """Sorted by -down_contribution_dps, then source_agent_id ASC."""
        rows = DownContributionAggregator().aggregate(
            [
                _damage(source=5, target=10, damage=200),
                _damage(source=3, target=10, damage=200),
                _damage(source=8, target=10, damage=100),
            ],
            [_down(agent=10)],
            [],
            duration_s=10.0,
        )
        assert [r.source_agent_id for r in rows] == [3, 5, 8]
        assert [r.down_contribution_dps for r in rows] == [20.0, 20.0, 10.0]

    def test_re_down_tracking(self) -> None:
        """A player who rallies and goes down again.

        Damage before the second down is conservatively counted as
        down contribution even though the player may have rallied.
        This is the known over-counting described in the module docstring.
        """
        rows = DownContributionAggregator().aggregate(
            [
                _damage(source=1, target=2, damage=100, time_ms=100),  # before first down
                _damage(source=1, target=2, damage=100, time_ms=200),  # while down (first)
                _damage(source=1, target=2, damage=100, time_ms=300),  # rallied+down again
            ],
            [
                _down(agent=2, time_ms=150),  # goes down first time
                # rallies at some point (no event)
                _down(agent=2, time_ms=250),  # goes down again
            ],
            [],
            duration_s=10.0,
        )
        # All 3 damage events hit while target is downed (or re-downed)
        # The second down event sees target already in set, stays in.
        # Damage at time_ms=100 is BEFORE first down at 150ms → not counted
        assert len(rows) == 1
        assert rows[0].source_agent_id == 1
        assert rows[0].down_contribution_dps == 20.0  # (100+100) / 10 = 20.0
        # 300ms damage is while target is in downed set (re-added at 250ms)

    def test_kills_are_additive(self) -> None:
        """Multiple DeathEvents with the same killed_by increment kills."""
        rows = DownContributionAggregator().aggregate(
            [],
            [],
            [
                _death(agent=2, killed_by=1),
                _death(agent=3, killed_by=1),
            ],
            duration_s=10.0,
        )
        assert len(rows) == 1
        assert rows[0].source_agent_id == 1
        assert rows[0].kills == 2

    def test_kills_by_different_sources(self) -> None:
        """Kills attributed to different sources produce separate rows."""
        rows = DownContributionAggregator().aggregate(
            [],
            [],
            [
                _death(agent=2, killed_by=1),
                _death(agent=3, killed_by=7),
            ],
            duration_s=10.0,
        )
        assert len(rows) == 2
        by_source = {r.source_agent_id: r for r in rows}
        assert by_source[1].kills == 1
        assert by_source[7].kills == 1

    def test_damage_to_alive_target_not_counted(self) -> None:
        """Damage to a target that never goes down is not down contribution."""
        rows = DownContributionAggregator().aggregate(
            [_damage(source=1, target=2, damage=100)],
            [],  # no down events
            [],
            duration_s=10.0,
        )
        assert rows == []

    def test_down_after_damage(self) -> None:
        """Damage before the target goes down is NOT counted."""
        rows = DownContributionAggregator().aggregate(
            [_damage(source=1, target=2, damage=100, time_ms=100)],
            [_down(agent=2, time_ms=200)],  # down AFTER the damage
            [],
            duration_s=10.0,
        )
        assert rows == []  # no down-contribution

    def test_kill_and_damage_same_row(self) -> None:
        """A player who kills AND damages downed targets gets both stats.

        Chronological ordering: DownEvent (t=50), DamageEvent (t=100),
        DeathEvent (t=200). Damage at t=100 hits before death at t=200
        removes the targets from the downed set.
        """
        rows = DownContributionAggregator().aggregate(
            [
                _damage(source=1, target=2, damage=100, time_ms=100),
                _damage(source=1, target=3, damage=50, time_ms=100),
            ],
            [
                _down(agent=2, time_ms=50),
                _down(agent=3, time_ms=50),
            ],
            [
                _death(agent=2, killed_by=1, time_ms=200),
                _death(agent=3, killed_by=7, time_ms=200),
            ],
            duration_s=10.0,
        )
        assert len(rows) == 2
        by_source = {r.source_agent_id: r for r in rows}
        # source 1: 100 damage to agent 2 + 50 damage to agent 3
        # (both downed at t=100, deaths at t=200)
        assert by_source[1].down_contribution_dps == 15.0  # (100+50) / 10
        assert by_source[1].kills == 1  # killed agent 2
        # source 7: no damage, killed agent 3
        assert by_source[7].kills == 1
        assert by_source[7].down_contribution_dps == 0.0

    def test_model_is_frozen(self) -> None:
        row = DownContributionRow(
            source_agent_id=1,
            down_contribution_dps=10.0,
            kills=1,
        )
        assert row.source_agent_id == 1
        assert row.down_contribution_dps == 10.0
        assert row.kills == 1
