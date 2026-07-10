"""Hermetic tests for condi_power_split (v0.10.5 plan 135).

The 3 plan-spec tests (new-build / old-build condi / unknown-skill)
+ 3 add-on edge cases (zero getter, capped condi, non-digit build code).
Pattern model: ``libs/gw2_analytics/tests/test_role_detection_voe_specs.py``.
"""

from __future__ import annotations

from gw2_analytics.condi_power_split import (
    KNOWN_CONDI_NAMES,
    split_condi_power,
)
from gw2_core import DamageEvent


def _skill_lookup(table: dict[int, str]):
    def get(skill_id: int) -> str | None:
        return table.get(skill_id)

    return get


def _no_condi(_event: DamageEvent) -> int:
    """Default getter returning 0 (old-build or no condi data available)."""
    return 0


def test_new_build_condi_extracted_from_condi_getter() -> None:
    """Plan 135 spec test 1: new build (`>= 20240501`) extracts condi from the
    ``condi_portion_getter`` callback (which the caller wires to the
    parser's buff_dmg side table)."""
    event = DamageEvent(
        time_ms=1500,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=42,
        damage=1000,
    )
    # Per-event getter closure: returns 300 for the specific event.
    condi_table = {(1_500, 1, 2, 42, 1_000): 300}

    def condi_getter(e: DamageEvent) -> int:
        return condi_table.get(
            (e.time_ms, e.source_agent_id, e.target_agent_id, e.skill_id, e.damage), 0
        )

    condi, power = split_condi_power(
        [event],
        build_date="20250925",
        skill_name_getter=_skill_lookup({42: "Bleeding"}),
        condi_portion_getter=condi_getter,
    )
    assert condi == 300
    assert power == 700


def test_old_build_skill_name_branch_is_all_condi() -> None:
    """Plan 135 spec test 2: old build, skill in KNOWN_CONDI_NAMES => all condi."""
    event = DamageEvent(
        time_ms=1500,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=42,
        damage=1000,
    )
    condi, power = split_condi_power(
        [event],
        build_date="20231101",
        skill_name_getter=_skill_lookup({42: "Burning"}),
        condi_portion_getter=_no_condi,  # unused on old build
    )
    assert condi == 1000
    assert power == 0


def test_old_build_unknown_skill_falls_back_to_power() -> None:
    """Plan 135 spec test 3: old build, skill not in lookup => power."""
    event = DamageEvent(
        time_ms=1500,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=9999,
        damage=1000,
    )
    condi, power = split_condi_power(
        [event],
        build_date="20231101",
        skill_name_getter=_skill_lookup({}),
        condi_portion_getter=_no_condi,
    )
    assert condi == 0
    assert power == 1000


def test_new_build_without_condi_portion_getter_returns_power_only() -> None:
    """Add-on: new build but no getter wired => entire hit attributed to power.
    Graceful degrade; the caller can opt-in to the condi split by passing
    the callback."""
    event = DamageEvent(
        time_ms=1500,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=42,
        damage=1000,
    )
    condi, power = split_condi_power(
        [event],
        build_date="20250925",
        skill_name_getter=_skill_lookup({42: "Bleeding"}),
        # condi_portion_getter deliberately omitted
    )
    assert condi == 0
    assert power == 1000


def test_new_build_condi_capped_at_damage() -> None:
    """Add-on: buff_dmg > damage should NOT inflate condi beyond the hit itself."""
    event = DamageEvent(
        time_ms=1500,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=42,
        damage=1000,
    )
    condi, power = split_condi_power(
        [event],
        build_date="20250925",
        skill_name_getter=_skill_lookup({42: "Bleeding"}),
        condi_portion_getter=lambda _e: 999_999,  # over-the-top value
    )
    assert condi == 1000  # capped at damage
    assert power == 0  # power = damage - condi = 0


def test_non_digit_build_string_falls_through_to_old_build() -> None:
    """Add-on: arcdps beta builds sometimes emit non-numeric build codes;
    the splitter silently routes them through the old-build branch."""
    event = DamageEvent(
        time_ms=1500,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=42,
        damage=1000,
    )
    condi, power = split_condi_power(
        [event],
        build_date="2024-05-01-beta",  # non-digit => old-build branch
        skill_name_getter=_skill_lookup({42: "Burning"}),
        condi_portion_getter=_no_condi,
    )
    assert condi == 1000
    assert power == 0


def test_known_condi_names_frozenset_stable() -> None:
    """The frozenset is exported as KNOWN_CONDI_NAMES; verify membership."""
    assert "Bleeding" in KNOWN_CONDI_NAMES
    assert "Burning" in KNOWN_CONDI_NAMES
    assert "Confusion" in KNOWN_CONDI_NAMES
    assert "Poisoned" in KNOWN_CONDI_NAMES
    assert "Torment" in KNOWN_CONDI_NAMES
    assert "Fury" not in KNOWN_CONDI_NAMES  # boon, NOT a condition
    assert "Regeneration" not in KNOWN_CONDI_NAMES  # boon, NOT a condition
    assert len(KNOWN_CONDI_NAMES) == 5


def test_zero_damage_events_attribute_to_neither_bucket() -> None:
    """Add-on: empty stream + zero-magnitude hits => (0, 0)."""
    condi, power = split_condi_power(
        [],
        build_date="20250925",
        skill_name_getter=_skill_lookup({}),
        condi_portion_getter=_no_condi,
    )
    assert condi == 0
    assert power == 0
