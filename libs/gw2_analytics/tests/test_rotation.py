from gw2_analytics.rotation import build_skill_rotation
from gw2_core import (
    ActivationType,
    BoonApplyEvent,
    DamageEvent,
    EffectEvent,
    HealingEvent,
    MissileEvent,
    Profession,
    SkillActivationEvent,
    SpawnEvent,
    WeaponSwapEvent,
)


def test_build_skill_rotation_pairs_and_infers_casts() -> None:
    origin = 42_000_000
    base = {"target_agent_id": 0, "source_agent_id": 7}
    events = [
        WeaponSwapEvent(
            time_ms=origin + 100,
            skill_id=0,
            swapped_from=3,
            swapped_to=5,
            **base,
        ),
        BoonApplyEvent(
            time_ms=origin + 100,
            source_agent_id=7,
            target_agent_id=7,
            skill_id=29446,
            duration_ms=0,
            stacks=1,
        ),
        EffectEvent(
            time_ms=origin + 100,
            skill_id=8553,
            guid="C4E8DD3234E0C647993857940ED79AC1",
            **base,
        ),
        HealingEvent(
            time_ms=origin + 150,
            skill_id=13980,
            healing=1_000,
            barrier=0,
            **base,
        ),
        SkillActivationEvent(
            time_ms=origin + 200,
            skill_id=123,
            activation=ActivationType.NORMAL,
            duration_ms=300,
            expected_duration_ms=300,
            **base,
        ),
        SkillActivationEvent(
            time_ms=origin + 500,
            skill_id=123,
            activation=ActivationType.RESET,
            duration_ms=300,
            expected_duration_ms=300,
            **base,
        ),
    ]

    assert [
        (cast.skill_id, cast.time_ms, cast.duration_ms)
        for cast in build_skill_rotation(events, duration_ms=1_000, start_time_ms=origin)
    ] == [
        (30792, 99, 0),
        (-2, 100, 0),
        (29560, 100, 0),
        (13980, 150, 0),
        (123, 200, 300),
    ]


def test_build_skill_rotation_infers_ei_instant_casts() -> None:
    origin = 42_000_000
    base = {"target_agent_id": 7, "source_agent_id": 7}
    events = [
        BoonApplyEvent(time_ms=origin + 10, skill_id=10198, duration_ms=1, stacks=1, **base),
        BoonApplyEvent(time_ms=origin + 20, skill_id=16553, duration_ms=1, stacks=1, **base),
        BoonApplyEvent(time_ms=origin + 30, skill_id=33162, duration_ms=1, stacks=1, **base),
        BoonApplyEvent(time_ms=origin + 31, skill_id=5586, duration_ms=1, stacks=1, **base),
        BoonApplyEvent(time_ms=origin + 32, skill_id=34778, duration_ms=1, stacks=1, **base),
        BoonApplyEvent(time_ms=origin + 33, skill_id=40052, duration_ms=1, stacks=1, **base),
        BoonApplyEvent(time_ms=origin + 34, skill_id=76351, duration_ms=1, stacks=1, **base),
        BoonApplyEvent(
            time_ms=origin + 40,
            skill_id=29446,
            duration_ms=0,
            stacks=1,
            kind="remove_all",
            **base,
        ),
        DamageEvent(time_ms=origin + 50, skill_id=29604, damage=1, **base),
        DamageEvent(time_ms=origin + 60, skill_id=45534, damage=1, **base),
        DamageEvent(time_ms=origin + 61, skill_id=46808, damage=1, **base),
        HealingEvent(time_ms=origin + 70, skill_id=13594, healing=1, barrier=0, **base),
        HealingEvent(time_ms=origin + 80, skill_id=14282, healing=1, barrier=0, **base),
        MissileEvent(time_ms=origin + 90, skill_id=29889, **base),
        EffectEvent(
            time_ms=origin + 100,
            skill_id=0,
            guid="95B52793B838524AB237EB9FED7834BF",
            **base,
        ),
        EffectEvent(
            time_ms=origin + 110,
            skill_id=0,
            guid="D7006AC247BBE74BA54E912188EF6B12",
            **base,
        ),
        EffectEvent(
            time_ms=origin + 120,
            skill_id=0,
            guid="AFC5D5C7DA63D64BAAD55F787205B64F",
            **base,
        ),
        EffectEvent(
            time_ms=origin + 130,
            skill_id=0,
            guid="734834E7EB7CD74EB129ACBCE5C64C1D",
            **base,
        ),
    ]

    assert [
        (cast.skill_id, cast.time_ms, cast.duration_ms)
        for cast in build_skill_rotation(events, duration_ms=1_000, start_time_ms=origin)
    ] == [
        (10197, 10, 0),
        (10199, 20, 0),
        (31129, 30, 0),
        (5493, 31, 0),
        (14412, 32, 0),
        (54870, 33, 0),
        (76351, 34, 0),
        (30961, 40, 0),
        (29604, 50, 0),
        (45534, 60, 0),
        (40813, 61, 0),
        (13594, 70, 0),
        (14282, 80, 0),
        (29889, 90, 0),
        (-22, 100, 0),
        (29786, 110, 0),
        (62813, 120, 0),
        (63095, 130, 0),
    ]


