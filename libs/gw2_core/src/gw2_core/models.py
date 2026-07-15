"""Pydantic models for GW2 combat data + the official v2 API.

This module is the **stable internal data model** of the application.
Nothing else may import from another domain to define a model. Other
packages may only consume or produce these shapes.

Three model families live here:

1. **Combat-data models** (`Agent`, `Skill`, `Fight`, etc.) -- the
   parser / analytics layer's vocabulary.
2. **Event-stream models** (`BaseEvent` + `DamageEvent` /
   `HealingEvent` + `EventType` discriminator) -- the synthetic event
   data types forwarded by :mod:`gw2_analytics` Phase 6 v1. Forward
   compat: a future Phase 6 v2 will swap the synthetic
   ``Iterable[Event]`` input for a parser-sourced stream.
3. **API-data models** (`AccountInfo`, `WorldInfo`, `Population`)
   -- the cross-cutting shapes needed for downstream enrichment (the
   v2 REST API's ``account`` and ``worlds`` endpoints). The
   ``gw2_api_client`` library OO-wraps the HTTP calls but delegates
   the shape definitions here so ``gw2_analytics`` can consume them
   without importing the HTTP client.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, WrapValidator

# ---------------------------------------------------------------------------
# Enums (IntEnum because EVTC stores them as 4-byte little-endian integers)
# ---------------------------------------------------------------------------


class Profession(IntEnum):
    """GW2 core professions.

    Integer values mirror what ``arcdps`` writes in the agent table bytes 8-11.
    See the wiki for the canonical mapping.
    """

    UNKNOWN = 0
    GUARDIAN = 1
    WARRIOR = 2
    ENGINEER = 3
    RANGER = 4
    THIEF = 5
    ELEMENTALIST = 6
    MESMER = 7
    NECROMANCER = 8
    REVENANT = 9


class EliteSpec(IntEnum):
    """Elite specializations.

    Integer values mirror ``arcdps`` bytes 12-15. Values are taken from the
    Elite Insights / GW2 wiki mapping. The catalogue is intentionally
    incomplete -- unknown values fall back to :attr:`UNKNOWN` at parse time.

    NOTE: Some older ``arcdps`` revisions write legacy IDs that no longer
    match the current catalogue (e.g. Druid = 5 reused for Soulbeast in
    early 2017 releases). The parser preserves the raw byte value via
    :attr:`Agent.elite_raw` for forensics; the enum mapping is best-effort.
    """

    UNKNOWN = 0
    BASE = 0  # No elite spec active
    # Warrior elites
    BERSERKER = 18
    SPELLBREAKER = 64
    # Guardian elites
    DRAGONHUNTER = 27
    FIREBRAND = 62
    WILLBENDER = 65
    # Revenant elites
    HERALD = 52
    RENEGADE = 63
    VINDICATOR = 68
    # Thief elites
    DAREDEVIL = 55
    DEADEYE = 71
    SPECTER = 72
    # Engineer elites
    SCRAPPER = 43
    HOLOSMITH = 57
    MECHANIST = 70
    # Ranger elites
    DRUID = 5
    SOULBEAST = 55  # collides with Daredevil pre-2018
    UNTAMED = 73
    # Elementalist elites
    TEMPEST = 48
    WEAVER = 63  # collides with Renegade historically
    CATALYST = 75
    # Mesmer elites
    CHRONOMANCER = 40
    MIRAGE = 59
    VIRTUOSO = 74
    # Necromancer elites
    REAPER = 34
    SCOURGE = 60
    HARBINGER = 77


class GameType(IntEnum):
    """Combat context."""

    WVW = 1
    PVE = 2
    PVP = 3


class Population(StrEnum):
    """GW2 world population state. Capitalised exactly as the v2 API emits."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    VERY_HIGH = "VeryHigh"
    FULL = "Full"


# ---------------------------------------------------------------------------
# Combat-data models (parser / analytics layer vocabulary)
# ---------------------------------------------------------------------------


