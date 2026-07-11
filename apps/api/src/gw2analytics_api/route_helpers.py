"""Shared helper functions used across multiple route modules."""

from __future__ import annotations

from gw2_core import EliteSpec, Profession


def format_profession(profession: Profession | int) -> str:
    """Map a profession to its wire-format label."""
    v = profession.value if isinstance(profession, Profession) else int(profession)
    return "UNKNOWN" if v == 0 else f"PROF({v})"


def format_elite_spec(elite: EliteSpec | int) -> str:
    """Map an elite spec to its wire-format label."""
    v = elite.value if isinstance(elite, EliteSpec) else int(elite)
    return "BASE" if v == 0 else f"ELITE({v})"
