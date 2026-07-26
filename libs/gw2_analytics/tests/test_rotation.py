from gw2_analytics.rotation import build_skill_rotation
from gw2_core import (
    ActivationType,
    BoonApplyEvent,
    EffectEvent,
    SkillActivationEvent,
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
        (123, 200, 300),
    ]