def test_build_skill_rotation_marks_french_ranger_pet_spawn() -> None:
    origin = 42_000_000
    events = [
        SpawnEvent(time_ms=origin + 10, source_agent_id=7, target_agent_id=99, skill_id=0),
    ]

    assert [
        (cast.skill_id, cast.time_ms, cast.duration_ms)
        for cast in build_skill_rotation(
            events,
            duration_ms=1_000,
            start_time_ms=origin,
            ranger_pet_agent_ids={99},
        )
    ] == [(-28, 10, 0)]


def test_build_skill_rotation_infers_engineer_kits_from_one_bundle_cast() -> None:
    origin = 42_000_000
    base = {"target_agent_id": 0, "source_agent_id": 7}
    events = [
        WeaponSwapEvent(
            time_ms=origin + 10,
            skill_id=0,
            swapped_from=3,
            swapped_to=2,
            **base,
        ),
        SkillActivationEvent(
            time_ms=origin + 20,
            skill_id=76493,
            activation=ActivationType.RESET,
            duration_ms=0,
            expected_duration_ms=0,
            **base,
        ),
        WeaponSwapEvent(
            time_ms=origin + 30,
            skill_id=0,
            swapped_from=3,
            swapped_to=2,
            **base,
        ),
        SkillActivationEvent(
            time_ms=origin + 40,
            skill_id=30371,
            activation=ActivationType.RESET,
            duration_ms=0,
            expected_duration_ms=0,
            **base,
        ),
    ]

    assert [
        (cast.skill_id, cast.time_ms, cast.duration_ms)
        for cast in build_skill_rotation(events, duration_ms=1_000, start_time_ms=origin)
    ] == [(5927, 9, 0), (-2, 10, 0), (30800, 29, 0), (-2, 30, 0)]


def _guardian_shout(origin: int, agent: int, boon: int, stacks: int, duration_ms: int) -> list:
    """One shout effect plus the self-applied boons that identify the skill."""
    return [
        EffectEvent(
            time_ms=origin + 100,
            source_agent_id=agent,
            target_agent_id=agent,
            skill_id=0,
            guid="122BA55CCDF2B643929F6C4A97226DC9",
            is_around_dst=True,
        ),
        *(
            BoonApplyEvent(
                time_ms=origin + 100,
                source_agent_id=agent,
                target_agent_id=agent,
                skill_id=boon,
                duration_ms=duration_ms,
                stacks=1,
            )
            for _ in range(stacks)
        ),
    ]


