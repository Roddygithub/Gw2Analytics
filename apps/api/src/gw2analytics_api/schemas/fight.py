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
    loses the pagination cursor (``limit``, ``offset``) on the
    wire. A frontend operator page cannot render "Showing
    50 of N fights" without either (A) a second round-trip
    asking for the same set + a ``COUNT(*)`` query or (B)
    reading the cursor back from the request that produced
    the page. This wrapper carries both the trimmed page
    (the ``fights`` list) AND the pagination cursor
    (``limit``, ``offset``) so the next iteration of the
    frontend pagination UX has the cursor metadata without
    a second round-trip.

    Field semantics mirror the handler's ``Query`` params
    (``limit`` clamped to ``[1, 500]``; ``offset`` clamped to
    ``[0, ∞)``). The defaults match the handler so a
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


class PlayerSkillUsageRowOut(BaseModel):
    """One row of a per-player per-skill roll-up.

    Tour 4 v0.10.13 plan 044: Skill build analyser. Same shape
    as :class:`SkillUsageRowOut` (the per-fight roll-up) but
    source-attributed to a specific player's agent. The frontend
    uses this when the analyst picks a player on the per-fight
    drill-down page (``PlayerSkillUsageFilter`` dropdown,
    mirroring the v0.10.3 ``PerPlayerTimeline`` UX pattern).
    """

    model_config = ConfigDict(from_attributes=True)

    skill_id: int
    skill_name: str
    hit_count: int
    total_damage: int
    total_healing: int
    total_buff_removal: int


class PlayerSkillLoadoutOut(BaseModel):
    """One player's loadout info at fight start.

    Tour 4 v0.10.13 plan 044: Skill build analyser. The wire
    format matches :class:`AgentOut`'s ``profession`` +
    ``elite_spec`` conventions (numeric enum values converted
    via ``format_profession`` + ``format_elite_spec`` from
    :mod:`gw2analytics_api.route_helpers`).

    ``equipped_skill_ids`` is the V1 STUB -- the parser does
    NOT yet extract equipped-skill IDs from the EVTC binary
    (a separate parser-layer ticket, deferred to v0.11.0). The
    field is intentionally an empty list (NOT omitted) so the
    frontend can render the empty-state panel without a
    conditional branch.
    """

    model_config = ConfigDict(from_attributes=True)

    profession: str
    elite_spec: str
    equipped_skill_ids: list[int] = []


class PlayerSkillsOut(BaseModel):
    """Per-player skill roll-up + loadout for one fight.

    Tour 4 v0.10.13 plan 044: Skill build analyser. Equivalent
    to :class:`FightSkillsOut` but with source-side attribution
    (every skill rolled up IS the player's own) + the player's
    loadout pre-pended for the per-player UI.

    A 0-player-attribution fight (the agent row resolves but
    the parsed event stream contains no events with
    ``source_agent_id == player_agent.agent_id``) returns
    ``200 OK`` with ``skills: []`` -- NOT 404. The 0-skills
    state is distinguishable from "player not found in fight"
    which returns 404 (see the endpoint docstring on
    :func:`get_fight_player_skills`).
    """

    model_config = ConfigDict(from_attributes=True)

    fight_id: str
    account_name: str
    agent_id: int
    loadout: PlayerSkillLoadoutOut
    skills: list[PlayerSkillUsageRowOut] = []


class PlayerReadoutDamageOut(BaseModel):
    """One player's damage rollup column block.

    Tour 5 v0.10.23 plan 045: Combat readout ``Damage`` table
    (per ``docs/v0.9.0-combat-readout-design.md`` §3). Same
    wire-shape contract as the JSON example in §5.1: total
    DPS + power/condi split + strips-on-DPS-row + cc-applied
    + down-contribution-dps + kills. Defaults leave every
    field zero so the parser can stream empty player rows
    before Phase 6 v2 lands the statechange events (the
    stips/cc/down/kills columns require a Phase 6 v2
    statechange parser extension that is NOT part of v0.10.23).
    """

    model_config = ConfigDict(from_attributes=True)

    dps_total: float = 0.0
    dps_power: float = 0.0
    dps_condi: float = 0.0
    strips: int = 0
    cc_applied: int = 0
    down_contribution_dps: float = 0.0
    kills: int = 0


class PlayerReadoutHealOut(BaseModel):
    """One player's heal rollup column block.

    Tour 5 v0.10.23 plan 045: Combat readout ``Heal`` table
    (per §4 of the design doc). The heal+barrier split is
    Pydantic-mandatory per §7 of the design doc (barrier
    MUST be a separate field from heal). ``stun_breaks``
    is the per-fight count of :class:`StunBreakEvent` rows
    where this player is ``source_agent_id``.
    """

    model_config = ConfigDict(from_attributes=True)

    heal_total: int = 0
    hps: float = 0.0
    barrier_total: int = 0
    barrier_ps: float = 0.0
    cleanses: int = 0
    stun_breaks: int = 0


