"""Canonical per-fight ORM-to-aggregation-dict mappers.

Pure ``SQLAlchemy`` / ORM-layer helpers that build the
``agent_id`` + ``skill_id`` attribution maps for the per-target
trio + the per-subgroup + the per-skill aggregators. Originally
inlined as 3 dict-comp loop blocks in
:mod:`gw2analytics_api.routes.fights.__init__` pre-A2 god-module
refactor. They live in a dedicated submodule here so the FastAPI
route handlers don't carry ORM-layer concerns.

Provenance
----------

Extracted in PR 2 sub-commit 1 of the A2 god-module refactor
(plan 021). The 4 functions each perform a single small query on
the per-fight ``OrmFightAgent`` / ``OrmFightSkill`` table
(typically 5-50 rows per fight; no N+1 risk at this row count).
Tour 6 v0.10.24 added :class:`AgentIdentity` + :func:`agent_id_to_identity`
to close the Wave 5 SCAFFOLD NIT-placeholder gap on the 5 shared
identity columns.

The 4th ORM query -- :func:`apps.api.routes.fights.get_fight_player_timeline`'s
inline ``agents: list[OrmFightAgent] = list(...)`` -- is kept in
the route handler because it returns a list of ORM instances
(not a dict for an aggregator). The aggregator's source-side
attribution filter reads 4 attributes via ``getattr`` so the
SQLAlchemy ORM instances are a drop-in match; extracting them
to a separate ``agents_for_fight()`` would just defer the
iteration target type without adding hermeticity.

Public surface
==============

- :func:`agent_id_to_name` -- per-fight ``OrmFightAgent`` ->
  ``name`` map (player-name denormalisation for the per-target
  trio roll-ups).
- :func:`agent_id_to_subgroup` -- per-fight ``OrmFightAgent`` ->
  ``subgroup`` map (per-subgroup rollup source-side attribution).
- :func:`skill_id_to_name` -- per-fight ``OrmFightSkill`` ->
  ``skill_name`` map (per-skill rollup).
- :class:`AgentIdentity` -- Tour 6 v0.10.24 close-out: the per-
  player Combat-readout identity slice (subgroup integer label +
  stripped name + account_name + formatted profession + elite
  spec + ``is_commander`` flag derived from the arcdps
  ``\" [CMDR]\"`` name-tag).
- :func:`agent_id_to_identity` -- Tour 6 v0.10.24 close-out:
  per-fight ``OrmFightAgent`` -> ``AgentIdentity`` map (filter
  to ``is_player=True`` so the map keys are exclusively player
  agent_ids; the dispatcher intersects this map with the union
  of per-aspect aggregator rows so NPC defense targets are
  silently dropped from the envelope per the design doc §2
  PLAYER-only contract).

Test monkeypatch contract (READ BEFORE PATCHING)
================================================

These helpers' SQLAlchemy queries resolve the model classes via
THIS module's namespace (NOT via ``routes.fights.__init__``'s).
Tests MUST monkeypatch
``gw2analytics_api.routes.fights.mappers.OrmFightAgent`` /
``OrmFightSkill`` directly when patching the model attribute
(the A2 PR 1 + PR 1.1 established a similar contract on
``routes.fights.blob_cache.get_events``; the pattern is the
same -- test patches via the SUBMODULE's namespace where the
call site resolves the symbol, NOT via the package namespace).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from gw2analytics_api.models import OrmFightAgent, OrmFightSkill
from gw2analytics_api.route_helpers import format_elite_spec, format_profession


def agent_id_to_name(db: Session, fight_id: str) -> dict[int, str | None]:
    """Build the per-fight ``agent_id`` -> ``name`` map.

    Single small query on :class:`OrmFightAgent` (typically 5-50
    rows per fight; no N+1). ``OrmFightAgent.name`` is non-null
    in practice but the schema permits ``None``; the type uses
    ``str | None`` so the per-target aggregators' ``.get(target)``
    returns ``None`` for NPCs without a registered arcdps
    char-name (explicit-``None`` and missing-key collapse to the
    same sentinel on the wire payload; the frontend falls back to
    the raw ``target_agent_id`` for).

    Consistency invariant: same ``agent_id`` == same ``name``
    across all three per-target roll-ups (the trio share this
    map as a single source-of-truth -- if a target appears in
    the damage roll-up AND the healing roll-up, it resolves to
    the SAME name on both rows).
    """
    return {
        a.agent_id: a.name
        for a in db.execute(
            select(OrmFightAgent).where(OrmFightAgent.fight_id == fight_id),
        )
        .scalars()
        .all()
    }


def agent_id_to_subgroup(db: Session, fight_id: str) -> dict[int, str]:
    """Build the per-fight ``agent_id`` -> ``subgroup`` map.

    Single small query on :class:`OrmFightAgent`. An empty subgroup
    is a valid value (collapses to ``""`` on the wire payload; the
    per-subgroup aggregator surfaces it in the empty-string bucket
    so a player without an assigned subgroup still rolls up to a
    visible bucket).
    """
    return {
        a.agent_id: (a.subgroup or "")
        for a in db.execute(
            select(OrmFightAgent).where(OrmFightAgent.fight_id == fight_id),
        )
        .scalars()
        .all()
    }


def skill_id_to_name(db: Session, fight_id: str) -> dict[int, str]:
    """Build the per-fight ``skill_id`` -> ``skill_name`` map.

    Single small query on :class:`OrmFightSkill`. Empty skill
    names are valid (the parser surfaces them for unknown skill
    IDs); the per-skill aggregator renders them as
    ``skill_name=""``.
    """
    return {
        s.skill_id: (s.name or "")
        for s in db.execute(
            select(OrmFightSkill).where(OrmFightSkill.fight_id == fight_id),
        )
        .scalars()
        .all()
    }


# Public surface lives ABOVE the new Combat-readout identity
# helpers added in Tour 6 v0.10.24. The __all__ block enumerates
# the module's stable re-export surface for grep-ability +
# future maintainer onboarding.
__all__ = [
    "AgentIdentity",
    "agent_id_to_identity",
    "agent_id_to_name",
    "agent_id_to_subgroup",
    "skill_id_to_name",
]


class AgentIdentity(BaseModel):
    """One player's Combat-readout identity slice (Tour 6 v0.10.24).

    Hydrated from :class:`OrmFightAgent`. The Combat readout's 5
    shared identity columns (per ``docs/v0.9.0-combat-readout-design.md``
    §2) populate from this slice: ``subgroup`` (integer label) +
    ``name`` (player char-name) + ``account_name`` (player account
    GUID with the leading ``:`` arcdps prefix stripped) +
    ``profession`` + ``elite_spec`` (both formatted via
    :func:`format_profession` / :func:`format_elite_spec` from
    :mod:`gw2analytics_api.route_helpers`) + ``is_commander``
    (the arcdps ``[CMDR]`` name-tag sentinel).

    The commander-flag derivation is the arcdps ``[CMDR]`` name-tag
    detection: arcdps writes a commander-flagged agent name as
    ``"Char Name [CMDR]"`` and an otherwise-equivalent non-commander
    as ``"Char Name"``. The :class:`bls.OrmFightAgent` table does NOT
    carry a dedicated ``is_commander`` column for v0.10.24 (the
    parser-side ``commander_tag`` byte is a v0.11.0 ticket per the
    Wave 5 SCAFFOLD charter); until then the name-tag heuristic is
    the canonical source. The :class:`AgentIdentity` strips the
    suffix from the wire-shape ``name`` field so the commander
    status lives on the dedicated ``is_commander: bool`` flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: int
    name: str
    subgroup: int
    account_name: str | None
    profession: str
    elite_spec: str
    is_player: bool
    is_commander: bool


