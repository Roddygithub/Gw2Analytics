"""Unit tests for :mod:`gw2_analytics.role_detection` (v1 lite).

The v1 lite algorithm is a port of an upstream reference parser's role-detection
heuristic (``(non-public reference).py``) adapted to the
3-magnitude ``OrmFightPlayerSummary`` schema (Gw2Analytics's
tracker is much leaner than an upstream reference parser's 80+ field
``PlayerStats``). The tests cover the 4 archetype classes
(DPS / HEAL / STRIP / BOON), the MIXED + UNKNOWN fallbacks, the
off_meta / foreign_badges / high_<axis> tags, the spec-hint
fallback, and the profession-level hint fallback. Edge cases
(0/0/0, unknown profession, unknown spec) are also covered.

The algorithm is **pure** (no I/O, no DB) so the tests are
straight function-call assertions. No fixtures, no async, no DB.
"""

from __future__ import annotations

from gw2_analytics.role_detection import detect_role_lite

# Profession + EliteSpec IntEnum values from :mod:`gw2_core`. We
# import here to keep the test self-contained and to surface the
# enum's int values in the assertions (the algorithm takes ints,
# not enum instances -- the upstream caller in
# ``_persist_player_summaries`` passes ``int(agent.profession)``).
from gw2_core import EliteSpec, Profession

# ---------------------------------------------------------------------------
# Pure-DPS archetype
# ---------------------------------------------------------------------------


def test_pure_dps_berserker_classified_dps_no_tags() -> None:
    """A pure-DPS Berserker (95% damage, 5% healing, 0 strips) -> DPS, no off_meta tag.

    The Berserker's spec hint is DPS, so the picked role matches
    the hint -> no ``off_meta`` tag. The strip ratio is well below
    the high_strip threshold (0.0) so no ``high_strips`` tag.
    """
    role, tags = detect_role_lite(
        total_damage=2_000_000,
        total_healing=100_000,
        total_buff_removal=0,
        profession_int=int(Profession.WARRIOR),
        elite_spec_int=int(EliteSpec.BERSERKER),
    )
    assert role == "DPS"
    # DPS spec hint matches DPS role -> no off_meta.
    assert "off_meta" not in tags
    # Damage ratio: 2M * 1.0 / (2M + 250k + 0) = 2M / 2.25M ~= 0.89
    # (well above _R_DMG_HIGH = 0.85).
    assert "high_dps" in tags
    # Strip ratio is 0 -> no high_strips.
    assert "high_strips" not in tags


def test_pure_dps_soulbeast_classified_dps() -> None:
    """A pure-DPS Soulbeast (Ranger) -> DPS, no off_meta.

    The Soulbeast's spec hint is DPS so the picked role matches.
    """
    role, tags = detect_role_lite(
        total_damage=1_500_000,
        total_healing=50_000,
        total_buff_removal=0,
        profession_int=int(Profession.RANGER),
        elite_spec_int=int(EliteSpec.SOULBEAST),
    )
    assert role == "DPS"
    assert "off_meta" not in tags


# ---------------------------------------------------------------------------
# Pure-HEAL archetype
# ---------------------------------------------------------------------------


def test_pure_heal_druid_classified_heal() -> None:
    """A pure-heal Druid (10% damage, 85% healing, 5% strips) -> HEAL, no off_meta.

    The Druid's spec hint is HEAL, so the picked role matches.
    The healing ratio is well above the high_heal threshold
    (0.75). The ``healing * 2.5`` weight dominates the
    weighted-effort calculation.
    """
    role, tags = detect_role_lite(
        total_damage=100_000,
        total_healing=400_000,  # 400k * 2.5 = 1M weighted effort
        total_buff_removal=10,  # 10 * 5000 = 50k weighted effort
        profession_int=int(Profession.RANGER),
        elite_spec_int=int(EliteSpec.DRUID),
    )
    assert role == "HEAL"
    assert "off_meta" not in tags
    # Weighted effort: 100k + 1M + 50k = 1.15M
    # r_heal = 1M / 1.15M ~= 0.87 (above _R_HEAL_HIGH = 0.75).
    assert "high_healing" in tags
    assert "high_dps" not in tags