class EvtcHeader(BaseModel):
    """The 20-byte file header at the start of every EVTC log.

    Mirrors the binary layout produced by ``arcdps``; we use it as the
    parser's first read pass and as a stable identifier of the log file.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    magic: str = Field(default="EVTC", min_length=4, max_length=4)
    build_version: str = Field(
        ..., min_length=8, max_length=8, description="ASCII arcdps build date, e.g. '20250925'."
    )
    encounter_id: int = Field(default=0, ge=0, le=0xFFFF)
    agent_count: int = Field(..., ge=0, le=10_000)
    skill_count: int = Field(default=0, ge=0, le=100_000)


class Agent(BaseModel):
    """One entity (player, NPC or gadget) observed during the fight."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int = Field(..., ge=0, description="arcdps pointer-sized agent id (uint64).")
    name: str = Field(..., min_length=0, max_length=128)
    profession: Profession = Profession.UNKNOWN
    elite: EliteSpec = EliteSpec.UNKNOWN
    elite_raw: int = Field(
        default=0, ge=0, le=0xFFFFFFFF, description="Raw elite byte for forensics."
    )
    is_player: bool = Field(
        default=False,
        description=(
            "True for player agents (name is a combo string "
            "'char_name\\0account_name\\0subgroup\\0' in arcdps EVTC). "
            "False for NPCs and gadgets (name is a single null-terminated string)."
        ),
    )
    account_name: str | None = Field(
        default=None,
        max_length=128,
        description="Player's account name (always prefixed with ':' in arcdps). None for NPCs.",
    )
    subgroup: str | None = Field(
        default=None,
        max_length=128,
        description="arcdps subgroup string (e.g. 'Subgroup 1' or empty). None for NPCs.",
    )


class Skill(BaseModel):
    """One skill/buff used or referenced during the fight.

    V0 keeps this contract minimal -- the parser does not yet expand skill
    names because none of V0 metrics need skill-name attribution.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int = Field(..., ge=0)
    name: str = Field(default="")


class Fight(BaseModel):
    """One combat encounter.

    A loaded EVTC log yields exactly one :class:`Fight`. Skill and event
    lists are intentionally lazy: V0 fills only what the parser populates,
    later phases enrich them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Identity (stable across runs)
    id: str = Field(
        ..., min_length=1, description="Stable identifier (SHA-256 of the source blob)."
    )
    started_at: datetime = Field(
        default_factory=lambda: datetime(1970, 1, 1, tzinfo=UTC),
        description=(
            "UTC timestamp at fight start. EVTC has no wall-clock so V0 uses an epoch sentinel."
        ),
    )
    game_type: GameType = Field(default=GameType.WVW)

    # Parser-driven payload (V0)
    header: EvtcHeader | None = None
    agents: list[Agent] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Event-stream models (Phase 6 v1 synthetic event types).
#
# arcdps EVTC has 30+ statechange kinds (damage, healing, buff, defiance,
# etc.) but the V1.3 parser only consumes the agent + skill blocks.
# Phase 6 v1 ships synthetic event data types so the analytics layer can
# validate rollup logic against deterministic fixtures; Phase 6 v2 will
# swap the synthetic ``Iterable[Event]`` inputs for a parser-sourced
# stream once the EVTC event block is consumed.
# ---------------------------------------------------------------------------


class EventType(StrEnum):
    """Discriminator for synthetic event kinds shipped in Phase 6 v1.

    Forward-compat: new ``EventType`` entries can be added alongside
    ``DAMAGE`` / ``HEALING`` / ``BUFF_REMOVAL``; aggregators gate on
    ``isinstance`` against the matching subclass, so unrecognized types
    fall through to ``event_count`` without breaking
    ``damage_total`` / ``healing_total`` / ``buff_removal_total``
    accounting.

    Spike (Plan 024) adds ``BOON_APPLY`` and ``CC`` as the first two
    members of the v0.9.0 combat-readout event vocabulary. They are
    emitted from arcdps statechange records (``is_statechange != 0``)
    once the parser is extended; until then they exist only as
    Pydantic shapes for API/aggregator design.
    """

    DAMAGE = "DAMAGE"
    HEALING = "HEALING"
    BUFF_REMOVAL = "BUFF_REMOVAL"
    BOON_APPLY = "BOON_APPLY"
    CC = "CC"
    CONDITION_REMOVE = "CONDITION_REMOVE"
    DOWN = "DOWN"
    DEATH = "DEATH"
    STUN_BREAK = "STUN_BREAK"
    # Wave 5 SCAFFOLD defense-tracking triplet (restored from baseline; the
    # enum entry MUST be declared BEFORE the Literal[EventType.X] reference
    # in the matching subclass body so the discriminator resolves at class
    # definition time).
    DODGE = "DODGE"
    BLOCK = "BLOCK"
    INTERRUPT = "INTERRUPT"
    # WAVE-8 v0.11.0 Blocker A.3 part 2: 1 NEW entry -- BARRIER. The A.4
    # parser emit path will deserialize the arcdps statechange kinds into
    # the matching subclass per WAVE-8 §2 A.2 kind map.
    BARRIER = "BARRIER"


