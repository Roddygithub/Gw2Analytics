"""Hermetic tests for gw2_core._buff_ids buff/effect ID classification.

Verifies the well-known GW2 boon, damage-condition, and control-condition
buff IDs against the ``classify_buff`` and ``is_condition`` predicates.
"""

from __future__ import annotations

import pytest

from gw2_core.models import (
    _BOON_IDS,
    _CONDITION_CONTROL_IDS,
    _CONDITION_DAMAGE_IDS,
    BUFF_CATEGORY_MAP,
    BuffCategory,
    classify_buff,
    is_condition,
)


class TestClassifyBuff:
    """Unit tests for :func:`classify_buff`."""

    # -- Boons --
    @pytest.mark.parametrize(
        ("buff_id", "name"),
        [
            (740, "Might"),
            (725, "Fury"),
            (717, "Protection"),
            (718, "Regeneration"),
            (719, "Swiftness"),
            (726, "Vigor"),
            (743, "Aegis"),
            (1122, "Alacrity"),
            (1187, "Quickness"),
            (873, "Resistance"),
            (5974, "Stability"),
            (30336, "Superspeed"),
            (13017, "Stealth"),
            (26980, "Resolution"),
        ],
    )
    def test_classify_boon(self, buff_id: int, name: str) -> None:
        """Well-known boon IDs classify as BOON."""
        assert classify_buff(buff_id) == BuffCategory.BOON, (
            f"{name} ({buff_id}) should be BOON"
        )

    # -- Damage conditions --
    @pytest.mark.parametrize(
        ("buff_id", "name"),
        [
            (736, "Bleeding"),
            (737, "Burning"),
            (721, "Poison"),
            (722, "Confusion"),
            (723, "Torment"),
        ],
    )
    def test_classify_damage_condition(self, buff_id: int, name: str) -> None:
        """Well-known damage condition IDs classify as CONDITION_DAMAGE."""
        assert classify_buff(buff_id) == BuffCategory.CONDITION_DAMAGE, (
            f"{name} ({buff_id}) should be CONDITION_DAMAGE"
        )

    # -- Control conditions --
    @pytest.mark.parametrize(
        ("buff_id", "name"),
        [
            (727, "Chilled"),
            (728, "Blind"),
            (730, "Weakness"),
            (731, "Vulnerability"),
            (732, "Crippled"),
            (733, "Fear"),
            (734, "Taunt"),
            (735, "Slow"),
            (742, "Immobilize"),
        ],
    )
    def test_classify_control_condition(self, buff_id: int, name: str) -> None:
        """Well-known control condition IDs classify as CONDITION_CONTROL."""
        assert classify_buff(buff_id) == BuffCategory.CONDITION_CONTROL, (
            f"{name} ({buff_id}) should be CONDITION_CONTROL"
        )

    def test_unknown_buff_returns_none(self) -> None:
        """An unrecognized buff ID returns None."""
        assert classify_buff(999_999) is None
        assert classify_buff(0) is None
        assert classify_buff(-1) is None

    def test_all_known_ids_are_mapped(self) -> None:
        """Every ID in BUFF_CATEGORY_MAP returns a non-None category."""
        for buff_id in BUFF_CATEGORY_MAP:
            assert classify_buff(buff_id) is not None, (
                f"buff_id {buff_id} has no category but is in BUFF_CATEGORY_MAP"
            )


class TestIsCondition:
    """Unit tests for :func:`is_condition`."""

    def test_boons_are_not_conditions(self) -> None:
        """Might (740) and other boons are NOT conditions."""
        assert not is_condition(740)
        assert not is_condition(725)
        assert not is_condition(1187)

    def test_damage_conditions_are_conditions(self) -> None:
        """Bleeding (736) is a condition."""
        assert is_condition(736)
        assert is_condition(737)
        assert is_condition(723)

    def test_control_conditions_are_conditions(self) -> None:
        """Chilled (727) is a condition."""
        assert is_condition(727)
        assert is_condition(733)
        assert is_condition(742)

    def test_unknown_is_not_condition(self) -> None:
        """Unknown buff IDs are NOT classified as conditions."""
        assert not is_condition(999_999)
        assert not is_condition(0)


class TestBuffCategoryMap:
    """Sanity checks on the BUFF_CATEGORY_MAP construction."""

    def test_no_overlap_between_categories(self) -> None:
        """No buff ID appears in more than one category."""
        assert not (_BOON_IDS & _CONDITION_DAMAGE_IDS), "boon ∩ damage condition"
        assert not (_BOON_IDS & _CONDITION_CONTROL_IDS), "boon ∩ control condition"
        assert not (
            _CONDITION_DAMAGE_IDS & _CONDITION_CONTROL_IDS
        ), "damage ∩ control condition"

    def test_total_count_matches_known_sets(self) -> None:
        """The BUFF_CATEGORY_MAP has exactly |boons|+|damage|+|control| entries."""
        expected = len(_BOON_IDS) + len(_CONDITION_DAMAGE_IDS) + len(_CONDITION_CONTROL_IDS)
        assert len(BUFF_CATEGORY_MAP) == expected, (
            f"BUFF_CATEGORY_MAP has {len(BUFF_CATEGORY_MAP)} entries, "
            f"expected {expected}"
        )

    def test_total_count_at_least_twenty_eight(self) -> None:
        """Sanity: we have at least 14 boons + 5 damage + 9 control = 28 entries."""
        assert len(BUFF_CATEGORY_MAP) >= 28, (
            f"Expected at least 28 known buff IDs, got {len(BUFF_CATEGORY_MAP)}"
        )
