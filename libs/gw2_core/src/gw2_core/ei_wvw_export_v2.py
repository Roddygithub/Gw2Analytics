"""Strict V2 contract for the pinned WvW Elite Insights export."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gw2_core.ei_wvw_export import (
    WvwBuffApplyEvent,
    WvwBuffExtensionEvent,
    WvwBuffRemoveAllEvent,
    WvwBuffRemoveManualEvent,
    WvwBuffRemoveSingleEvent,
    WvwDamageEvent,
    WvwDeathEvent,
    WvwDespawnEvent,
    WvwDownEvent,
    WvwHealthUpdateEvent,
    WvwOwnershipInterval,
    WvwPositionSample,
    WvwSpawnEvent,
)


class _V2Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class WvwV2Actor(_V2Model):
    actor_id: str = Field(min_length=1)
    kind: Literal["player", "npc", "gadget", "unknown"]
    name: str | None
    account: str | None
    subgroup: int | None = Field(ge=0)
    profession: str | None
    elite_spec: str | None
    species_id: int | None = Field(ge=0)
    first_aware_ms: int = Field(ge=0)
    last_aware_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def awareness_is_ordered(self) -> WvwV2Actor:
        if self.last_aware_ms < self.first_aware_ms:
            raise ValueError("last_aware_ms must be >= first_aware_ms")
        return self


class WvwV2HealingEvent(_V2Model):
    sequence: int = Field(ge=0)
    kind: Literal["healing"]
    time_ms: int = Field(ge=0)
    source_actor_id: str | None
    target_actor_id: str | None
    skill_id: int
    amount: int = Field(ge=0)


class WvwV2UpEvent(_V2Model):
    sequence: int = Field(ge=0)
    kind: Literal["up"]
    time_ms: int = Field(ge=0)
    actor_id: str | None


class WvwV2CCEvent(_V2Model):
    sequence: int = Field(ge=0)
    kind: Literal["cc"]
    time_ms: int = Field(ge=0)
    source_actor_id: str | None
    target_actor_id: str | None
    skill_id: int
    duration_ms: int = Field(ge=0)


type WvwV2Event = Annotated[
    WvwDamageEvent
    | WvwBuffApplyEvent
    | WvwBuffExtensionEvent
    | WvwBuffRemoveAllEvent
    | WvwBuffRemoveSingleEvent
    | WvwBuffRemoveManualEvent
    | WvwDownEvent
    | WvwDeathEvent
    | WvwSpawnEvent
    | WvwDespawnEvent
    | WvwHealthUpdateEvent
    | WvwV2HealingEvent
    | WvwV2UpEvent
    | WvwV2CCEvent,
    Field(discriminator="kind"),
]


class WvwV2Fight(_V2Model):
    fight_id: str = Field(min_length=1)
    source_log_index: int = Field(ge=0)
    segment_index: int = Field(ge=0)
    started_at: datetime | None
    duration_ms: int = Field(gt=0)
    recording_end_ms: int = Field(gt=0)
    event_domain_end_ms: int = Field(gt=0)
    healing_available: bool
    build: int | None = Field(default=None, ge=0)
    outcome: Literal["success", "failure", "unknown"]
    actors: list[WvwV2Actor]
    events: list[WvwV2Event]
    ownership_intervals: list[WvwOwnershipInterval]
    ownership_observation_count: int = Field(ge=0)
    ownership_same_time_collision_count: int = Field(ge=0)
    position_samples: list[WvwPositionSample]

    @model_validator(mode="after")
    def temporal_bounds_are_ordered(self) -> WvwV2Fight:
        if self.event_domain_end_ms < self.duration_ms:
            raise ValueError("event_domain_end_ms must cover the active fight duration")
        if self.recording_end_ms < self.duration_ms:
            raise ValueError("recording_end_ms must cover the active fight duration")
        if self.event_domain_end_ms < self.recording_end_ms:
            raise ValueError("event_domain_end_ms must cover recording_end_ms")
        latest_event_ms = max((event.time_ms for event in self.events), default=0)
        if self.event_domain_end_ms != max(self.recording_end_ms, latest_event_ms):
            raise ValueError(
                "event_domain_end_ms must be the maximum of recording_end_ms and the "
                "latest exported event timestamp"
            )
        return self

    @model_validator(mode="after")
    def domain_and_references_are_valid(self) -> WvwV2Fight:  # noqa: PLR0912
        actor_by_id = {actor.actor_id: actor for actor in self.actors}
        if len(actor_by_id) != len(self.actors):
            raise ValueError("actor_id values must be unique within a fight")
        if self.started_at is not None and self.started_at.utcoffset() is None:
            raise ValueError("started_at must include a UTC offset")
        for actor in self.actors:
            if actor.last_aware_ms > self.recording_end_ms:
                raise ValueError("actor awareness exceeds recording_end_ms")
        if self.events != sorted(self.events, key=lambda event: (event.time_ms, event.sequence)):
            raise ValueError("events must be ordered by time_ms then sequence")
        if [event.sequence for event in self.events] != list(range(len(self.events))):
            raise ValueError("event sequence must be contiguous from zero")
        if self.ownership_observation_count < len(self.ownership_intervals):
            raise ValueError("ownership observations cannot be fewer than generated intervals")
        if self.ownership_same_time_collision_count > self.ownership_observation_count:
            raise ValueError("same-time collisions cannot exceed ownership observations")
        for event in self.events:
            if event.time_ms > self.event_domain_end_ms:
                raise ValueError("event time_ms exceeds event_domain_end_ms")
            refs = _event_actor_ids(event)
            for actor_id in refs:
                if actor_id is not None and actor_id not in actor_by_id:
                    raise ValueError(f"event references unknown actor_id {actor_id!r}")
        expected_positions = sorted(
            self.position_samples,
            key=lambda sample: (sample.time_ms, sample.actor_id, sample.x, sample.y, sample.z),
        )
        if self.position_samples != expected_positions:
            raise ValueError("position_samples must be ordered by time, actor, x, y, z")
        for sample in self.position_samples:
            if sample.actor_id not in actor_by_id:
                raise ValueError(f"position sample references unknown actor_id {sample.actor_id!r}")
            if sample.time_ms > self.recording_end_ms:
                raise ValueError("position sample exceeds recording_end_ms")
            if not all(map(math.isfinite, (sample.x, sample.y, sample.z))):
                raise ValueError("position coordinates must be finite")
        for interval in self.ownership_intervals:
            agent = actor_by_id.get(interval.agent_id)
            if agent is None:
                raise ValueError(
                    f"ownership interval references unknown agent_id {interval.agent_id!r}"
                )
            if interval.end_ms > self.recording_end_ms:
                raise ValueError("ownership interval exceeds recording_end_ms")
            if interval.start_ms < agent.first_aware_ms or interval.end_ms > agent.last_aware_ms:
                raise ValueError("ownership interval exceeds agent awareness")
            owner_id = interval.owner_actor_id
            if owner_id is not None:
                owner = actor_by_id.get(owner_id)
                if owner is None:
                    raise ValueError(
                        f"ownership interval references unknown owner_actor_id {owner_id!r}"
                    )
                if not owner.first_aware_ms <= interval.start_ms <= owner.last_aware_ms:
                    raise ValueError("observed owner is not aware at ownership start_ms")
        if self.ownership_intervals != sorted(
            self.ownership_intervals,
            key=lambda interval: (
                interval.agent_id,
                interval.start_ms,
                interval.owner_actor_id or "",
            ),
        ):
            raise ValueError("ownership_intervals must be ordered by agent, start, then owner")
        if not self.healing_available and any(event.kind == "healing" for event in self.events):
            raise ValueError("healing events require healing_available=true")
        return self


class WvwExportV2(_V2Model):
    schema_version: Literal[2]
    parser_version: str = Field(min_length=1)
    source_commit: str | None
    config_sha256: str | None
    session_id: str | None
    source_log_count: int = Field(gt=0)
    fights: list[WvwV2Fight] = Field(min_length=1)

    @model_validator(mode="after")
    def fight_ids_are_unique_and_indexed(self) -> WvwExportV2:
        ids = [fight.fight_id for fight in self.fights]
        if len(ids) != len(set(ids)):
            raise ValueError("fight_id values must be unique within an export")
        for fight in self.fights:
            if fight.source_log_index >= self.source_log_count:
                raise ValueError("source_log_index is outside source_log_count")
            expected_id = f"log-{fight.source_log_index:04d}/fight-{fight.segment_index:04d}"
            if fight.fight_id != expected_id:
                raise ValueError(f"fight_id must be {expected_id!r}")
        if self.fights != sorted(
            self.fights,
            key=lambda fight: (fight.source_log_index, fight.segment_index),
        ):
            raise ValueError("fights must be ordered by source_log_index then segment_index")
        return self


def _event_actor_ids(event: WvwV2Event) -> tuple[str | None, ...]:
    match event:
        case WvwV2HealingEvent(source_actor_id=source, target_actor_id=target):
            return (source, target)
        case WvwV2CCEvent(source_actor_id=source, target_actor_id=target):
            return (source, target)
        case WvwV2UpEvent(actor_id=actor):
            return (actor,)
        case _:
            values = ("source_actor_id", "target_actor_id")
            refs = tuple(getattr(event, key, None) for key in values)
            if getattr(event, "kind", None) in {
                "down",
                "death",
                "spawn",
                "despawn",
                "health_update",
            }:
                return (getattr(event, "target_actor_id", None),)
            return refs


__all__ = [
    "WvwExportV2",
    "WvwV2Actor",
    "WvwV2CCEvent",
    "WvwV2Event",
    "WvwV2Fight",
    "WvwV2HealingEvent",
    "WvwV2UpEvent",
]