class BaseEvent(BaseModel):
    """Common timestamp + actor + skill fields shared by every event kind.

    Subclasses carry the per-kind payload (``damage``, ``healing``, ...).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    time_ms: int = Field(..., ge=0, description="Milliseconds since fight start.")
    source_agent_id: int = Field(..., ge=0, description="Actor agent id.")
    target_agent_id: int = Field(..., ge=0, description="Target agent id.")
    skill_id: int = Field(..., ge=0, description="Skill/buff id (FK to fight.skills).")


class DamageEvent(BaseEvent):
    """One outgoing-damage event. ``damage`` is the per-hit integer value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal[EventType.DAMAGE] = EventType.DAMAGE
    damage: int = Field(..., ge=0)


class HealingEvent(BaseEvent):
    """One outgoing-healing event. ``healing`` is the per-hit integer value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal[EventType.HEALING] = EventType.HEALING
    healing: int = Field(..., ge=0)


class BuffRemovalEvent(BaseEvent):
    """One outgoing buff-strip event. ``buff_removal`` is the per-hit integer value.

    Phase 8 ships the third Event discriminated union member. A single
    arcdps ``cbtevent`` record can represent BOTH an outgoing heal AND
    a buff strip (corrupting / confusion skills; ``is_nondamage > 0``
    + ``buff_dmg > 0``); the parser yields BOTH a
    :class:`HealingEvent` (with ``healing = value``) AND a
    :class:`BuffRemovalEvent` (with ``buff_removal = buff_dmg``) from
    the same record. The "double-counting" concern that deferred this
    from Phase 7 v2 was about adding ``buff_dmg`` to the
    ``HealingEvent.healing`` field -- the v0.5.0-parser code did
    ``magnitude = max(0, value)`` and silently discarded ``buff_dmg``.
    Phase 8 keeps that conservative choice (the heal amount stays
    separate from the strip amount) and adds a SECOND yielded event
    for the strip.

    Pure damage records (``is_nondamage == 0``) with ``buff_dmg > 0``
    are NOT classified as buff-strip events: arcdps only writes
    ``buff_dmg`` on the non-damage (heal-class) event kind, so a
    damage record with non-zero ``buff_dmg`` is a parser-version
    artefact and is silently dropped.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal[EventType.BUFF_REMOVAL] = EventType.BUFF_REMOVAL
    buff_removal: int = Field(..., ge=0)


