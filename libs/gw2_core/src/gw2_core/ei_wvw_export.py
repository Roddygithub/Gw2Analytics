"""Strict product contract for the first WvW Elite Insights export."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class _ExportModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class WvwExportActor(_ExportModel):
    actor_id: str = Field(min_length=1)
    kind: Literal["player", "npc", "gadget", "unknown"]
    name: str | None
    account: str | None
    subgroup: int | None = Field(ge=0)
    profession: str | None
    elite_spec: str | None
    instance_id: int | None = Field(ge=0)
    species_id: int | None = Field(ge=0)
    first_aware_ms: int = Field(ge=0)
    last_aware_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def awareness_is_ordered(self) -> WvwExportActor:
        if self.last_aware_ms < self.first_aware_ms:
            raise ValueError("last_aware_ms must be >= first_aware_ms")
        return self


class WvwEventBase(_ExportModel):
    sequence: int = Field(ge=0)
    time_ms: int = Field(ge=0)


class WvwDamageEvent(WvwEventBase):
    kind: Literal["damage"]
    source_actor_id: str | None
    target_actor_id: str | None
    skill_id: int
    damage: int = Field(ge=0)
    shield_damage: int = Field(ge=0)


class WvwBuffApplyEvent(WvwEventBase):
    kind: Literal["buff_apply"]
    source_actor_id: str | None
    target_actor_id: str | None
    buff_id: int
    duration_ms: int = Field(ge=0)


class WvwBuffExtensionEvent(WvwEventBase):
    kind: Literal["buff_extension"]
    source_actor_id: str | None
    target_actor_id: str | None
    buff_id: int
    duration_ms: int = Field(ge=0)


class _WvwBuffRemovalEvent(WvwEventBase):
    source_actor_id: str | None
    target_actor_id: str | None
    buff_id: int
    duration_ms: int = Field(ge=0)
    removed_stacks: int = Field(ge=0)


class WvwBuffRemoveAllEvent(_WvwBuffRemovalEvent):
    kind: Literal["buff_remove_all"]


class WvwBuffRemoveSingleEvent(_WvwBuffRemovalEvent):
    kind: Literal["buff_remove_single"]


class WvwBuffRemoveManualEvent(_WvwBuffRemovalEvent):
    kind: Literal["buff_remove_manual"]


class _WvwLifecycleEvent(WvwEventBase):
    target_actor_id: str | None


class WvwDownEvent(_WvwLifecycleEvent):
    kind: Literal["down"]


class WvwDeathEvent(_WvwLifecycleEvent):
    kind: Literal["death"]


class WvwAliveEvent(_WvwLifecycleEvent):
    kind: Literal["alive"]


class WvwSpawnEvent(_WvwLifecycleEvent):
    kind: Literal["spawn"]


class WvwDespawnEvent(_WvwLifecycleEvent):
    kind: Literal["despawn"]


class WvwHealthUpdateEvent(_WvwLifecycleEvent):
    kind: Literal["health_update"]
    health_percent: FiniteFloat = Field(ge=0, le=100)


type WvwExportEvent = Annotated[
    WvwDamageEvent
    | WvwBuffApplyEvent
    | WvwBuffExtensionEvent
    | WvwBuffRemoveAllEvent
    | WvwBuffRemoveSingleEvent
    | WvwBuffRemoveManualEvent
    | WvwDownEvent
    | WvwDeathEvent
    | WvwAliveEvent
    | WvwSpawnEvent
    | WvwDespawnEvent
    | WvwHealthUpdateEvent,
    Field(discriminator="kind"),
]


class WvwOwnershipInterval(_ExportModel):
    agent_id: str = Field(min_length=1)
    owner_actor_id: str | None
    owner_resolution: Literal["resolved", "unresolved"]
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    start_basis: Literal["master_observation"]
    end_basis: Literal["master_observation", "agent_awareness"]

    @model_validator(mode="after")
    def interval_is_consistent(self) -> WvwOwnershipInterval:
        if self.end_ms <= self.start_ms:
            raise ValueError("ownership interval must satisfy start_ms < end_ms")
        if (self.owner_actor_id is None) != (self.owner_resolution == "unresolved"):
            raise ValueError("owner_actor_id and owner_resolution disagree")
        return self


class WvwPositionSample(_ExportModel):
    actor_id: str = Field(min_length=1)
    time_ms: int = Field(ge=0)
    x: FiniteFloat
    y: FiniteFloat
    z: FiniteFloat


class WvwExportFight(_ExportModel):
    fight_id: str = Field(min_length=1)
    source_log_index: int = Field(ge=0)
    segment_index: int = Field(ge=0)
    started_at: datetime | None
    duration_ms: int = Field(gt=0)
    build: int | None = Field(default=None, ge=0)
    outcome: Literal["success", "failure", "unknown"]
    actors: list[WvwExportActor]
    events: list[WvwExportEvent]
    ownership_intervals: list[WvwOwnershipInterval]
    ownership_observation_count: int = Field(ge=0)
    ownership_same_time_collision_count: int = Field(ge=0)
    position_samples: list[WvwPositionSample]

    @model_validator(mode="after")
    def references_and_order_are_valid(self) -> WvwExportFight:  # noqa: PLR0912
        actor_by_id = {actor.actor_id: actor for actor in self.actors}
        if len(actor_by_id) != len(self.actors):
            raise ValueError("actor_id values must be unique within a fight")
        if self.started_at is not None and self.started_at.utcoffset() is None:
            raise ValueError("started_at must include a UTC offset")
        for actor in self.actors:
            if actor.last_aware_ms > self.duration_ms:
                raise ValueError("actor awareness exceeds fight duration_ms")
        if self.events != sorted(self.events, key=lambda event: (event.time_ms, event.sequence)):
            raise ValueError("events must be ordered by time_ms then sequence")
        if [event.sequence for event in self.events] != list(range(len(self.events))):
            raise ValueError("event sequence must be contiguous from zero")
        if self.ownership_observation_count < len(self.ownership_intervals):
            raise ValueError("ownership observations cannot be fewer than generated intervals")
        if self.ownership_same_time_collision_count > self.ownership_observation_count:
            raise ValueError("same-time collisions cannot exceed ownership observations")
        for event in self.events:
            for actor_id in _event_actor_ids(event):
                if actor_id is not None and actor_id not in actor_by_id:
                    raise ValueError(f"event references unknown actor_id {actor_id!r}")
            if event.time_ms > self.duration_ms:
                raise ValueError("event time_ms exceeds fight duration_ms")
        expected_positions = sorted(
            self.position_samples,
            key=lambda sample: (sample.time_ms, sample.actor_id, sample.x, sample.y, sample.z),
        )
        if self.position_samples != expected_positions:
            raise ValueError("position_samples must be ordered by time, actor, x, y, z")
        for sample in self.position_samples:
            position_actor = actor_by_id.get(sample.actor_id)
            if position_actor is None:
                raise ValueError(f"position sample references unknown actor_id {sample.actor_id!r}")
            if sample.time_ms > self.duration_ms:
                raise ValueError("position sample time_ms exceeds fight duration_ms")
        for interval in self.ownership_intervals:
            agent = actor_by_id.get(interval.agent_id)
            if agent is None:
                raise ValueError(
                    f"ownership interval references unknown agent_id {interval.agent_id!r}"
                )
            if interval.end_ms > self.duration_ms:
                raise ValueError("ownership interval end_ms exceeds fight duration_ms")
            if interval.start_ms < agent.first_aware_ms or interval.end_ms > agent.last_aware_ms:
                raise ValueError("ownership interval exceeds agent awareness")
            if interval.owner_actor_id is not None:
                owner = actor_by_id.get(interval.owner_actor_id)
                if owner is None:
                    raise ValueError(
                        f"ownership interval references unknown owner_actor_id "
                        f"{interval.owner_actor_id!r}"
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
        return self


def _event_actor_ids(event: WvwExportEvent) -> tuple[str | None, ...]:
    match event:
        case WvwDamageEvent() | WvwBuffApplyEvent() | WvwBuffExtensionEvent():
            return event.source_actor_id, event.target_actor_id
        case WvwBuffRemoveAllEvent() | WvwBuffRemoveSingleEvent() | WvwBuffRemoveManualEvent():
            return event.source_actor_id, event.target_actor_id
        case _:
            return (event.target_actor_id,)


class WvwExportV1(_ExportModel):
    schema_version: Literal[1]
    parser_version: str = Field(min_length=1)
    source_commit: str | None
    config_sha256: str | None
    session_id: str | None
    source_log_count: int = Field(ge=1)
    fights: list[WvwExportFight] = Field(min_length=1)

    @model_validator(mode="after")
    def fight_ids_are_unique_and_indexed(self) -> WvwExportV1:
        ids = [fight.fight_id for fight in self.fights]
        if len(set(ids)) != len(ids):
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