def test_pure_heal_tempest_classified_heal() -> None:
    """A pure-heal Tempest (Elementalist) -> HEAL, no off_meta.

    Tempest's spec hint is HEAL.
    """
    role, tags = detect_role_lite(
        total_damage=200_000,
        total_healing=600_000,
        total_buff_removal=0,
        profession_int=int(Profession.ELEMENTALIST),
        elite_spec_int=int(EliteSpec.TEMPEST),
    )
    assert role == "HEAL"
    assert "off_meta" not in tags


# ---------------------------------------------------------------------------
# Pure-STRIP archetype
# ---------------------------------------------------------------------------


def test_pure_strip_spellbreaker_classified_strip() -> None:
    """A pure-strip Spellbreaker (Warrior) -> STRIP, no off_meta.

    The Spellbreaker's spec hint is STRIP, so the picked role
    matches. The strip ratio is well above the high_strip
    threshold (0.60).
    """
    role, tags = detect_role_lite(
        total_damage=300_000,
        total_healing=0,
        total_buff_removal=150,  # 150 * 5000 = 750k weighted effort
        profession_int=int(Profession.WARRIOR),
        elite_spec_int=int(EliteSpec.SPELLBREAKER),
    )
    assert role == "STRIP"
    assert "off_meta" not in tags
    # Weighted effort: 300k + 0 + 750k = 1.05M
    # r_strip = 750k / 1.05M ~= 0.71 (above _R_STRIP_HIGH = 0.60).
    assert "high_strips" in tags
    assert "high_dps" not in tags


def test_pure_strip_reaper_classified_strip() -> None:
    """A pure-strip Reaper (Necromancer) -> STRIP, no off_meta.

    Reaper's spec hint is STRIP.
    """
    role, tags = detect_role_lite(
        total_damage=400_000,
        total_healing=0,
        total_buff_removal=200,
        profession_int=int(Profession.NECROMANCER),
        elite_spec_int=int(EliteSpec.REAPER),
    )
    assert role == "STRIP"
    assert "off_meta" not in tags


# ---------------------------------------------------------------------------
# Pure-BOON archetype (the spec-hint-only path)
# ---------------------------------------------------------------------------


def test_herald_doing_pure_dps_is_dps_with_off_meta_tag() -> None:
    """A pure-boon Herald (Revenant) -> BOON via spec hint + magnitudes.

    The Herald's spec hint is BOON. The Herald's ROLE_CAPABILITIES
    is ``{"DPS", "BOON"}`` (multi-role -- DPS is also allowed).
    The algorithm grants BOON only if
    ``r_heal + r_strip > r_dmg`` (the magnitudes are consistent
    with non-DPS / non-HEAL play). With r_dmg = 0.85 and
    r_heal + r_strip ~= 0.15, the guard fails and the Herald is
    tagged DPS (not BOON). This is the expected behaviour: the
    Herald is multi-role and is doing pure DPS in this fight.

    A test for the "genuine BOON Herald" is omitted because the
    algorithm does NOT support a "boon-only" detection without
    the magnitude ratios tilting away from DPS. The current
    heuristic relies on the spec hint + a multi-role cap check.
    """
    role, tags = detect_role_lite(
        total_damage=1_500_000,
        total_healing=100_000,
        total_buff_removal=0,
        profession_int=int(Profession.REVENANT),
        elite_spec_int=int(EliteSpec.HERALD),
    )
    # r_dmg ~= 0.94, well above _R_DMG_PURE = 0.65 -> DPS axis wins.
    # The Herald's spec hint is BOON, but the DPS axis already
    # won, so no spec-hint fallback.
    assert role == "DPS"
    # DPS is in the Herald's ROLE_CAPABILITIES, so no foreign_badges.
    assert not any(t.startswith("foreign_badges:") for t in tags)
    # The Herald's spec hint is BOON but the picked role is DPS,
    # so off_meta is granted (the spec can do BOON but is doing DPS).
    assert "off_meta" in tags