class BoonApplyEvent(BaseEvent):
    """One outgoing boon-state-change event (Phase 9 / advisor-plan 026).

    Forward-compatible union of ALL 4 arcdps ``is_buffremove`` byte
    values (the arcdps.h ``cbtbuffremove`` enum: ``0`` = NONE in
    the buff-emit context the parser interprets as apply, ``1``
    = ALL, ``2`` = SINGLE, ``3`` = MANUAL -- the latter collapses
    onto ``remove_single`` per arcdps's "use for in/out volume"
    guidance; see :func:`gw2_analytics.buff_dispatch.decode_buff_change`)
    gated on the ``kind`` discriminator literal.
    Pre-Phase-9 spike (Plan 024) called this class a "boon-apply"
    event; Phase 9 collapses the apply + 2-remove variants into one
    class because the wire shape (time_ms + source/target agent id +
    skill id + stacks + duration) is identical across the three, and
    the discriminator literal lets downstream aggregators
    (``buff_uptime``, ``BuffState``) compute stack deltas in a single
    pass.

    ``duration_ms`` is the total duration of the applied/removed
    boon stack in milliseconds. ``stacks`` is the magnitude of the
    change (apply: stacks applied; remove_single: 1; remove_all:
    full-stack count to drop). ``kind`` defaults to ``"apply"`` so
    pre-Phase-9 round-trip payloads (those without an explicit
    ``kind`` key) parse cleanly into the apply subset -- the
    backward-compat default materialises the pre-Phase-9
    "outgoing boon apply" semantics into the new class without a
    data migration.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal[EventType.BOON_APPLY] = EventType.BOON_APPLY
    duration_ms: int = Field(
        ..., ge=0, description="Total duration of the applied boon stack in milliseconds."
    )
    stacks: int = Field(..., ge=0, description="Magnitude of the state change.")
    kind: Literal["apply", "remove_single", "remove_all"] = Field(
        default="apply",
        description=(
            "arcdps 2025+ ``cbtbuffremove`` byte decoded: ``0`` = NONE "
            "(interpreted as apply in the buff-emit context), "
            "``1`` = ALL (all-stack remove), ``2`` = SINGLE (single-stack "
            "remove), ``3`` = MANUAL (auto-remove on all-stack or "
            "out-of-combat; collapses to remove_single per arcdps's "
            "'use for in/out volume' guidance). Mapping verified against "
            "the arcdps.h cbtbuffremove enum + ship via Phase 9 step 4. "
            "Defaults to ``'apply'`` for forward-compat with pre-Phase-9 "
            "wire payloads that omit the field."
        ),
    )


class CCEvent(BaseEvent):
    """One crowd-control event.

    Spike (Plan 024) prototype for the v0.9.0 combat-readout Damage
    table ``CC appliqués`` column. ``cc_value`` is the magnitude of
    the crowd-control effect (defiance-bar damage or duration in
    milliseconds — exact semantics TBD during parser integration).
    Emitted from arcdps defiance-bar / breakbar statechange records
    once the parser is extended; until then this model exists only
    for API/aggregator design.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal[EventType.CC] = EventType.CC
    cc_value: int = Field(
        ..., ge=0, description="Crowd-control magnitude (defiance damage or duration ms)."
    )


