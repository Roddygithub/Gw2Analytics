"""Initial buff snapshots, including food and utility consumables."""

from __future__ import annotations

from collections.abc import Iterable, Set

from pydantic import BaseModel, ConfigDict

from gw2_core import BoonApplyEvent, BuffApplyEvent, Event


class InitialBuff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: int
    skill_id: int
    time_ms: int
    duration_ms: int
    stacks: int


def extract_initial_buffs(
    events: Iterable[Event],
    start_time_ms: int,
    skill_ids: Set[int] | None = None,
) -> list[InitialBuff]:
    """Return initial snapshots, optionally restricted to known buff IDs."""
    return [
        InitialBuff(
            agent_id=event.target_agent_id,
            skill_id=event.skill_id,
            time_ms=event.time_ms - start_time_ms,
            duration_ms=event.duration_ms,
            stacks=event.stacks,
        )
        for event in events
        if (
            (isinstance(event, BuffApplyEvent) and event.initial)
            or (isinstance(event, BoonApplyEvent) and event.kind == "apply")
        )
        and (skill_ids is None or event.skill_id in skill_ids)
    ]


__all__ = ["InitialBuff", "extract_initial_buffs"]