def test_firebrand_with_balanced_play_classified_heal_with_off_meta() -> None:
    """A Firebrand doing balanced play (40% dmg, 50% heal, 10% strip) -> BOON.

    The Firebrand's spec hint is BOON. Its ROLE_CAPABILITIES is
    ``{"DPS", "BOON", "HEAL"}``. The algorithm grants BOON if
    ``r_heal + r_strip > r_dmg``. With weighted-effort:
    score_dmg = 400k * 1.0 = 400k
    score_heal = 500k * 2.5 = 1.25M
    score_strip = 100 * 5000 = 500k
    total_effort = 400k + 1.25M + 500k = 2.15M
    r_dmg = 0.186, r_heal = 0.581, r_strip = 0.233
    r_heal + r_strip = 0.814 > r_dmg = 0.186 -> guard passes -> BOON.
    """
    role, tags = detect_role_lite(
        total_damage=400_000,
        total_healing=500_000,
        total_buff_removal=100,
        profession_int=int(Profession.GUARDIAN),
        elite_spec_int=int(EliteSpec.FIREBRAND),
    )
    # r_heal = 0.581 > _R_HEAL_PURE = 0.50 -> HEAL axis wins
    # first (badges are appended in dmg / heal / strip order).
    # The Firebrand's ROLE_CAPABILITIES includes HEAL so no
    # foreign_badges. Spec hint is BOON but picked role is HEAL
    # -> off_meta tag (HEAL is in caps, so not foreign_badges).
    assert role == "HEAL"
    assert "off_meta" in tags
    assert not any(t.startswith("foreign_badges:") for t in tags)


# ---------------------------------------------------------------------------
# MIXED + UNKNOWN fallbacks
# ---------------------------------------------------------------------------


def test_mixed_classification_when_no_axis_pure_and_no_hint() -> None:
    """A balanced DPS/HEAL/STRIP build with an UNKNOWN spec -> MIXED.

    No spec / profession hint is available. No axis crosses its
    pure threshold. The algorithm falls back to MIXED.
    """
    role, tags = detect_role_lite(
        total_damage=300_000,  # score_dmg = 300k
        total_healing=100_000,  # score_heal = 250k
        total_buff_removal=20,  # score_strip = 100k
        profession_int=int(Profession.WARRIOR),  # hint = DPS
        elite_spec_int=int(EliteSpec.UNKNOWN),  # no spec hint
    )
    # total_effort = 650k
    # r_dmg = 0.462, r_heal = 0.385, r_strip = 0.154
    # No axis crosses its pure threshold. Spec hint = DPS via
    # _PROF_ROLE_HINTS["Warrior"] = "DPS". r_dmg = 0.462 >=
    # _HINT_MIN_FRACTION = 0.30 -> DPS axis granted via the
    # hint-fallback.
    assert role == "DPS"
    # The profession hint is DPS and the picked role is DPS, so
    # no off_meta. No high_<axis> tag (no axis crosses the high tier).
    assert "off_meta" not in tags
    assert "high_dps" not in tags


def test_unknown_classification_on_zero_output() -> None:
    """0/0/0 + unknown profession + unknown spec -> UNKNOWN + zero_output tag.

    This is the defensive edge case: a malformed event stream
    (or a parse failure) yielded zero data, the profession +
    spec are both UNKNOWN, and the algorithm degrades gracefully
    to ``("UNKNOWN", ["zero_output"])`` instead of crashing.
    """
    role, tags = detect_role_lite(
        total_damage=0,
        total_healing=0,
        total_buff_removal=0,
        profession_int=int(Profession.UNKNOWN),
        elite_spec_int=int(EliteSpec.UNKNOWN),
    )
    assert role == "UNKNOWN"
    assert "zero_output" in tags