class ConditionRemoveEvent(BaseEvent):
    """One outgoing condition-removal event (Combat readout §3.4 / §9.1).

    Mirrors :class:`BuffRemovalEvent` semantically
    (``condition_removal`` is the per-hit integer stacks /
    magnitude) but tags the statechange variety so the heal
    table's ``Cleanses`` column + the §3.3 ``Strips`` healing
    column can attribute GW2 conditions (burn / freeze /
    torment / etc) distinct from boons once a skills DB
    catalog lands.

    The boon-vs-condition wire-distinction is NOT made at the
    arcdps API level — BOTH go through ``is_buffremove``
    statechange records; the distinction comes from the
    skills DB catalog (deferred to v0.11.0 per
    ``docs/v0.9.0-combat-readout-design.md`` §9). Until
    then, this class is the forward-compat landing pad for
    condition-removals once the skill-catalog lookup is
    wired.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal[EventType.CONDITION_REMOVE] = EventType.CONDITION_REMOVE
    condition_removal: int = Field(..., ge=0)


class DownEvent(BaseEvent):
    """One ``is_statechange == 5`` (ChangeDown) statechange event.

    The actor (the player who went down) is encoded as
    ``source_agent_id``; ``target_agent_id`` and ``skill_id``
    are both ``0`` because down events have no relevant
    secondary target or skill attribution (the ``ge=0``
    constraint on :class:`BaseEvent` accepts ``0``).

    Combat readout §3 ``Down contribution DPS`` column needs
    both the down event + the subsequent damage events
    targeting that downed agent to compute per-player
    down-contribution DPS; until Phase 6 v2 (parser-stream
    switch) delivers the statechange records this class
    exists as the parser-side landing pad.

    WAVE-8 v0.11.0 §6 risk-5 mitigation: ``downtime_ms`` is the
    per-instance down-state duration in milliseconds (design
    doc §11 Q4 — "time on ground" semantics). The
    ``PlayerReadoutDefenseOut.time_downed_ms`` column aggregates
    ``downtime_ms`` per-source_agent_id (Phase 6 v2 parser-stream
    emits the actual value; pre-Phase-6-v2 streams parse cleanly
    because ``downtime_ms`` defaults to ``0``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal[EventType.DOWN] = EventType.DOWN
    # WAVE-8 §6 risk-5 mitigation: see class docstring above. Field added
    # by the Blocker A.3 first-slice followup commit (the original WAVE-8
    # DownEvent draft carried this field; the dedup preserved it on the
    # canonical Wave 5 SCAFFOLD class).
    downtime_ms: int = Field(default=0, ge=0)


class DeathEvent(BaseEvent):
    """One ``is_statechange == 4`` (ChangeDead) statechange event.

    Actor-only shape (mirrors :class:`DownEvent`): the dying
    player is ``source_agent_id``; both ``target_agent_id``
    and ``skill_id`` are ``0``. The ``killed_by_agent_id`` +
    ``killing_skill_id`` Optional fields are forward-compat
    for Phase 6 v2 (when the parser yields the ``kill``
    tuple from the arcdps state transition); pre-Phase-6-v2
    streams parse cleanly because both fields default to
    ``None`` and Pydantic v2 ``extra="forbid"`` only blocks
    UNKNOWN keys, not unknown-``None`` values on
    pre-declared fields.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal[EventType.DEATH] = EventType.DEATH
    killed_by_agent_id: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Phase 6 v2 forward-compat: the agent responsible for the kill. "
            "``None`` for pre-Phase-6-v2 streams where the kill attribution "
            "is not derivable from the actor-only statechange record."
        ),
    )
    killing_skill_id: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Phase 6 v2 forward-compat: the skill id responsible for the kill. "
            "``None`` for pre-Phase-6-v2 streams where the killing skill is "
            "not yet extracted from the arcdps state transition."
        ),
    )


class StunBreakEvent(BaseEvent):
    """One ``is_statechange == 56`` (StunBreak) statechange event.

    Actor-only shape (mirrors :class:`DownEvent` /
    :class:`DeathEvent`): the player who broke the stun is
    ``source_agent_id``; secondary target/skill fields are
    ``0``. Combat readout §4 ``Breakstunt`` column aggregates
    across the fight.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal[EventType.STUN_BREAK] = EventType.STUN_BREAK

# WAVE-8 v0.11.0 Blocker A.3 part 2: 1 NEW subclass (BarrierEvent); the 7
# other WAVE-8 backlog subclasses (ConditionRemoveEvent + CCEvent +
# DownEvent + DeathEvent + DodgeEvent + BlockEvent + InterruptEvent)
# were pre-existing in the Wave 5 SCAFFOLD + Plan 024 baseline, so
# this commit adds ONLY BarrierEvent (the arcdps barrier statechange
# yield from Phase 6 v2 parser-stream switch). Pattern mirrors
# :class:`StunBreakEvent` (the Tour 6 v0.10.24-pre shipped subclass):
# - arcdps statechange kind byte cbtevent.is_statechange != 0 emits the
#   matching subclass (per A.4 parser decode loop extension, the deferred
#   A.4 deliverable)
# - the ``event_type: Literal[EventType.X]`` discriminator is the canonical
#   JSONL forward-compat contract (verified by the
#   ``tests.test_models_dispatch`` hermetic test below)


class BarrierEvent(BaseEvent):
    """WAVE-8 v0.11.0 Blocker A.3 part 2: barrier application event.

    Arcdps statechange kind ``statechange == BARRIER`` (a planned Phase 6 v2 yield).
    The barrier amount + duration are sub-class-specific fields not part of
    the BaseEvent parent (Phase 6 v2 parser-stream will surface these from the
    per-skill barrier table).
    """

    event_type: Literal[EventType.BARRIER] = EventType.BARRIER
    barrier_amount: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)


