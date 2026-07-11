from __future__ import annotations

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


class FightsPageOut(BaseModel):
    """Paginated response shape for ``GET /api/v1/fights``.

    v0.10.12 PR 3.2 closes the thin-route per-handler
    schema-typing gap identified by Phase C's architect verdict:
    the pre-PR-3.2 handler returned a naked ``list[FightOut]``
    which is technically valid for ``response_model=`` but
    loses the pagination cursor (``limit``, ``offset``) on
    the wire. A frontend operator page cannot render "Showing
    50 of N fights" without either (A) a second round-trip
    asking for the same set + a ``COUNT(*)`` query or (B)
    reading the cursor back from the request that produced
    the page. This wrapper carries both the trimmed page
    (the ``fights`` list) AND the pagination cursor
    (``limit``, ``offset``) so the next iteration of the
    frontend pagination UX has the cursor metadata without
    a second round-trip.

    Field semantics mirror the handler's ``Query`` params
    (``limit`` clamped to ``[1, 500]``; ``offset`` clamped
    to ``[0, ∞)``). The defaults match the handler so a
    frontend that consumes a hard-coded call site gets the
    same out-of-the-box behaviour. ``total_count`` is
    deliberately NOT in this wrapper: adding it would force
    a separate ``SELECT count(*) FROM fights`` round-trip
    per request and the architect verdict explicitly
    scoped this PR to the schema-typing gap closure, not
    the pagination-enhancement feature.
    """

    model_config = ConfigDict(from_attributes=True)

    fights: list[FightOut] = []
    limit: int = 50
    offset: int = 0


class EventBucketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start_ms: int
    end_ms: int
    damage_total: int = 0
    healing_total: int = 0
    event_count: int = 0


class TargetDpsRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_agent_id: int
    total_damage: int
    dps: float
    name: str | None = None


class TargetHealingRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_agent_id: int
    total_healing: int
    hps: float
    name: str | None = None


class TargetBuffRemovalRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_agent_id: int
    total_buff_removal: int
    bps: float
    name: str | None = None


class FightEventsSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fight_id: str
    duration_s: float
    target_dps: list[TargetDpsRowOut] = []
    target_healing: list[TargetHealingRowOut] = []
    target_buff_removal: list[TargetBuffRemovalRowOut] = []
    event_windows: list[EventBucketOut] = []


class SquadRollupRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subgroup: str
    total_damage: int
    total_healing: int
    total_buff_removal: int
    dps: float
    hps: float
    bps: float


class FightSquadsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fight_id: str
    duration_s: float
    squads: list[SquadRollupRowOut] = []


class SkillUsageRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    skill_id: int
    skill_name: str
    hit_count: int
    total_damage: int
    total_healing: int
    total_buff_removal: int


class FightSkillsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fight_id: str
    skills: list[SkillUsageRowOut] = []


class PerFightTimelinePointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    window_start_ms: int
    window_end_ms: int
    total_damage: int
    total_healing: int
    total_buff_removal: int


class PerFightTimelineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fight_id: str
    window_s: int
    duration_s: float
    points: list[PerFightTimelinePointOut] = []


class PerPlayerTimelinePointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    window_start_ms: int
    window_end_ms: int
    total_damage: int
    total_healing: int
    total_buff_removal: int


class PerPlayerTimelineSeriesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_name: str
    name: str
    points: list[PerPlayerTimelinePointOut] = []


class PerPlayerTimelineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fight_id: str
    window_s: int
    duration_s: float
    series: list[PerPlayerTimelineSeriesOut] = []