def _parse_subgroup_label(subgroup: str | None) -> int:
    """Parse an arcdps subgroup string to its integer label.

    arcdps writes the subgroup in one of three formats:

    * ``"Subgroup N"`` (canonical 2024+ format)
    * ``"Sub N"`` (legacy 2018-2023 format)
    * ``"N"`` (plain integer string — the format written by the
      EVTC parser into the database ``OrmFightAgent.subgroup``
      column when the source EVTC carries a bare integer subgroup
      field).

    An empty / ``None`` subgroup OR a non-numeric string collapses
    to ``0`` (the canonical wire-shape "no subgroup assigned"
    sentinel). The parse tries the plain-integer fast-path first,
    then falls back to whitespace-token extraction so a malformed
    subgroup like ``"Subgroup A"`` returns ``0`` rather than
    raising -- a misconfigured parser would otherwise crash the
    readout envelope.
    """
    if not subgroup:
        return 0
    # Fast path: plain integer string ("7", "12", etc.)
    try:
        return int(subgroup)
    except ValueError:
        pass
    # Fallback: "Sub N" or "Subgroup N" format
    tokens = subgroup.split()
    if len(tokens) < 2:
        return 0
    try:
        return int(tokens[-1])
    except ValueError:
        return 0


def _is_commander_from_name(name: str | None) -> bool:
    """Derive the commander flag from the arcdps ``[CMDR]`` name-tag suffix.

    The heuristic: name ``endswith`` ``" [CMDR]"`` (with the
    whitespace token prefix). The pre-Phase-C path is documented in
    the PlayerReadoutOut schema docstring.
    """
    if not name:
        return False
    return name.endswith(" [CMDR]")


