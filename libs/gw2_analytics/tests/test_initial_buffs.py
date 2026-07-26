from gw2_analytics.initial_buffs import extract_initial_buffs
from gw2_core import BuffApplyEvent


def test_extract_initial_buffs_filters_and_normalizes_time() -> None:
    events = [
        BuffApplyEvent(
            time_ms=42_000_001,
            source_agent_id=1,
            target_agent_id=7,
            skill_id=57051,
            duration_ms=3_578_044,
            stacks=1,
        ),
        BuffApplyEvent(
            time_ms=42_000_001,
            source_agent_id=1,
            target_agent_id=7,
            skill_id=743,
            duration_ms=4_000,
            stacks=1,
        ),
    ]

    assert [buff.model_dump() for buff in extract_initial_buffs(events, 42_000_000, {57051})] == [
        {
            "agent_id": 7,
            "skill_id": 57051,
            "time_ms": 1,
            "duration_ms": 3_578_044,
            "stacks": 1,
        }
    ]
