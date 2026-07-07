"""Pydantic v2 schemas for the API surface (request + response).

These are HTTP-only contracts; they are NOT the domain models. Domain
lives in ``gw2_core``. We deliberately translate between the two at the
route boundary to keep persistence independent of API evolution.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_id: int
    name: str
    profession: str
    elite_spec: str
    is_player: bool
    account_name: str | None = None
    subgroup: str | None = None


class SkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class FightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    build_version: str
    encounter_id: int
    agent_count: int
    started_at: datetime
    game_type: int
    agents: list[AgentOut] = []
    skills: list[SkillOut] = []


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sha256: str
    original_filename: str
    size_bytes: int
    uploaded_at: datetime
    status: str
    error_message: str | None = None
    parser_version: str
    fight_id: str | None = None


class UploadCreatedResponse(BaseModel):
    """Returned from POST /uploads before parsing is finalised."""

    id: uuid.UUID
    sha256: str
    status: str


class EventBucketOut(BaseModel):
    """Response schema for ``GET /api/v1/fights/{fight_id}/events``.

    Mirrors :class:`gw2_analytics.event_window.EventBucket` so the
    OpenAPI shape is locked before the parser-side integration in
    Phase 6 v2. Phase 6 v1 returns an empty list — this schema is
    future-proofed for the moment parsing of events arrives.
    """

    model_config = ConfigDict(from_attributes=True)

    start_ms: int
    end_ms: int
    damage_total: int = 0
    healing_total: int = 0
    event_count: int = 0


class TargetDpsRowOut(BaseModel):
    """One damage roll-up row in :class:`FightEventsSummaryOut`.

    Mirrors :class:`gw2_analytics.target_dps.TargetDpsRow` with the
    ``attack_count`` field dropped from the API surface (analyst-only
    signal; UI shows ``total_damage`` + ``dps`` only).
    """

    model_config = ConfigDict(from_attributes=True)

    target_agent_id: int
    total_damage: int
    dps: float


class TargetHealingRowOut(BaseModel):
    """One healing roll-up row in :class:`FightEventsSummaryOut`.

    Mirrors :class:`gw2_analytics.target_healing.TargetHealingRow`
    with the ``heal_count`` field dropped from the API surface
    (analyst-only signal; UI shows ``total_healing`` + ``hps`` only).
    Strict parallel of :class:`TargetDpsRowOut` so the pair reads as
    one design.
    """

    model_config = ConfigDict(from_attributes=True)

    target_agent_id: int
    total_healing: int
    hps: float


class TargetBuffRemovalRowOut(BaseModel):
    """One buff-removal roll-up row in :class:`FightEventsSummaryOut`.

    Mirrors
    :class:`gw2_analytics.target_buff_removal.TargetBuffRemovalRow`
    with the ``strip_count`` field dropped from the API surface
    (analyst-only signal; UI shows ``total_buff_removal`` + ``bps``
    only). Strict parallel of :class:`TargetDpsRowOut` /
    :class:`TargetHealingRowOut` so the trio reads as one design.
    Phase 8 ships this third roll-up.
    """

    model_config = ConfigDict(from_attributes=True)

    target_agent_id: int
    total_buff_removal: int
    bps: float


class FightEventsSummaryOut(BaseModel):
    """Combined aggregation payload returned by ``GET /api/v1/fights/{fight_id}/events``.

    Phase 7 v1 ships a single bound response so the frontend can render
    the timeline + per-target DPS without two extra round-trips.
    Phase 7 v1 of the API adds the per-target healing roll-up as a
    sibling field, completing the v2 Event union consumption on the
    HTTP surface (the v2 ``Event`` discriminated union
    ``DamageEvent | HealingEvent`` is now materialised as both a
    per-target DPS roll-up AND a per-target healing roll-up in a
    single round-trip).

    Contract:

    - ``duration_s`` is computed natively from
      ``max(event.time_ms) / 1000.0`` because the V1.3 EVTC header
      does not carry a wall-clock duration scalar.
    - ``target_dps`` is empty when the parser yielded zero damage events
      (after the ``is_statechange == 0`` ``/`` ``is_nondamage == 0``
      ``/`` ``value > 0`` filter); the route returns ``404 Not Found``
      when the events blob is missing entirely (pre-Phase-7 row OR the
      blob upload failed).
    - ``target_healing`` is the strict parallel of ``target_dps``
      (filtered by ``isinstance(e, HealingEvent)`` and rolled up via
      :class:`gw2_analytics.target_healing.TargetHealingAggregator`).
      Empty when the parser yielded zero healing events; the
      damage-only / heal-only / mixed-fight cases all surface
      correctly because the route filters at the call site rather
      than branching inside the aggregator.
    - ``target_buff_removal`` (Phase 8) is the third sibling roll-up,
      filtered by ``isinstance(e, BuffRemovalEvent)`` and rolled up via
      :class:`gw2_analytics.target_buff_removal.TargetBuffRemovalAggregator`.
      The parser yields ``BuffRemovalEvent`` from two distinct paths:
      (a) a single ``cbtevent`` record with ``is_statechange == 0``,
      ``is_nondamage > 0``, ``value > 0``, ``buff_dmg > 0`` yields
      BOTH a ``HealingEvent`` AND a ``BuffRemovalEvent`` (corrupting
      / confusion skills that heal the caster + strip a boon); (b) a
      record with ``is_nondamage > 0``, ``value == 0``,
      ``buff_dmg > 0`` yields ONLY a ``BuffRemovalEvent`` (pure
      strip). Empty when the parser yielded zero strip events.
    - ``event_windows`` is empty when there are no events. The
      ``EventWindowAggregator`` accepts the full ``Iterable[Event]``
      and accounts damage + healing in one bucket
      (``damage_total`` + ``healing_total`` + ``event_count``).
      Phase 8 deliberately does NOT extend ``EventBucketOut`` with a
      ``buff_removal_total`` field -- the per-bucket window contract
      is locked and the heterogeneous stream passes through unchanged
      (the aggregator's unknown-event fallback increases
      ``event_count``).
    """

    model_config = ConfigDict(from_attributes=True)

    fight_id: str
    duration_s: float
    target_dps: list[TargetDpsRowOut] = []
    target_healing: list[TargetHealingRowOut] = []
    target_buff_removal: list[TargetBuffRemovalRowOut] = []
    event_windows: list[EventBucketOut] = []  # forwarded Pydantic alias


class AccountEnrichedOut(BaseModel):
    """GET /api/v1/account response.

    Composed in :mod:`gw2analytics_api.routes.account` from two
    upstream calls (``AsyncGuildWars2Client.account_get`` +
    ``worlds_get([account.world_id])``) so the client gets a single
    (world_id, world_name, world_population) tuple per GW2 API key.

    ``world_population`` is the canonical capitalised ``Population``
    string exactly as the v2 API emits (``"Low" | "Medium" | "High" |
    "VeryHigh" | "Full"``). Forward-compat is delegated to ``gw2_core``
    ``Population`` parsing; if the v2 API grows a new bucket, the
    underlying ``WorldInfo`` validation raises and the route surfaces
    a 502 rather than silently coercing to a known bucket.
    """

    model_config = ConfigDict(from_attributes=True)

    world_id: int
    world_name: str
    world_population: str  # matches gw2_core.Population values