def test_guardian_shout_effect_splits_by_the_boons_it_applied() -> None:
    """One effect serves every guardian shout; the self-buff picks the skill.

    Five-plus stacks of stability is "Stand Your Ground!", a 20-to-40 second
    aegis is "Advance!". A shout that grants neither is one Elite Insights
    does not attribute, so nothing is emitted for it.
    """
    origin = 42_000_000
    guardians = {7: Profession.GUARDIAN}

    def casts(events: list) -> list[tuple[int, int]]:
        return [
            (cast.skill_id, cast.time_ms)
            for cast in build_skill_rotation(
                events, duration_ms=1_000, start_time_ms=origin, professions=guardians
            )
        ]

    assert casts(_guardian_shout(origin, 7, 1122, 5, 5_000)) == [(9153, 100)]
    assert casts(_guardian_shout(origin, 7, 743, 1, 24_000)) == [(9084, 100)]
    # Three stabilities is a different shout, and a two-second aegis is the
    # ordinary one every guardian shout grants -- neither is attributable.
    assert casts(_guardian_shout(origin, 7, 1122, 3, 5_000)) == []
    assert casts(_guardian_shout(origin, 7, 743, 1, 2_000)) == []


def test_guardian_shout_effect_ignores_other_professions() -> None:
    """Warriors emit the same effect and Elite Insights books nothing for them."""
    origin = 42_000_000
    events = _guardian_shout(origin, 7, 1122, 5, 5_000)

    assert (
        build_skill_rotation(
            events,
            duration_ms=1_000,
            start_time_ms=origin,
            professions={7: Profession.WARRIOR},
        )
        == []
    )


def test_cleansing_fire_needs_both_secondary_effects_on_the_same_target() -> None:
    """A by-dst finder matches its secondaries on the destination, not the source.

    The three effects are emitted by different sources, so keying the
    secondary check on the source would find nothing.
    """
    origin = 42_000_000

    def effect(guid: str, source: int, target: int) -> EffectEvent:
        return EffectEvent(
            time_ms=origin + 100,
            source_agent_id=source,
            target_agent_id=target,
            skill_id=0,
            guid=guid,
            is_around_dst=True,
        )

    primary = effect("BFFE3477ECFA26458D69E93EE76EFF6B", 11, 7)
    second = effect("61F5669F9FAC1F48B47635C9F3833CEF", 12, 7)
    third = effect("ABF2332D28C7D6449A5B822E5714ADA4", 13, 7)
    elementalists = {7: Profession.ELEMENTALIST}

    def casts(events: list) -> list[tuple[int, int]]:
        return [
            (cast.skill_id, cast.time_ms)
            for cast in build_skill_rotation(
                events, duration_ms=1_000, start_time_ms=origin, professions=elementalists
            )
        ]

    assert casts([primary, second, third]) == [(5535, 100)]
    assert casts([primary, second]) == []
    # The secondaries land on a different actor, so they identify nothing.
    assert casts([primary, effect("61F5669F9FAC1F48B47635C9F3833CEF", 12, 9), third]) == []


def test_familiar_cast_is_credited_to_the_owner_named_by_the_record() -> None:
    """Elite Insights books four Evoker familiar skills against the owner.

    The familiar keeps its own cast; the owner gains a separate instant one.
    """
    origin = 42_000_000
    events = [
        SkillActivationEvent(
            time_ms=origin + 100,
            source_agent_id=99,
            target_agent_id=0,
            skill_id=76803,
            activation=ActivationType.NORMAL,
            duration_ms=0,
            expected_duration_ms=0,
            src_master_instid=1234,
        ),
    ]

    def casts(**kwargs: object) -> list[tuple[int, int, int]]:
        return [
            (cast.source_agent_id, cast.skill_id, cast.time_ms)
            for cast in build_skill_rotation(
                events, duration_ms=1_000, start_time_ms=origin, **kwargs
            )
        ]

    assert casts(agent_id_by_instance={1234: 7}) == [
        (99, 76803, 100),  # the familiar's own cast, unchanged
        (7, 77370, 100),  # and the instant one credited to its owner
    ]

    # Without the instance lookup the owner cannot be named, so only the
    # familiar's own cast survives rather than being misattributed.
    assert casts() == [(99, 76803, 100)]