def _strip_commander_tag(name: str | None) -> str:
    """Strip the trailing `` [CMDR]`` arcdps name-tag from the wire-shape name.

    The arcdps convention suffixes ``"Char Name [CMDR]"`` when the
    agent is flagged as commander; the Combat readout wire-shape
    renders the commander status on the separate ``is_commander``
    bool field, so the name is stripped to read naturally.
    ``None`` / empty name collapses to ``""``.
    """
    if not name:
        return ""
    if name.endswith(" [CMDR]"):
        return name[: -len(" [CMDR]")]
    return name


def agent_id_to_identity(db: Session, fight_id: str) -> dict[int, AgentIdentity]:
    """Build the per-fight ``agent_id`` -> :class:`AgentIdentity` map.

    Filters to ``is_player=True`` so the map keys are exclusively
    player agent_ids. The dispatcher in
    :mod:`gw2analytics_api.routes.fights.aggregators` intersects this
    map with the union of the per-aspect aggregator rows so NPC
    agents in the damage-side defense roll-up are silently dropped.

    Single small query on :class:`OrmFightAgent` (typically 5-50
    rows per fight; the ``is_player`` filter cuts the candidate
    set in half for NPC-heavy fights like WvW zerg battles). The
    helper maps each row through 4 transforms:

    1. :func:`_parse_subgroup_label` for the integer subgroup column.
    2. :func:`_is_commander_from_name` for the
       arcdps ``[CMDR]`` name-tag detection.
    3. :func:`_strip_commander_tag` for the wire-shape
       name (the commander status moves to a separate boolean).
    4. :func:`format_profession` + :func:`format_elite_spec` from
       :mod:`gw2analytics_api.route_helpers` for the wire-shape
       profession + elite_spec strings.
    """
    return {
        a.agent_id: AgentIdentity(
            agent_id=a.agent_id,
            name=_strip_commander_tag(a.name),
            subgroup=_parse_subgroup_label(a.subgroup),
            account_name=a.account_name,
            profession=format_profession(a.profession),
            elite_spec=format_elite_spec(a.elite_spec),
            is_player=a.is_player,
            is_commander=_is_commander_from_name(a.name),
        )
        for a in db.execute(
            select(OrmFightAgent).where(
                OrmFightAgent.fight_id == fight_id,
                OrmFightAgent.is_player.is_(True),
            ),
        )
        .scalars()
        .all()
    }
