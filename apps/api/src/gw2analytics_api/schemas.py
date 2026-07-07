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


class SquadRollupRowOut(BaseModel):
    """One per-subgroup roll-up row in :class:`FightSquadsOut`.

    Mirrors :class:`gw2_analytics.squad_rollup.SquadRollupRow` with
    the ``hit_count`` field dropped from the API surface
    (analyst-only signal; UI shows ``total_damage`` +
    ``total_healing`` + ``total_buff_removal`` + the three
    per-second rates only). v0.7.0 ships this fourth roll-up,
    source-side (the subgroup is the actor's, not the target's).
    """

    model_config = ConfigDict(from_attributes=True)

    subgroup: str
    total_damage: int
    total_healing: int
    total_buff_removal: int
    dps: float
    hps: float
    bps: float


class FightSquadsOut(BaseModel):
    """Combined payload from ``GET /api/v1/fights/{fight_id}/squads``.

    v0.7.0 ships the squad-rollup as a separate endpoint (not
    folded into :class:`FightEventsSummaryOut`) so the per-fight
    drill-down page can fetch it in parallel with the per-target
    roll-ups via ``Promise.all``; folding it into the existing
    payload would force the page to refetch the full event blob
    even when only the squad view is requested. The route
    decompresses the same events blob, splits by ``isinstance``,
    and invokes
    :class:`gw2_analytics.squad_rollup.SquadRollupAggregator` on
    the same ``duration_s`` used by the per-target trio.
    """

    model_config = ConfigDict(from_attributes=True)

    fight_id: str
    duration_s: float
    squads: list[SquadRollupRowOut] = []


class SkillUsageRowOut(BaseModel):
    """One per-skill roll-up row in :class:`FightSkillsOut`.

    Mirrors :class:`gw2_analytics.skill_usage.SkillUsageRow`; the
    ``hit_count`` field is kept on the API surface (it's the
    per-skill event frequency, the only per-skill signal that
    doesn't depend on a duration). v0.7.0 ships this fifth
    roll-up.
    """

    model_config = ConfigDict(from_attributes=True)

    skill_id: int
    skill_name: str
    hit_count: int
    total_damage: int
    total_healing: int
    total_buff_removal: int


class FightSkillsOut(BaseModel):
    """Combined payload from ``GET /api/v1/fights/{fight_id}/skills``.

    v0.7.0 ships the skill-usage roll-up as a separate endpoint
    (not folded into :class:`FightEventsSummaryOut`); same
    rationale as :class:`FightSquadsOut`. The route loads the
    fight's ``OrmFightSkill`` rows to build the
    ``skill_id -> skill_name`` map and invokes
    :class:`gw2_analytics.skill_usage.SkillUsageAggregator` on
    the split event streams.
    """

    model_config = ConfigDict(from_attributes=True)

    fight_id: str
    skills: list[SkillUsageRowOut] = []


class PlayerListRowOut(BaseModel):
    """One row of the cross-fight player roll-up returned by ``GET /api/v1/players``.

    Lean schema for the list endpoint: the analyst scans a
    paginated AG Grid of accounts. The full per-fight breakdown
    lives on :class:`PlayerProfileOut` (returned by the detail
    endpoint).

    ``account_name`` is the operational identity (stable across
    uploads). ``name`` is the last-seen char-name (cosmetic
    identity). The three totals are summed across every fight the
    account attended.
    """

    model_config = ConfigDict(from_attributes=True)

    account_name: str
    name: str
    profession: str
    elite_spec: str
    fights_attended: int
    total_damage: int
    total_healing: int
    total_buff_removal: int


class PerFightBreakdownRowOut(BaseModel):
    """One row of the per-fight breakdown on :class:`PlayerProfileOut`.

    The route computes one of these per ``(fight_id, account_name)``
    pair by walking the fight's events blob and accumulating
    magnitudes where ``event.source_agent_id`` maps to
    ``account_name`` via :class:`OrmFightAgent`.
    """

    model_config = ConfigDict(from_attributes=True)

    fight_id: str
    started_at: datetime
    total_damage: int
    total_healing: int
    total_buff_removal: int


class PlayerProfileOut(BaseModel):
    """Full player profile returned by ``GET /api/v1/players/{account_name}``.

    Mirrors :class:`gw2_analytics.player_profile.PlayerProfile`
    with the addition of the per-fight breakdown array
    (``per_fight_breakdown``) and the ``started_at`` timestamps
    on each fight row. v0.7.0 ships the player-centric view of
    the dataset; the route joins on ``OrmFightAgent.account_name``
    to build the cross-fight roll-up.

    ``account_name`` is URL-encoded in the request path because
    arcdps prefixes the value with ``:`` (e.g. ``:account.1234``);
    FastAPI's path-parameter parser handles the decoding. The
    route raises ``404 Not Found`` when no agent in any fight
    carries the requested ``account_name``.
    """

    model_config = ConfigDict(from_attributes=True)

    account_name: str
    name: str
    profession: str
    elite_spec: str
    fights_attended: int
    total_damage: int
    total_healing: int
    total_buff_removal: int
    attended_fight_ids: list[str] = []
    per_fight_breakdown: list[PerFightBreakdownRowOut] = []


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
