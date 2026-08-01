from gw2_analytics.rotation import build_skill_rotation
from gw2_core import (
    ActivationType,
    BoonApplyEvent,
    DamageEvent,
    EffectEvent,
    HealingEvent,
    MissileEvent,
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
