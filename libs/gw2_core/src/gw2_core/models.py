"""Pydantic models for GW2 combat data.

This module is the **stable internal data model** of the application.
Nothing else may import from another domain to define a model. Other
packages may only consume or produce these shapes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum

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
    incomplete — unknown values fall back to :attr:`UNKNOWN` at parse time.

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


# ---------------------------------------------------------------------------
# Models
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
    skill_count: int = Field(default=0, ge=0, le=10_000)


class Agent(BaseModel):
    """One entity (player, NPC or gadget) observed during the fight."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int = Field(..., ge=0, description="arcdps pointer-sized agent id (uint64).")
    name: str = Field(..., min_length=0, max_length=64)
    profession: Profession = Profession.UNKNOWN
    elite: EliteSpec = EliteSpec.UNKNOWN
    elite_raw: int = Field(
        default=0, ge=0, le=0xFFFFFFFF, description="Raw elite byte for forensics."
    )
    is_player: bool = Field(default=False)


class Skill(BaseModel):
    """One skill/buff used or referenced during the fight.

    V0 keeps this contract minimal — the parser does not yet expand skill
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


__all__ = [
    "Agent",
    "EliteSpec",
    "EvtcHeader",
    "Fight",
    "GameType",
    "Profession",
    "Skill",
]