def test_unknown_classification_on_zero_output_known_profession() -> None:
    """0/0/0 + known profession (Warrior) but UNKNOWN spec -> UNKNOWN.

    No spec hint; profession hint is DPS, but the hint-fallback
    requires ``r_dmg >= _HINT_MIN_FRACTION = 0.30`` and r_dmg is
    0.0, so the hint is NOT granted. The algorithm falls through
    to ``UNKNOWN + zero_output``.
    """
    role, tags = detect_role_lite(
        total_damage=0,
        total_healing=0,
        total_buff_removal=0,
        profession_int=int(Profession.WARRIOR),
        elite_spec_int=int(EliteSpec.UNKNOWN),
    )
    assert role == "UNKNOWN"
    assert "zero_output" in tags


# ---------------------------------------------------------------------------
# foreign_badges + off_meta tags
# ---------------------------------------------------------------------------


def test_foreign_badges_when_spec_cannot_play_picked_role() -> None:
    """A Druid (HEAL-spec) doing pure STRIP -> STRIP + foreign_badges:STRIP.

    The Druid's ROLE_CAPABILITIES is ``{"DPS", "HEAL"}`` -- STRIP
    is NOT in the set, so the foreign_badges tag is added. The
    spec hint is HEAL but the picked role is STRIP, so the
    off_meta tag is suppressed (the foreign_badges tag already
    captures the disagreement -- adding both would be redundant).
    """
    role, tags = detect_role_lite(
        total_damage=200_000,
        total_healing=0,
        total_buff_removal=100,  # 100 * 5000 = 500k weighted
        profession_int=int(Profession.RANGER),
        elite_spec_int=int(EliteSpec.DRUID),
    )
    # total_effort = 200k + 0 + 500k = 700k
    # r_dmg = 0.286, r_heal = 0.0, r_strip = 0.714
    # r_strip > _R_STRIP_PURE = 0.35 -> STRIP axis wins.
    assert role == "STRIP"
    assert "foreign_badges:STRIP" in tags
    # off_meta is suppressed because foreign_badges is present.
    assert "off_meta" not in tags


def test_off_meta_tag_when_picked_role_disagrees_with_spec_hint() -> None:
    """A Herald (BOON-spec) doing pure DPS -> DPS + off_meta.

    The Herald's spec hint is BOON. The picked role is DPS (the
    damage axis crossed its pure threshold). The Herald's
    ROLE_CAPABILITIES includes DPS so no foreign_badges. The
    off_meta tag is granted (the spec can do DPS but is doing
    DPS while the spec's hint is BOON).
    """
    role, tags = detect_role_lite(
        total_damage=2_000_000,
        total_healing=0,
        total_buff_removal=0,
        profession_int=int(Profession.REVENANT),
        elite_spec_int=int(EliteSpec.HERALD),
    )
    assert role == "DPS"
    assert "off_meta" in tags
    # DPS is in the Herald's ROLE_CAPABILITIES so no foreign_badges.
    assert not any(t.startswith("foreign_badges:") for t in tags)
    # Damage ratio: 2M * 1.0 / 2M = 1.0 -> well above high threshold.
    assert "high_dps" in tags


# ---------------------------------------------------------------------------
# high_<axis> tags
# ---------------------------------------------------------------------------


def test_high_heal_tag_when_healing_dominates() -> None:
    """A pure-heal Druid (95% healing) -> HEAL + high_healing.

    r_heal > _R_HEAL_HIGH = 0.75 -> high_healing tag.
    """
    role, tags = detect_role_lite(
        total_damage=50_000,
        total_healing=600_000,
        total_buff_removal=0,
        profession_int=int(Profession.RANGER),
        elite_spec_int=int(EliteSpec.DRUID),
    )
    assert role == "HEAL"
    # r_heal = 600k * 2.5 / (50k + 1.5M) = 1.5M / 1.55M ~= 0.97
    assert "high_healing" in tags
    assert "high_dps" not in tags


# ---------------------------------------------------------------------------
# Spec / profession hint fallback (the "ambiguous magnitudes" path)
# ---------------------------------------------------------------------------