class DodgeEvent(BaseEvent):
    """One ``Dodge`` tracking event (Combat readout §6 forward-compat SCAFFOLD).

    Actor-only shape (mirrors :class:`DownEvent` /
    :class:`DeathEvent` / :class:`StunBreakEvent`): the player
    who dodged is ``source_agent_id``; ``target_agent_id`` and
    ``skill_id`` are ``0`` because dodge is a player-action, NOT
    skill-attributable (the arcdps in-game overlay logger is the
    authoritative dodge tracker; the :mod:`libs.gw2_evtc_parser`
    ``EvtcParser`` Protocol V1.3 does NOT surface dodge events,
    so the parser-stream switch in Phase 6 v2 is the precondition
    for production-realistic dodge yields).

    Combat readout §6 ``Dodges`` column is the count of
    :class:`DodgeEvent` rows where ``source_agent_id == player``.
    The Wave 5 SCAFFOLD ships this Event dataclass so the
    :class:`PlayerDefenseAggregator` can fill the previously-stub
    ``dodges`` column without a Phase 6 v2 dependency in the
    aggregator code.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal[EventType.DODGE] = EventType.DODGE


class BlockEvent(BaseEvent):
    """One ``Block`` tracking event (Combat readout §6 forward-compat SCAFFOLD).

    Actor-only shape (mirrors :class:`DodgeEvent`): the player
    who blocked is ``source_agent_id``;
    ``target_agent_id`` + ``skill_id`` are ``0`` because
    block is a player-action, NOT skill-attributable (the
    arcdps in-game overlay logger is the canonical source for
    block counts; the :mod:`libs.gw2_evtc_parser` V1.3 parser
    does NOT surface block events, so the parser-stream switch
    in Phase 6 v2 is the precondition for production-realistic
    block yields).

    Combat readout §6 ``Blocks`` column is the count of
    :class:`BlockEvent` rows where ``source_agent_id == player``.
    The Wave 5 SCAFFOLD ships this Event dataclass so the
    :class:`PlayerDefenseAggregator` can fill the previously-stub
    ``blocks`` column without a Phase 6 v2 dependency in the
    aggregator code.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal[EventType.BLOCK] = EventType.BLOCK


