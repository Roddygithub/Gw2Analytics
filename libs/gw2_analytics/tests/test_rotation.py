from typing import Any

from gw2_analytics.rotation import build_skill_rotation
from gw2_core import (
    ActivationType,
    BoonApplyEvent,
    BuffApplyEvent,
    DamageEvent,
    EffectEvent,
    EliteSpec,
    Event,
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
        BoonApplyEvent(time_ms=origin + 35, skill_id=44272, duration_ms=0, stacks=1, **base),
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
        EffectEvent(
            time_ms=origin + 140,
            skill_id=0,
            guid="BB5488951B60B546BB1BD5626DAE83E1",
            is_around_dst=True,
            **base,
        ),
        EffectEvent(
            time_ms=origin + 150,
            source_agent_id=8,
            target_agent_id=8,
            skill_id=0,
            guid="E1C1DD7F866B4149A1BADD216C9AA69D",
        ),
        EffectEvent(
            time_ms=origin + 151,
            source_agent_id=8,
            target_agent_id=8,
            skill_id=0,
            guid="DB22850AE209B34BBD11372F56D42D43",
        ),
    ]

    assert [
        (cast.skill_id, cast.time_ms, cast.duration_ms)
        for cast in build_skill_rotation(
            events,
            duration_ms=1_000,
            start_time_ms=origin,
            professions={7: Profession.THIEF},
            elite_specs={8: EliteSpec.MECHANIST},
        )
    ] == [
        (10197, 10, 0),
        (10199, 20, 0),
        (31129, 30, 0),
        (5493, 31, 0),
        (14412, 32, 0),
        (54870, 33, 0),
        (76351, 34, 0),
        (41858, 35, 0),
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
        (13062, 140, 0),
        (63111, 150, 0),
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


def test_engineer_kit_ignores_previous_kit_finisher_at_same_time() -> None:
    origin = 42_000_000
    base = {"target_agent_id": 0, "source_agent_id": 7}
    events = [
        WeaponSwapEvent(
            time_ms=origin + 10,
            skill_id=0,
            swapped_from=4,
            swapped_to=2,
            **base,
        ),
        SkillActivationEvent(
            time_ms=origin + 20,
            skill_id=5931,
            activation=ActivationType.MINIMUM,
            duration_ms=0,
            expected_duration_ms=0,
            **base,
        ),
        SkillActivationEvent(
            time_ms=origin + 20,
            skill_id=5936,
            activation=ActivationType.NORMAL,
            duration_ms=0,
            expected_duration_ms=0,
            **base,
        ),
    ]

    assert [
        (cast.skill_id, cast.time_ms, cast.duration_ms)
        for cast in build_skill_rotation(events, duration_ms=1_000, start_time_ms=origin)
    ] == [(5933, 9, 0), (-2, 10, 0), (5936, 20, 0)]


def test_hunker_down_uses_buff_source_when_turtle_spawn_owner_is_missing() -> None:
    origin = 42_000_000
    events = [
        BoonApplyEvent(
            time_ms=origin + 100,
            source_agent_id=7,
            target_agent_id=99,
            skill_id=59536,
            duration_ms=1_000,
            stacks=1,
        )
    ]

    assert [
        (cast.source_agent_id, cast.skill_id, cast.time_ms, cast.duration_ms)
        for cast in build_skill_rotation(
            events,
            duration_ms=1_000,
            start_time_ms=origin,
            siege_turtle_agent_ids={99},
        )
    ] == [(7, 65418, 100, 0)]


def test_smoke_cloud_books_full_duration_apply_to_smokescale() -> None:
    origin = 42_000_000
    events = [
        BoonApplyEvent(
            time_ms=origin + 100,
            source_agent_id=7,
            target_agent_id=99,
            skill_id=59536,
            duration_ms=1_000,
            stacks=1,
        )
    ]

    assert [
        (cast.source_agent_id, cast.skill_id, cast.time_ms, cast.duration_ms)
        for cast in build_skill_rotation(
            events,
            duration_ms=1_000,
            start_time_ms=origin,
            smokescale_agent_ids={99},
        )
    ] == [(7, 31568, 100, 0)]


def test_smoke_cloud_is_credited_to_spawn_owner() -> None:
    origin = 42_000_000
    events = [
        SpawnEvent(time_ms=origin + 10, source_agent_id=7, target_agent_id=99, skill_id=0),
        BoonApplyEvent(
            time_ms=origin + 100,
            source_agent_id=99,
            target_agent_id=99,
            skill_id=59536,
            duration_ms=1_000,
            stacks=1,
        ),
    ]

    assert [
        (cast.source_agent_id, cast.skill_id, cast.time_ms)
        for cast in build_skill_rotation(
            events,
            duration_ms=1_000,
            start_time_ms=origin,
            smokescale_agent_ids={99},
        )
    ] == [(7, 31568, 100)]


def test_smoke_cloud_skips_reapply_echo_from_env() -> None:
    origin = 42_000_000
    events = [
        BoonApplyEvent(
            time_ms=origin + 100,
            source_agent_id=7,
            target_agent_id=99,
            skill_id=59536,
            duration_ms=1_000,
            stacks=1,
        ),
        BoonApplyEvent(
            time_ms=origin + 1_100,
            source_agent_id=0,
            target_agent_id=99,
            skill_id=59536,
            duration_ms=0,
            stacks=1,
        ),
    ]

    assert [
        (cast.source_agent_id, cast.skill_id, cast.time_ms)
        for cast in build_skill_rotation(
            events,
            duration_ms=1_000,
            start_time_ms=origin,
            smokescale_agent_ids={99},
        )
    ] == [(7, 31568, 100)]


def test_fern_hound_regenerate_is_credited_to_spawn_owner() -> None:
    origin = 42_000_000
    events = [
        SpawnEvent(time_ms=origin + 10, source_agent_id=7, target_agent_id=99, skill_id=0),
        BoonApplyEvent(
            time_ms=origin + 100,
            source_agent_id=99,
            target_agent_id=99,
            skill_id=59536,
            duration_ms=1_000,
            stacks=1,
        ),
    ]

    assert [
        (cast.source_agent_id, cast.skill_id, cast.time_ms)
        for cast in build_skill_rotation(
            events,
            duration_ms=1_000,
            start_time_ms=origin,
            fern_hound_agent_ids={99},
        )
    ] == [(7, 12717, 100)]


def test_flash_spark_is_inferred_from_engineer_effect() -> None:
    origin = 42_000_000
    events = [
        EffectEvent(
            time_ms=origin + 100,
            source_agent_id=7,
            target_agent_id=7,
            skill_id=2257,
            guid="418A090D719AB44AAF1C4AD1473068C4",
            is_around_dst=True,
        )
    ]

    assert [
        (cast.source_agent_id, cast.skill_id, cast.time_ms, cast.duration_ms)
        for cast in build_skill_rotation(
            events,
            duration_ms=1_000,
            start_time_ms=origin,
            elite_specs={7: EliteSpec.HOLOSMITH},
        )
    ] == [(7, 43176, 100, 0)]


def test_mercy_is_inferred_from_effect() -> None:
    origin = 42_000_000
    events = [
        EffectEvent(
            time_ms=origin + 100,
            source_agent_id=7,
            target_agent_id=7,
            skill_id=43917,
            guid="B59FCEFCF1D5D84B9FDB17F11E9B52E6",
            is_around_dst=True,
        )
    ]

    assert [
        (cast.source_agent_id, cast.skill_id, cast.time_ms, cast.duration_ms)
        for cast in build_skill_rotation(events, duration_ms=1_000, start_time_ms=origin)
    ] == [(7, 41372, 100, 0)]


def _guardian_shout(
    origin: int, agent: int, boon: int, stacks: int, duration_ms: int
) -> list[Event]:
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

    def casts(events: list[Event]) -> list[tuple[int, int]]:
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

    def casts(events: list[Event]) -> list[tuple[int, int]]:
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

    def casts(**kwargs: Any) -> list[tuple[int, int, int]]:
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


def test_engineer_kit_table_covers_the_three_kits_added_from_the_api() -> None:
    """Bomb, Tool and Grenade kits were absent, so their swaps went unnamed.

    One bundle skill per kit is enough to identify the swap that preceded it.
    """
    origin = 42_000_000
    base = {"target_agent_id": 0, "source_agent_id": 7}
    events: list[Event] = []
    for offset, bundle_skill in enumerate((5842, 5905, 5806)):
        events.append(
            WeaponSwapEvent(
                time_ms=origin + offset * 100 + 10,
                skill_id=0,
                swapped_from=3,
                swapped_to=2,
                **base,
            )
        )
        events.append(
            SkillActivationEvent(
                time_ms=origin + offset * 100 + 20,
                skill_id=bundle_skill,
                activation=ActivationType.RESET,
                duration_ms=0,
                expected_duration_ms=0,
                **base,
            )
        )

    kits = [
        cast.skill_id
        for cast in build_skill_rotation(events, duration_ms=1_000, start_time_ms=origin)
        if cast.skill_id > 0
    ]
    assert kits == [5812, 5904, 6020]


def test_repeated_activation_start_closes_previous_cast() -> None:
    origin = 42_000_000
    base = {"source_agent_id": 7, "target_agent_id": 0, "skill_id": 30521}
    events = [
        SkillActivationEvent(
            time_ms=origin + 100,
            activation=ActivationType.NORMAL,
            duration_ms=1_200,
            expected_duration_ms=1_200,
            **base,
        ),
        SkillActivationEvent(
            time_ms=origin + 2_981,
            activation=ActivationType.NORMAL,
            duration_ms=1_200,
            expected_duration_ms=1_200,
            **base,
        ),
        SkillActivationEvent(
            time_ms=origin + 3_604,
            activation=ActivationType.NORMAL,
            duration_ms=1_200,
            expected_duration_ms=1_200,
            **base,
        ),
    ]

    assert [
        (cast.skill_id, cast.time_ms, cast.duration_ms)
        for cast in build_skill_rotation(events, duration_ms=5_000, start_time_ms=origin)
    ] == [(30521, 100, 1_200), (30521, 2_981, 633), (30521, 3_604, 1_200)]


def test_repeated_activation_start_ignores_previous_prefight_cast() -> None:
    origin = 42_000_000
    base = {"source_agent_id": 7, "target_agent_id": 0, "skill_id": 30521}
    events = [
        SkillActivationEvent(
            time_ms=origin - 296,
            activation=ActivationType.NORMAL,
            duration_ms=1_200,
            expected_duration_ms=1_200,
            **base,
        ),
        SkillActivationEvent(
            time_ms=origin + 56,
            activation=ActivationType.NORMAL,
            duration_ms=1_200,
            expected_duration_ms=1_200,
            **base,
        ),
    ]

    assert [
        (cast.skill_id, cast.time_ms, cast.duration_ms)
        for cast in build_skill_rotation(events, duration_ms=2_000, start_time_ms=origin)
    ] == [(30521, 56, 1_200)]


def test_flowing_resolve_is_synthesized_from_buff_end() -> None:
    origin = 42_000_000
    events = [
        BuffApplyEvent(
            time_ms=origin + 5,
            source_agent_id=7,
            target_agent_id=7,
            skill_id=62632,
            duration_ms=5_392,
            original_duration_ms=6_000,
            stacks=1,
            initial=True,
        )
    ]

    assert [
        (cast.skill_id, cast.time_ms, cast.duration_ms)
        for cast in build_skill_rotation(
            events,
            duration_ms=10_000,
            start_time_ms=origin,
            elite_specs={7: EliteSpec.WILLBENDER},
        )
    ] == [(62603, -435, 500)]


def test_gunsaber_mode_books_enter_and_exit_before_swap() -> None:
    origin = 42_000_000
    events = [
        WeaponSwapEvent(
            time_ms=origin + 100,
            source_agent_id=7,
            target_agent_id=0,
            skill_id=0,
            swapped_from=1,
            swapped_to=5,
        ),
        BoonApplyEvent(
            time_ms=origin + 101,
            source_agent_id=7,
            target_agent_id=7,
            skill_id=62769,
            duration_ms=0,
            stacks=1,
        ),
        WeaponSwapEvent(
            time_ms=origin + 500,
            source_agent_id=7,
            target_agent_id=0,
            skill_id=0,
            swapped_from=5,
            swapped_to=1,
        ),
        BoonApplyEvent(
            time_ms=origin + 501,
            source_agent_id=0,
            target_agent_id=7,
            skill_id=62769,
            duration_ms=0,
            stacks=1,
            kind="remove_all",
        ),
        BoonApplyEvent(
            time_ms=origin + 700,
            source_agent_id=0,
            target_agent_id=7,
            skill_id=62769,
            duration_ms=0,
            stacks=1,
            kind="remove_single",
        ),
    ]

    assert [
        (cast.skill_id, cast.time_ms)
        for cast in build_skill_rotation(events, duration_ms=1_000, start_time_ms=origin)
        if cast.skill_id in {62745, 62861}
    ] == [(62745, 99), (62861, 499)]


def test_buff_give_casts_are_deduplicated_per_source_skill() -> None:
    origin = 42_000_000
    events = [
        BoonApplyEvent(
            time_ms=origin + 101,
            source_agent_id=7,
            target_agent_id=7,
            skill_id=78624,
            duration_ms=5_000,
            stacks=1,
        ),
        BoonApplyEvent(
            time_ms=origin + 200,
            source_agent_id=7,
            target_agent_id=8,
            skill_id=70806,
            duration_ms=5_000,
            stacks=1,
        ),
        BoonApplyEvent(
            time_ms=origin + 300,
            source_agent_id=7,
            target_agent_id=8,
            skill_id=42428,
            duration_ms=8_000,
            stacks=1,
        ),
        BoonApplyEvent(
            time_ms=origin + 300,
            source_agent_id=7,
            target_agent_id=9,
            skill_id=42428,
            duration_ms=8_000,
            stacks=1,
        ),
    ]

    assert [
        (cast.skill_id, cast.time_ms)
        for cast in build_skill_rotation(events, duration_ms=1_000, start_time_ms=origin)
    ] == [(76752, 101), (70806, 200), (43532, 300)]


def test_post_july_sand_cascade_effect_is_deduplicated() -> None:
    origin = 42_000_000
    events = [
        EffectEvent(
            time_ms=origin + 100,
            source_agent_id=7,
            target_agent_id=8,
            skill_id=42756,
            guid="23613E6E374EC6429FE9A69CC893984D",
            is_around_dst=True,
        ),
        EffectEvent(
            time_ms=origin + 100,
            source_agent_id=7,
            target_agent_id=9,
            skill_id=42756,
            guid="23613E6E374EC6429FE9A69CC893984D",
            is_around_dst=True,
        ),
    ]

    assert [
        (cast.skill_id, cast.time_ms)
        for cast in build_skill_rotation(
            events,
            duration_ms=1_000,
            start_time_ms=origin,
            professions={7: Profession.NECROMANCER},
        )
    ] == [(43448, 100)]


def _shroud_loss(origin: int, offset: int, kind: str) -> BoonApplyEvent:
    return BoonApplyEvent(
        time_ms=origin + offset,
        source_agent_id=7,
        target_agent_id=7,
        skill_id=29446,
        duration_ms=0,
        stacks=1,
        kind=kind,
    )


def test_exit_reaper_shroud_needs_a_full_removal_and_lands_before_the_swap() -> None:
    """``BuffLossCastFinder`` is typed on the full-removal event.

    A partial strip of Reaper's Shroud is not a cast, and leaving shroud
    triggers a weapon swap the cast has to sit just ahead of.
    """
    origin = 42_000_000

    def casts(events: list[Event]) -> list[tuple[int, int]]:
        return [
            (cast.skill_id, cast.time_ms)
            for cast in build_skill_rotation(events, duration_ms=1_000, start_time_ms=origin)
            if cast.skill_id == 30961
        ]

    swap = WeaponSwapEvent(
        time_ms=origin + 502,
        source_agent_id=7,
        target_agent_id=0,
        skill_id=0,
        swapped_from=3,
        swapped_to=5,
    )

    assert casts([_shroud_loss(origin, 500, "remove_all"), swap]) == [(30961, 500)]
    assert casts([_shroud_loss(origin, 500, "remove_single")]) == []
    # The swap lands first, so the cast is pulled back to just before it
    # rather than left on its own timestamp.
    swap_first = swap.model_copy(update={"time_ms": origin + 499})
    assert casts([_shroud_loss(origin, 500, "remove_all"), swap_first]) == [(30961, 498)]


def _symbol(origin: int, offset: int, guid: str) -> EffectEvent:
    return EffectEvent(
        time_ms=origin + offset,
        source_agent_id=7,
        target_agent_id=7,
        skill_id=0,
        guid=guid,
    )


def _symbol_cast(origin: int, offset: int, activation: ActivationType) -> SkillActivationEvent:
    return SkillActivationEvent(
        time_ms=origin + offset,
        source_agent_id=7,
        target_agent_id=0,
        skill_id=9161,
        activation=activation,
        duration_ms=0,
        expected_duration_ms=0,
    )


def test_symbol_trait_is_not_booked_while_the_real_skill_is_being_cast() -> None:
    """The trait places the same symbol, so a cast window rules the proc out.

    The test is on the whole window rather than on a cast still open at that
    instant: an effect landing just after the cast ends belongs to it too.
    """
    origin = 42_000_000
    guid = "8321373FA14B2B4B8761CDC6EEADB161"

    def casts(events: list[Event]) -> list[int]:
        return [
            cast.time_ms
            for cast in build_skill_rotation(events, duration_ms=10_000, start_time_ms=origin)
            if cast.skill_id == 13684
        ]

    cast_window = [
        _symbol_cast(origin, 500, ActivationType.NORMAL),
        _symbol_cast(origin, 900, ActivationType.RESET),
    ]

    # Inside the window, and within a server delay of either end.
    assert casts([_symbol(origin, 700, guid), *cast_window]) == []
    assert casts([_symbol(origin, 492, guid), *cast_window]) == []
    assert casts([_symbol(origin, 908, guid), *cast_window]) == []
    # Clear of it on both sides, and with no cast of 9161 at all.
    assert casts([_symbol(origin, 400, guid), *cast_window]) == [400]
    assert casts([_symbol(origin, 700, guid)]) == [700]


def test_weaver_attunement_buff_is_not_booked_as_a_base_attunement() -> None:
    """A Weaver swaps dual attunements, which Elite Insights books separately.

    Reporting the base skill would be a cast the log never contained, so the
    buff is dropped for a Weaver rather than attributed to the wrong skill.
    """
    origin = 42_000_000
    fire_attunement = BoonApplyEvent(
        time_ms=origin + 100,
        source_agent_id=7,
        target_agent_id=7,
        skill_id=5585,
        duration_ms=0,
        stacks=1,
    )

    def casts(**kwargs: Any) -> list[int]:
        return [
            cast.skill_id
            for cast in build_skill_rotation(
                [fire_attunement], duration_ms=1_000, start_time_ms=origin, **kwargs
            )
        ]

    assert casts() == [5492]
    assert casts(elite_specs={7: EliteSpec.TEMPEST}) == [5492]
    assert casts(elite_specs={7: EliteSpec.WEAVER}) == []
