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
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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


# Discriminated union for forward-compat downstream consumers that
# accept "any event" (e.g. the EventWindowAggregator buckets damage +
# healing in one shot without forcing the caller to split the stream)
# AND for JSONL round-trip in apps/api/services (the per-fight events
# blob is a heterogeneous stream of damage + healing + buff-removal
# records written one ``model_dump_json()`` per line). The
# ``Annotated`` + ``Field(discriminator="event_type")`` combination
# tells Pydantic v2 to dispatch on the ``event_type`` literal at
# validation time, so a ``TypeAdapter(Event).validate_json(line)`` call
# materialises the matching subclass with no manual ``isinstance``
# ladder. Declared via the PEP 695 ``type`` statement (Python 3.12+)
# so mypy treats the right-hand side as a type expression without
# any ``# type: ignore``.
type Event = Annotated[
    DamageEvent | HealingEvent | BuffRemovalEvent | BoonApplyEvent | CCEvent,
    Field(discriminator="event_type"),
]  # PEP 695 type statement; mypy accepts at the type-expression slot


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
    "AccountInfo",
    "Agent",
    "BaseEvent",
    "BoonApplyEvent",
    "BuffRemovalEvent",
    "CCEvent",
    "DamageEvent",
    "EliteSpec",
    "Event",
    "EventType",
    "EvtcHeader",
    "Fight",
    "GameType",
    "HealingEvent",
    "Population",
    "Profession",
    "Skill",
    "WorldInfo",
]