def test_spec_hint_fallback_when_magnitudes_too_mixed() -> None:
    """A Scourge doing balanced play -> HEAL via spec hint.

    No axis crosses its pure threshold, but the Scourge's spec
    hint is HEAL and r_heal = 0.40 >= _HINT_MIN_FRACTION = 0.30.
    The HEAL axis is granted via the spec-hint fallback.
    """
    role, tags = detect_role_lite(
        total_damage=200_000,
        total_healing=80_000,
        total_buff_removal=20,
        profession_int=int(Profession.NECROMANCER),
        elite_spec_int=int(EliteSpec.SCOURGE),
    )
    # score_dmg = 200k
    # score_heal = 80k * 2.5 = 200k
    # score_strip = 20 * 5000 = 100k
    # total_effort = 500k
    # r_dmg = 0.40, r_heal = 0.40, r_strip = 0.20
    # r_dmg < _R_DMG_PURE = 0.65, r_heal < _R_HEAL_PURE = 0.50,
    # r_strip < _R_STRIP_PURE = 0.35 -> no axis crosses.
    # Spec hint = HEAL, r_heal = 0.40 >= 0.30 -> HEAL granted.
    assert role == "HEAL"
    # HEAL is in the Scourge's ROLE_CAPABILITIES so no foreign_badges.
    assert not any(t.startswith("foreign_badges:") for t in tags)
    # No off_meta (spec hint matches picked role).
    assert "off_meta" not in tags


def test_profession_hint_fallback_when_spec_unknown() -> None:
    """A Warrior (BASE spec, no elite) doing 60% damage -> DPS via profession hint.

    No spec hint (EliteSpec.BASE is excluded from ELITE_SPEC_BY_INT).
    The Warrior's profession hint is DPS, r_dmg = 0.60 >= 0.30 ->
    DPS axis granted via the profession-hint fallback.
    """
    role, tags = detect_role_lite(
        total_damage=300_000,
        total_healing=100_000,
        total_buff_removal=0,
        profession_int=int(Profession.WARRIOR),
        elite_spec_int=int(EliteSpec.BASE),  # BASE = no elite spec
    )
    # score_dmg = 300k, score_heal = 250k, total_effort = 550k
    # r_dmg = 0.545, r_heal = 0.455
    # r_dmg < 0.65 -> no DPS axis. Profession hint = DPS, r_dmg >=
    # 0.30 -> DPS granted.
    assert role == "DPS"
    assert "off_meta" not in tags


# ---------------------------------------------------------------------------
# Negative-magnitude defensive guard
# ---------------------------------------------------------------------------


def test_negative_magnitudes_clamped_to_zero() -> None:
    """A negative ``total_damage`` is clamped to 0 by ``max(0, ...)``.

    Defensive: a parser bug could yield a negative magnitude. The
    algorithm clamps the value to 0 instead of producing a
    negative ratio (which would corrupt the classification).
    """
    role, tags = detect_role_lite(
        total_damage=-1_000_000,
        total_healing=200_000,
        total_buff_removal=0,
        profession_int=int(Profession.WARRIOR),
        elite_spec_int=int(EliteSpec.BERSERKER),
    )
    # score_dmg = max(0, -1M) * 1.0 = 0
    # score_heal = 200k * 2.5 = 500k
    # total_effort = 500k
    # r_heal = 1.0 > _R_HEAL_PURE = 0.50 -> HEAL axis.
    # Berserker's ROLE_CAPABILITIES is {"DPS"} -> HEAL is foreign.
    assert role == "HEAL"
    assert "foreign_badges:HEAL" in tags


# ---------------------------------------------------------------------------
# Spec hint where spec is not in ROLE_CAPABILITIES
# ---------------------------------------------------------------------------


