"""Shared helper functions used across multiple route modules.

Phase 2.3: also includes helpers extracted from
:mod:`gw2analytics_api.routes.players`:
:func:`parse_profession_filter` and :func:`profile_to_list_row`.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from gw2_analytics.player_profile import PlayerProfile
from gw2_analytics.role_detection import detect_role_lite
from gw2_core import EliteSpec, Profession
from gw2analytics_api.schemas import PlayerListRowOut


def format_profession(profession: Profession | int) -> str:
    """Map a profession to its wire-format label.

    Returns the profession's display name (e.g. ``"Guardian"``,
    ``"Warrior"``) for known core professions, ``"UNKNOWN"`` for
    value 0, and ``"PROF(N)"`` for unknown profession IDs (the
    fallback for future professions not yet in the ``Profession``
    enum).
    """
    v = profession.value if isinstance(profession, Profession) else int(profession)
    if v == 0:
        return "UNKNOWN"
    try:
        return Profession(v).name.title()
    except (ValueError, KeyError):
        return f"PROF({v})"


def format_elite_spec(elite: EliteSpec | int) -> str:
    """Map an elite spec to its wire-format label.

    Returns the spec's display name (e.g. ``"Spellbreaker"``,
    ``"Firebrand"``) for known elite specializations, ``"BASE"``
    for the core profession (value 0), and ``"ELITE(N)"`` for
    unknown elite spec IDs.
    """
    v = elite.value if isinstance(elite, EliteSpec) else int(elite)
    if v == 0:
        return "BASE"
    try:
        return EliteSpec(v).name.title()
    except (ValueError, KeyError):
        return f"ELITE({v})"


# ---------------------------------------------------------------------------
# Extracted from routes/players.py (Phase 2.3)
# ---------------------------------------------------------------------------


def parse_profession_filter(value: str) -> Profession | None:
    """Parse the ``?profession=`` query param into a :class:`Profession` enum.

    Accepts BOTH the enum NAME (e.g. ``"MESMER"``, case-insensitive)
    AND the integer value (e.g. ``"7"``). An empty string is the
    "no filter" sentinel. An unrecognised value surfaces as 422.
    """
    if not value:
        return None
    try:
        return Profession[value.upper()]
    except KeyError:
        pass
    try:
        return Profession(int(value))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown profession: {value!r} (expected name like 'MESMER' or integer 0-9)",
        ) from exc


def profile_to_list_row(p: PlayerProfile) -> PlayerListRowOut:
    """Build a :class:`PlayerListRowOut` with cross-fight role detection."""
    detected_role, detected_tags = detect_role_lite(
        total_damage=p.total_damage,
        total_healing=p.total_healing,
        total_buff_removal=p.total_buff_removal,
        profession_int=int(p.profession),
        elite_spec_int=int(p.elite),
    )
    return PlayerListRowOut(
        account_name=p.account_name,
        name=p.name,
        profession=format_profession_label(p.profession),
        elite_spec=format_elite_label(p.elite),
        fights_attended=p.fights_attended,
        total_damage=p.total_damage,
        total_healing=p.total_healing,
        total_buff_removal=p.total_buff_removal,
        detected_role=detected_role,
        detected_tags=detected_tags,
    )


def format_profession_label(profession: Profession) -> str:
    """Wire-format label. Delegates to :func:`format_profession`."""
    return format_profession(profession)


def format_elite_label(elite: EliteSpec) -> str:
    """Wire-format label. Delegates to :func:`format_elite_spec`."""
    return format_elite_spec(elite)


__all__ = [
    "format_elite_label",
    "format_elite_spec",
    "format_profession",
    "format_profession_label",
    "parse_profession_filter",
    "profile_to_list_row",
]
