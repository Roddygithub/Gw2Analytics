"""Shared helper functions used across multiple route modules."""

from __future__ import annotations

from gw2_core import EliteSpec, Profession


def format_profession(profession: Profession | int) -> str:
    """Map a profession to its wire-format label."""
    v = profession.value if isinstance(profession, Profession) else int(profession)
    return "UNKNOWN" if v == 0 else f"PROF({v})"


def format_elite_spec(elite: EliteSpec | int) -> str:
    """Map an elite spec to its wire-format label.

    Returns the spec's display name (e.g. ``"Spellbreaker"``,
    ``"Firebrand"``) for known elite specializations, ``"BASE"``
    for the core profession (value 0), and ``"ELITE(N)"`` for
    unknown elite spec IDs.

    Collision note: two elite spec IDs collide (55 = Daredevil/Soulbeast,
    63 = Renegade/Weaver). The parser disambiguates via
    :func:`gw2_core.disambiguate_elite_spec` before the value
    reaches the DB; the disambiguation uses the agent's
    profession, so the correct spec name appears at read time.
    When called with a raw ``int`` (e.g. from tests), the Python
    ``IntEnum`` returns the first-defined member for the
    duplicate value (Daredevil for 55, Renegade for 63), which
    is the best-effort visible label.
    """
    v = elite.value if isinstance(elite, EliteSpec) else int(elite)
    if v == 0:
        return "BASE"
    try:
        return EliteSpec(v).name.title()
    except (ValueError, KeyError):
        return f"ELITE({v})"