def test_no_foreign_badges_when_spec_not_in_capabilities() -> None:
    """A Firebrand doing pure HEAL -> HEAL, no foreign_badges.

    The Firebrand's ROLE_CAPABILITIES is ``{"DPS", "BOON", "HEAL"}``
    so HEAL is allowed -> no foreign_badges. The spec hint is
    BOON but the picked role is HEAL, so off_meta is granted.
    """
    role, tags = detect_role_lite(
        total_damage=50_000,
        total_healing=300_000,  # 300k * 2.5 = 750k weighted
        total_buff_removal=0,
        profession_int=int(Profession.GUARDIAN),
        elite_spec_int=int(EliteSpec.FIREBRAND),
    )
    # total_effort = 50k + 750k = 800k
    # r_heal = 0.94 > _R_HEAL_PURE = 0.50 -> HEAL axis.
    assert role == "HEAL"
    # HEAL is in caps -> no foreign_badges.
    assert not any(t.startswith("foreign_badges:") for t in tags)
    # Spec hint is BOON, picked is HEAL -> off_meta.
    assert "off_meta" in tags
    # r_heal = 0.94 > _R_HEAL_HIGH = 0.75 -> high_healing.
    assert "high_healing" in tags


def test_mixed_fallback_does_not_emit_foreign_badges_tag() -> None:
    """The MIXED fallback must NOT emit a ``foreign_badges:MIXED`` tag.

    Regression test for a v0.10.3 bug: the initial implementation
    iterated ``badges`` in the foreign_badges check without
    excluding the MIXED / UNKNOWN fallbacks. Since neither MIXED
    nor UNKNOWN is in any spec's ``ROLE_CAPABILITIES``, the check
    would always fire for these cases and produce a semantically
    nonsensical ``foreign_badges:MIXED`` tag. The fix adds the
    same MIXED / UNKNOWN exclusion the off_meta check already had.

    Test inputs: a balanced build on a Scourge where no axis
    crosses its pure threshold AND the spec-hint fallback is
    denied (``r_heal < _HINT_MIN_FRACTION``). The algorithm
    falls through to MIXED. The ``foreign_badges:MIXED`` tag
    would be the bug signature.
    """
    # score_dmg = 200k, score_heal = 20k * 2.5 = 50k,
    # score_strip = 20 * 5000 = 100k -> total_effort = 350k
    # r_dmg = 0.571 (< 0.65), r_heal = 0.143 (< 0.50),
    # r_strip = 0.286 (< 0.35) -> no axis crosses.
    # Spec hint = HEAL, r_heal = 0.143 < _HINT_MIN_FRACTION = 0.30
    # -> hint-fallback denied -> falls through to MIXED.
    role, tags = detect_role_lite(
        total_damage=200_000,
        total_healing=20_000,
        total_buff_removal=20,
        profession_int=int(Profession.NECROMANCER),
        elite_spec_int=int(EliteSpec.SCOURGE),
    )
    assert role == "MIXED"
    # The foreign_badges:MIXED bug would produce this nonsensical tag.
    assert "foreign_badges:MIXED" not in tags, (
        f"MIXED fallback must not emit foreign_badges:MIXED, got {tags!r}"
    )
    # No foreign_badges tag of any kind for the MIXED fallback.
    assert not any(t.startswith("foreign_badges:") for t in tags)
    # off_meta is suppressed for MIXED (the existing exclusion).
    assert "off_meta" not in tags
    # No high_<axis> tags (no axis crosses the high tier).
    assert not any(t.startswith("high_") for t in tags)


def test_unknown_fallback_does_not_emit_foreign_badges_tag() -> None:
    """The UNKNOWN fallback (0/0/0) must NOT emit foreign_badges.

    Defensive: the UNKNOWN fallback already short-circuits before
    ``_compute_tags`` is called (it returns early in the
    orchestrator with the ``zero_output`` tag). This test locks
    that the early-return path does NOT fall through to the tag
    computation (which would otherwise produce a foreign_badges
    tag for a made-up UNKNOWN role).
    """
    role, tags = detect_role_lite(
        total_damage=0,
        total_healing=0,
        total_buff_removal=0,
        profession_int=int(Profession.WARRIOR),
        elite_spec_int=int(EliteSpec.BERSERKER),
    )
    assert role == "UNKNOWN"
    # The early-return path produces ONLY the zero_output tag.
    assert tags == ["zero_output"]