class PlayerReadoutBoonsOut(BaseModel):
    """One player's boons rollup column block.

    Tour 5 v0.10.23 plan 045: Combat readout ``Boons`` table
    (per §5 of the design doc). The 6 named boons get fixed
    columns; the remaining ~34 GW2 boons collapse into
    ``other_boons_out`` (a free-form name → count mapping;
    default empty dict so the frontend renders the empty-state
    column without a conditional branch).
    """

    model_config = ConfigDict(from_attributes=True)

    boons_out_rate: float = 0.0
    boons_in_rate: float = 0.0
    stability_out: int = 0
    alacrity_out: int = 0
    resistance_out: int = 0
    aegis_out: int = 0
    superspeed_out: int = 0
    stealth_out: int = 0
    other_boons_out: dict[str, int] = {}


class PlayerReadoutDefenseOut(BaseModel):
    """One player's defense rollup column block.

    Tour 5 v0.10.23 plan 045: Combat readout ``Defense``
    table (per §6 of the design doc). The ``time_downed_ms``
    column requires the parser to track the ``downed`` state
    per target across events (Phase 6 v2 work); the v0.10.23
    scaffold leaves it at 0 by default.
    """

    model_config = ConfigDict(from_attributes=True)

    damage_taken: int = 0
    cc_taken: int = 0
    deaths: int = 0
    time_downed_ms: int = 0
    dodges: int = 0
    blocks: int = 0
    interrupts: int = 0
    barrier_absorbed: int = 0


class PlayerReadoutOut(BaseModel):
    """One player's full Combat-readout row.

    Tour 5 v0.10.23 plan 045: the 5 shared identity columns
    (per design doc §2: subgroup, name, elite_spec,
    is_commander, roles) PLUS the 4 nested per-aspect
    rollup column blocks (Damage / Heal / Boons / Defense).
    Mirrors the §5.1 JSON example one-for-one.

    **Naming note (the convention-break):** the 4 nested
    aspect blocks (``PlayerReadoutDamageOut`` /
    ``PlayerReadoutHealOut`` / ``PlayerReadoutBoonsOut`` /
    ``PlayerReadoutDefenseOut``) intentionally do NOT carry
    the project's ``Row`` suffix convention (cf.
    :class:`SkillUsageRowOut` / :class:`TargetDpsRowOut`
    / :class:`SquadRollupRowOut`): they represent NESTED
    column BLOCKS inside this single row-shaped aggregate,
    not FLAT per-target / per-skill aggregation rows. This
    class itself (``PlayerReadoutOut``) plays the role of
    the ``row`` in any future flat-aggregation surface, so
    the 4 nested aspect blocks nest INSIDE the row rather
    than competing with it for the ``Row`` suffix.

    ``roles`` is a backend-computed ``list[str]`` (the role
    classifier module is the ``gw2_analytics``
    PlayerRoleClassifier workspace owner; v0.10.23 ships
    the wire shape only — the classifier + its
    threshold-calibration is a follow-up cycle).
    ``is_commander`` defaults False (the commando-flag is
    ONLY rendered when the ORM exposes it; the v0.10.23
    scaffold primes the field for the future Phase C
    feature where the parser writes the flag).
    """

    model_config = ConfigDict(from_attributes=True)

    agent_id: int
    subgroup: int
    name: str
    account_name: str
    profession: str
    elite_spec: str
    is_commander: bool = False
    roles: list[str] = []
    damage: PlayerReadoutDamageOut = PlayerReadoutDamageOut()
    heal: PlayerReadoutHealOut = PlayerReadoutHealOut()
    boons: PlayerReadoutBoonsOut = PlayerReadoutBoonsOut()
    defense: PlayerReadoutDefenseOut = PlayerReadoutDefenseOut()


class FightReadoutOut(BaseModel):
    """The full Combat-readout payload for one fight.

    Tour 5 v0.10.23 plan 045: the wire shape for
    ``GET /api/v1/fights/{fight_id}/readout`` (per
    design doc §5.1's "unified endpoint" choice: a single
    round-trip renders all 4 tables). v0.10.23 ships the
    wire shape only — the route handler + statechange
    aggregators await the Phase 6 v2 parser-stream switch
    (separate from this tour).
    """

    model_config = ConfigDict(from_attributes=True)

    fight_id: str
    duration_s: float = 0.0
    players: list[PlayerReadoutOut] = []
