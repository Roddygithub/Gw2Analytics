"""Single-fight aggregations built on top of :mod:`gw2_core`.

Phase 3 starter. Aggregates a single parsed :class:`~gw2_core.Fight` into
a :class:`FightAggregate` -- a stable denormalised view of combatants
(player agents grouped by squad position), the skill catalog (the
fight's skill table), and aggregate counts.

Event-derived aggregations (target DPS, damage taken, healing, etc.)
land in a sibling module in a later phase; the public surface here is
intentionally minimal so the multi-fight aggregator and event
sub-aggregators can be added without breaking this contract.

Conventions
===========

- **Deterministic ordering.** ``combatants`` is sorted by
  ``(account_name, name)``; ``groups`` by ``subgroup``; ``skill_catalog``
  by ``Skill.id``. Two runs over the same input must yield
  byte-identical aggregate output.
- **No defaults invented.** An empty ``Fight.agents`` yields
  ``combatants=[]`` and ``groups=[]``; an empty ``Fight.skills`` yields
  ``skill_catalog=[]``. We never synthesise a placeholder row.
- **Invariants are validated at construction.** Cross-field checks
  (player + npc == agent, group combatant counts match their
  combatants, skill count matches catalog size) live in
  :meth:`SingleFightAggregator._check_invariants` so any future
  caller can rely on them -- they are not enforced by Pydantic
  field-by-field constraints alone.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from operator import attrgetter
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import EliteSpec, Fight, Profession

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CombatantSummary(BaseModel):
    """Player-roster row of a :class:`FightAggregate`.

    Distinct from :class:`~gw2_core.Agent` in three ways:

    1. ``is_player`` is implicit (always ``True`` here -- the aggregator
       never emits an NPC row).
    2. ``account_name`` is mandatory (NPCs have no account; we surface
       ``None`` from the parser here as the empty string so the schema
       stays flat -- this is the only field where we materialise a value
       rather than carry the parser's optional ``None`` through).
    3. ``subgroup`` is a string (never ``None``). The parser surfaces
       the arcdps WvW "player with empty account + non-empty subgroup"
       quirk with an empty-string account but a string subgroup; we
       preserve that flat-string semantics here.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: int = Field(..., ge=0)
    account_name: str = Field(..., min_length=1, max_length=128)
    name: str = Field(default="", max_length=128)
    profession: Profession = Profession.UNKNOWN
    elite: EliteSpec = EliteSpec.UNKNOWN
    subgroup: str = Field(default="", max_length=128)


class SkillCatalogEntry(BaseModel):
    """Row of the fight's skill-table summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int = Field(..., ge=0)
    name: str = Field(default="", max_length=256)


class GroupSummary(BaseModel):
    """Per-subgroup roll-up: how many combatants and which accounts.

    A subgroup ``""`` (no squad position assigned) is a valid group label
    and gets its own row here, mirroring the parser's empty-string
    convention.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    subgroup: str = Field(..., min_length=0, max_length=128)
    combatant_count: int = Field(..., ge=0)
    account_names: list[str] = Field(default_factory=list)


class FightAggregate(BaseModel):
    """Denormalised single-fight aggregation.

    Constructed via :meth:`SingleFightAggregator.aggregate`. The
    invariants listed on :class:`SingleFightAggregator` are
    *post-construction* validated; Pydantic's per-field constraints
    only catch ``frozen=True``, ``extra=forbid``, and ``min_length`` /
    ``ge`` / ``le`` violations.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fight_id: str = Field(..., min_length=1)
    encounter_id: int = Field(..., ge=0, le=0xFFFF)
    agent_count: int = Field(..., ge=0)
    player_count: int = Field(..., ge=0)
    npc_count: int = Field(..., ge=0)
    skill_count: int = Field(..., ge=0)
    combatants: list[CombatantSummary] = Field(default_factory=list)
    groups: list[GroupSummary] = Field(default_factory=list)
    skill_catalog: list[SkillCatalogEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


class SingleFightAggregator:
    """Stateless aggregator: input ``Fight`` -> output ``FightAggregate``.

    Instantiate once and reuse across fights -- the class holds no state.

    Invariants (enforced in :meth:`_check_invariants` after construction;
    violations raise ``ValueError``):

    - ``fight_id == input fight.id`` (``min_length=1`` enforces it
      before even reaching the aggregator; defense-in-depth recheck
      below catches the path if upstream ever bypasses validation via
      ``model_construct``).
    - ``agent_count == len(input fight.agents)``.
    - ``player_count + npc_count == agent_count``: players whose
      ``Agent.account_name`` parsed as ``None`` (the lenient-parser
      "empty account + non-empty subgroup" WvW quirk) are filtered
      out and counted under ``npc_count`` -- per-player joins
      across fights could not function without a stable identifier
      so they leave the analytics pipeline rather than silently
      mis-joining unrelated accounts.
    - ``skill_count == len(skill_catalog) == len(input fight.skills)``.
    - For every :class:`GroupSummary` ``g``:
      ``g.combatant_count == sum(1 for c in combatants if c.subgroup == g.subgroup)``.
    - Combatants ordered by ``(account_name, name)``.
    - Groups ordered by ``subgroup`` string.
    - Skill catalog ordered by ``Skill.id``.

    Future phases will add ``MultiFightAggregator`` (operates on a
    sequence of ``Fight`` records) as a sibling class in
    :mod:`gw2_analytics.multi_fight`, leaving this public surface
    untouched.
    """

    #: Sentinel returned from ``aggregate`` whenever ``fight.header`` is
    #: ``None`` (the parser only sets it on success; defensive default
    #: keeps the constructor signature stable for callers that hold a
    #: partially-populated ``Fight``).
    _DEFAULT_ENCOUNTER_ID: Final[int] = 0

    def aggregate(self, fight: Fight) -> FightAggregate:
        """Compute the aggregate for one parsed fight.

        The input ``Fight`` is not mutated (its Pydantic model is
        already frozen upstream), and the returned ``FightAggregate``
        is itself frozen, so downstream consumers can safely memoize
        or pass it across thread boundaries without a defensive copy.
        """
        if not fight.id:
            msg = "fight.id must be non-empty"
            raise ValueError(msg)

        encounter_id = (
            fight.header.encounter_id if fight.header is not None else self._DEFAULT_ENCOUNTER_ID
        )
        agent_count = len(fight.agents)
        skill_count = len(fight.skills)

        # Drop players whose account_name parsed as None (the lenient
        # parser's "empty account + non-empty subgroup" WvW quirk).
        # Without a stable account identifier these rows cannot be
        # deduped across uploads, so they leave the analytics pipeline
        # here rather than silently mis-joining unrelated accounts.
        # Use a generator to avoid the intermediate list allocation;
        # ``sorted()`` consumes it directly.
        player_rows = (a for a in fight.agents if a.is_player and a.account_name)

        combatants = sorted(
            (
                CombatantSummary(
                    agent_id=a.id,
                    account_name=a.account_name or "",
                    name=a.name,
                    profession=a.profession,
                    elite=a.elite,
                    subgroup=a.subgroup or "",
                )
                for a in player_rows
            ),
            key=attrgetter("account_name", "name"),
        )

        grouped: dict[str, list[CombatantSummary]] = defaultdict(list)
        for c in combatants:
            grouped[c.subgroup].append(c)
        groups = [
            GroupSummary(
                subgroup=subgroup,
                combatant_count=len(rows),
                account_names=sorted(c.account_name for c in rows),
            )
            for subgroup, rows in sorted(grouped.items())
        ]

        skill_catalog = [
            SkillCatalogEntry(id=s.id, name=s.name)
            for s in sorted(fight.skills, key=attrgetter("id"))
        ]

        aggregate = FightAggregate(
            fight_id=fight.id,
            encounter_id=encounter_id,
            agent_count=agent_count,
            player_count=len(combatants),
            npc_count=agent_count - len(combatants),
            skill_count=skill_count,
            combatants=combatants,
            groups=groups,
            skill_catalog=skill_catalog,
        )

        # Cross-field invariants are not enforced by Pydantic BaseModel
        # field constraints; assert them post-construction.
        self._check_invariants(aggregate)
        return aggregate

    @staticmethod
    def _check_invariants(agg: FightAggregate) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated."""
        if agg.player_count + agg.npc_count != agg.agent_count:
            msg = (
                f"player_count + npc_count ({agg.player_count + agg.npc_count}) "
                f"!= agent_count ({agg.agent_count})"
            )
            raise ValueError(msg)
        if agg.skill_count != len(agg.skill_catalog):
            msg = (
                f"skill_count ({agg.skill_count}) != len(skill_catalog) ({len(agg.skill_catalog)})"
            )
            raise ValueError(msg)
        subgroup_counts = Counter(c.subgroup for c in agg.combatants)
        for g in agg.groups:
            expected = subgroup_counts.get(g.subgroup, 0)
            if g.combatant_count != expected:
                msg = (
                    f"GroupSummary({g.subgroup!r}).combatant_count "
                    f"({g.combatant_count}) != actual combatants in that "
                    f"subgroup ({expected})"
                )
                raise ValueError(msg)


__all__ = [
    "CombatantSummary",
    "FightAggregate",
    "GroupSummary",
    "SingleFightAggregator",
    "SkillCatalogEntry",
]
