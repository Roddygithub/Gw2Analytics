"""Tests for :mod:`gw2_core._scaffold` SCAFFOLD defaults.

These defaults provide safe zero / identity fallbacks for the
Phase 6 v2 side-table getter plumbing. The tests lock the
contract: every default returns the expected zero/identity value
and accepts the expected event type without raising.
"""

from __future__ import annotations

from gw2_core._scaffold import (
    default_barrier_portion_from_damage,
    default_barrier_portion_from_healing,
    default_dps_split,
    default_full_power_split,
    default_zero,
)
from gw2_core.models import DamageEvent, HealingEvent


def _damage_event(damage: int = 100) -> DamageEvent:
    return DamageEvent(
        time_ms=0,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=42,
        damage=damage,
    )


def _healing_event(healing: int = 100) -> HealingEvent:
    return HealingEvent(
        time_ms=0,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=43,
        healing=healing,
    )


def test_default_dps_split_returns_zero_zero() -> None:
    event = _damage_event(damage=1234)
    assert default_dps_split(event) == (0, 0)


def test_default_full_power_split_is_default_dps_split() -> None:
    event = _damage_event(damage=999)
    assert default_full_power_split(event) == default_dps_split(event)


def test_default_barrier_portion_from_damage_returns_zero() -> None:
    event = _damage_event(damage=500)
    assert default_barrier_portion_from_damage(event) == 0


def test_default_barrier_portion_from_healing_returns_zero() -> None:
    event = _healing_event(healing=500)
    assert default_barrier_portion_from_healing(event) == 0


def test_default_zero_returns_zero_for_any_event() -> None:
    assert default_zero(_damage_event()) == 0
    assert default_zero(_healing_event()) == 0
    assert default_zero("anything") == 0
    assert default_zero(None) == 0
