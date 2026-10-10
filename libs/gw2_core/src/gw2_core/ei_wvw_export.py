"""Strict product contract for the first WvW Elite Insights export."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class WvwExportEvent(_ExportModel):
    sequence: int = Field(ge=0)
    kind: Literal[
        "damage",
        "buff_apply",
        "buff_extension",
        "buff_remove_all",
        "buff_remove_single",
        "buff_remove_manual",
        "down",
        "death",
        "alive",
        "spawn",
        "despawn",
        "health_update",
    ]
    time_ms: int = Field(ge=0)
    source_actor_id: str | None
    target_actor_id: str | None
    skill_id: int | None = Field(ge=0)
    damage: int | None = Field(ge=0)
    shield_damage: int | None = Field(ge=0)
    buff_id: int | None = Field(ge=0)
    buff_duration_ms: int | None = Field(ge=0)
    removed_stacks: int | None = Field(ge=0)
    health_percent: float | None = Field(ge=0, le=100)

    @model_validator(mode="after")
    def event_payload_matches_kind(self) -> WvwExportEvent:
        if self.kind == "damage" and self.damage is None:
            raise ValueError("damage events require damage")
        if self.kind in {"buff_apply", "buff_extension"} and (
            self.buff_id is None or self.buff_duration_ms is None
        ):
            raise ValueError(f"{self.kind} events require buff_id and buff_duration_ms")
        if self.kind.startswith("buff_remove_") and (
            self.buff_id is None or self.buff_duration_ms is None
        ):
            raise ValueError("buff removal events require buff_id and buff_duration_ms")
        if self.kind == "buff_remove_all" and self.removed_stacks is None:
            raise ValueError("buff_remove_all events require removed_stacks")
        if self.kind == "health_update" and self.health_percent is None:
            raise ValueError("health_update events require health_percent")
        return self


class WvwOwnershipInterval(_ExportModel):
    agent_id: str = Field(min_length=1)
    owner_actor_id: str | None
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    boundary_basis: Literal["master_observation", "agent_awareness"]

    @model_validator(mode="after")
    def interval_is_nonempty(self) -> WvwOwnershipInterval:
        if self.end_ms <= self.start_ms:
            raise ValueError("ownership interval must satisfy start_ms < end_ms")
        return self


class WvwPositionSample(_ExportModel):
    actor_id: str = Field(min_length=1)
    time_ms: int = Field(ge=0)
    x: float
    y: float
    z: float


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
    position_samples: list[WvwPositionSample]

    @model_validator(mode="after")
    def references_and_order_are_valid(self) -> WvwExportFight:  # noqa: PLR0912
        actor_ids = {actor.actor_id for actor in self.actors}
        if len(actor_ids) != len(self.actors):
            raise ValueError("actor_id values must be unique within a fight")
        if self.started_at is not None and self.started_at.utcoffset() is None:
            raise ValueError("started_at must include a UTC offset")
        for actor in self.actors:
            if actor.last_aware_ms > self.duration_ms:
                raise ValueError("actor awareness exceeds fight duration_ms")
        if self.events != sorted(self.events, key=lambda event: (event.time_ms, event.sequence)):
            raise ValueError("events must be ordered by time_ms then sequence")
        if len({event.sequence for event in self.events}) != len(self.events):
            raise ValueError("event sequence values must be unique within a fight")
        for event in self.events:
            for actor_id in (event.source_actor_id, event.target_actor_id):
                if actor_id is not None and actor_id not in actor_ids:
                    raise ValueError(f"event references unknown actor_id {actor_id!r}")
            if event.time_ms > self.duration_ms:
                raise ValueError("event time_ms exceeds fight duration_ms")
        if self.position_samples != sorted(
            self.position_samples, key=lambda sample: (sample.time_ms, sample.actor_id)
        ):
            raise ValueError("position_samples must be ordered by time_ms then actor_id")
        for sample in self.position_samples:
            if sample.actor_id not in actor_ids:
                raise ValueError(f"position sample references unknown actor_id {sample.actor_id!r}")
            if sample.time_ms > self.duration_ms:
                raise ValueError("position sample time_ms exceeds fight duration_ms")
        for interval in self.ownership_intervals:
            if interval.agent_id not in actor_ids:
                raise ValueError(
                    f"ownership interval references unknown agent_id {interval.agent_id!r}"
                )
            if interval.owner_actor_id is not None and interval.owner_actor_id not in actor_ids:
                raise ValueError(
                    "ownership interval references unknown owner_actor_id "
                    f"{interval.owner_actor_id!r}"
                )
            if interval.end_ms > self.duration_ms:
                raise ValueError("ownership interval end_ms exceeds fight duration_ms")
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
