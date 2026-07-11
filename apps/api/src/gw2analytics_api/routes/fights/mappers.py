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
(plan 021). The 3 functions each perform a single small query on
the per-fight ``OrmFightAgent`` / ``OrmFightSkill`` table
(typically 5-50 rows per fight; no N+1 risk at this row count).

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

from sqlalchemy import select
from sqlalchemy.orm import Session

from gw2analytics_api.models import OrmFightAgent, OrmFightSkill


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


__all__ = ["agent_id_to_name", "agent_id_to_subgroup", "skill_id_to_name"]