class InterruptEvent(BaseEvent):
    """One ``Interrupt`` event (Combat readout §6 + §9 forward-compat SCAFFOLD).

    Full :class:`BaseEvent` shape (NOT actor-only — explicit
    contrast with :class:`DodgeEvent` / :class:`BlockEvent` which
    ARE actor-only). The asymmetry is by design:

    - ``DodgeEvent`` + ``BlockEvent``: player-action tracking
      where ``target_agent_id = 0`` and ``skill_id = 0`` because
      arcdps records dodge + block as player-side actions
      without a target or skill attribution (the arcdps in-game
      overlay logger is the canonical source; V1.3 parser does
      NOT surface yield a skill or target).
    - ``InterruptEvent``: target + skill CARRIES the forensic
      signal that future per-skill analytics (the v0.11.0 skills
      DB catalog) will surface -- a target agent (the enemy whose
      cast was interrupted) + a skill_id (the interrupt mechanic).
      Truncating these via actor-only shape would lose the
      per-interrupt attribution.

    Combat readout §6 ``Interrupts`` column is the count of
    :class:`InterruptEvent` rows where ``source_agent_id == player``.
    ``target_agent_id`` + ``skill_id`` carry the per-interrupt
    attribution for the future per-skill forensic layer (Phase 6
    v2 parser-stream switch yields the actual events; pre-Phase-6-v2
    streams parse cleanly because all fields fall back to ``0``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal[EventType.INTERRUPT] = EventType.INTERRUPT


# ---------------------------------------------------------------------
# Event dispatch table (Wave 6 partition refactor — Tour 5 wrap-up)
# ---------------------------------------------------------------------
#
# Wave 5 left this as a flat 12-member Annotated union under
# ``Field(discriminator="event_type")``. The empirical Pydantic v2
# discriminator-perf cliff is between 12 and 20 members; adding
# Event#13 pre-Wave-6 would have caused a per-event validation
# regression across the per-fight drill-down page fetches.
#
# Wave 6 replaces it with a Python dict-lookup dispatch +
# a per-class ``model_validate`` call wrapped via ``WrapValidator``.
# Adding Event#13+ now requires ONLY one new entry in ``_EVENT_MAP``
# (NO union-membership change, NO consumer-side update, NO schema
# bump for existing JSONL blobs). The POST-Wave-5 FORBIDDEN clause is
# RESOLVED by this dispatch-table design.
_EVENT_MAP: dict[EventType, type[BaseEvent]] = {
    EventType.DAMAGE: DamageEvent,
    EventType.HEALING: HealingEvent,
    EventType.BUFF_REMOVAL: BuffRemovalEvent,
    EventType.BOON_APPLY: BoonApplyEvent,
    EventType.CC: CCEvent,
    EventType.CONDITION_REMOVE: ConditionRemoveEvent,
    EventType.DOWN: DownEvent,
    EventType.DEATH: DeathEvent,
    EventType.STUN_BREAK: StunBreakEvent,
    EventType.BARRIER: BarrierEvent,
    EventType.DODGE: DodgeEvent,
    EventType.BLOCK: BlockEvent,
    EventType.INTERRUPT: InterruptEvent,
}


def _dispatch_event(
    v: Any,
    handler: Any,
) -> BaseEvent:
    """WrapValidator routing via the ``_EVENT_MAP`` dict for O(1) dispatch.

    Steps: (1) read ``event_type`` from raw input dict; (2) map to the
    subclass via ``_EVENT_MAP[et]``; (3) call ``cls.model_validate(v)``;
    (4) fall through to ``handler(v)`` on unknown ``event_type``. The
    fall-through preserves the ``ValidationError`` contract on unknown
    event_type values (the
    ``test_unknown_event_type_raises_validation_error`` regression).
    """
    if isinstance(v, dict):
        et_str = v.get("event_type")
        if et_str is not None:
            try:
                et = EventType(et_str)
            except ValueError:
                pass  # unknown enum: fall through to handler
            else:
                cls = _EVENT_MAP.get(et)
                if cls is not None:
                    return cls.model_validate(v)
    return cast(BaseEvent, handler(v))


# Discriminated routing for forward-compat downstream consumers that
# accept "any event" (the EventWindowAggregator + the JSONL round-trip
# in apps/api/services). The routing mechanism is a Python-dict
# dispatch table (``_EVENT_MAP``) wired through ``WrapValidator`` for
# O(1) lookup (vs Pydantic v2 discriminator linear-scan at N >= 12).
# Declared via the PEP 695 ``type`` statement (Python 3.12+); mypy
# treats the right-hand side as a type expression without `# type: ignore`.
#
# Wave 6 partition refactor (Tour 5 wrap-up): the FORBIDDEN-on-13th-
# member clause is RESOLVED. Adding Event#13+ now requires ONLY one
# new entry in ``_EVENT_MAP`` (no union-membership change, no
# consumer-side update). Wire compatibility: preserved (JSONL lines
# without explicit ``category`` field still validate correctly via the
# ``event_type`` discriminator).
type Event = Annotated[BaseEvent, WrapValidator(_dispatch_event)]
# PEP 695 type statement; mypy accepts at the type-expression slot
# See _EVENT_MAP + _dispatch_event (above) for the O(1) dispatch table.


# ---------------------------------------------------------------------------
# API-data models (gw2 v2 REST API surface -- consumed by gw2_api_client
# + gw2_analytics for cross-fight enrichment via the v2 worlds index)
# ---------------------------------------------------------------------------


class AccountInfo(BaseModel):
    """The authenticated GW2 account, returned by ``GET /v2/account``.

    Distinct from :class:`Agent` (arcdps EVTC agent) -- this is the
    authoritative GW2 v2 API view of the linked account.

    The model uses ``extra="ignore"`` rather than ``extra="forbid"``
    so the v2 API can grow new fields without breaking the library;
    unknown keys are silently dropped at validation time.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    #: Account GUID (e.g. ``"ABC12345-1234-5678-9ABC-DEF123456789"``).
    id: str = Field(..., min_length=1)
    #: Account name (no ``:`` prefix -- this is the v2 API convention,
    #: not arcdps, so analytics has to add the prefix when joining).
    name: str = Field(..., min_length=1)
    #: World the account is currently on. Renamed ``world`` -> ``world_id``
    #: via Pydantic ``alias`` so the surface uses the analyst-friendly
    #: name while the wire format stays aligned with the API.
    world_id: int = Field(..., alias="world", ge=1)


class WorldInfo(BaseModel):
    """One world record, returned by ``GET /v2/worlds[?ids=...]``.

    Distinct from ``AccountInfo.world_id`` -- ``WorldInfo`` describes
    ONE world (id + name + population); ``AccountInfo`` references one
    by its ``world_id`` foreign key.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1)
    population: Population


__all__ = [
    "_EVENT_MAP",
    "AccountInfo",
    "Agent",
    "BarrierEvent",
    "BaseEvent",
    "BlockEvent",
    "BoonApplyEvent",
    "BuffRemovalEvent",
    "CCEvent",
    "ConditionRemoveEvent",
    "DamageEvent",
    "DeathEvent",
    "DodgeEvent",
    "DownEvent",
    "EliteSpec",
    "Event",
    "EventType",
    "EvtcHeader",
    "Fight",
    "GameType",
    "HealingEvent",
    "InterruptEvent",
    "Population",
    "Profession",
    "Skill",
    "StunBreakEvent",
    "WorldInfo",
    "_dispatch_event",
]
