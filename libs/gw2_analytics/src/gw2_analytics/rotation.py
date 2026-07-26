"""Build EI-style skill casts from raw EVTC activation and instant-cast signals."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from gw2_core import (
    ActivationType,
    BoonApplyEvent,
    EffectEvent,
    Event,
    SkillActivationEvent,
    WeaponSwapEvent,
)

_WEAPON_DRAW = 23284
_INSTANT_CASTS_BY_BUFF = {
    29446: (30792, True),  # Reaper's Shroud, immediately before its weapon swap
    30129: (29958, False),  # Infusing Terror
}
_INSTANT_CASTS_BY_EFFECT = {
    "C4E8DD3234E0C647993857940ED79AC1": 29560,  # Spiteful Spirit
}


class SkillCast(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_agent_id: int
    skill_id: int
    time_ms: int
    duration_ms: int


def build_skill_rotation(  # noqa: PLR0912
    events: Iterable[Event],
    duration_ms: int,
    start_time_ms: int | None = None,
) -> list[SkillCast]:
    """Return completed, clipped casts ordered by fight-relative start time."""
    event_list = list(events)
    if not event_list:
        return []
    origin = start_time_ms if start_time_ms is not None else min(e.time_ms for e in event_list)
    swaps = [e for e in event_list if isinstance(e, WeaponSwapEvent)]
    active: dict[tuple[int, int], SkillActivationEvent] = {}
    casts: list[SkillCast] = []

    for event in event_list:
        if isinstance(event, SkillActivationEvent):
            key = (event.source_agent_id, event.skill_id)
            if event.activation in (ActivationType.NORMAL, ActivationType.QUICKNESS):
                if event.skill_id != _WEAPON_DRAW:
                    active[key] = event
            elif start := active.pop(key, None):
                casts.append(
                    SkillCast(
                        source_agent_id=event.source_agent_id,
                        skill_id=event.skill_id,
                        time_ms=start.time_ms - origin,
                        duration_ms=event.time_ms - start.time_ms,
                    )
                )
        elif isinstance(event, WeaponSwapEvent):
            casts.append(
                SkillCast(
                    source_agent_id=event.source_agent_id,
                    skill_id=-2,
                    time_ms=event.time_ms - origin,
                    duration_ms=0,
                )
            )
        elif isinstance(event, BoonApplyEvent) and event.kind == "apply":
            instant = _INSTANT_CASTS_BY_BUFF.get(event.skill_id)
            if instant is not None:
                skill_id, before_swap = instant
                time_ms = event.time_ms
                if before_swap and any(
                    swap.source_agent_id == event.target_agent_id
                    and abs(swap.time_ms - event.time_ms) < 5
                    for swap in swaps
                ):
                    time_ms -= 1
                casts.append(
                    SkillCast(
                        source_agent_id=event.target_agent_id,
                        skill_id=skill_id,
                        time_ms=time_ms - origin,
                        duration_ms=0,
                    )
                )
        elif isinstance(event, EffectEvent):
            effect_skill_id = _INSTANT_CASTS_BY_EFFECT.get(event.guid)
            if effect_skill_id is not None:
                casts.append(
                    SkillCast(
                        source_agent_id=event.source_agent_id,
                        skill_id=effect_skill_id,
                        time_ms=event.time_ms - origin,
                        duration_ms=0,
                    )
                )

    for start in active.values():
        casts.append(
            SkillCast(
                source_agent_id=start.source_agent_id,
                skill_id=start.skill_id,
                time_ms=start.time_ms - origin,
                duration_ms=max(0, duration_ms - (start.time_ms - origin)),
            )
        )
    return sorted(casts, key=lambda cast: cast.time_ms)


__all__ = ["SkillCast", "build_skill_rotation"]
