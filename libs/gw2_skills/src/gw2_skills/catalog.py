"""In-memory GW2 skills catalog with NDJSON load + lookup methods.

Layer-separation: this module owns the catalog lookup path. It does
NOT import from ``gw2_analytics`` (a foundational-vs-analytics
hierarchy). The catalog may be empty on a fresh install -- callers
must handle None / [] returns gracefully.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from gw2_core import Profession
from gw2_skills.models import SkillEntry

#: Default NDJSON file shipped inside the package (placeholder, empty by default).
_DEFAULT_CATALOG_PATH: Final[Path] = Path(__file__).parent / "data" / "gw2_skills.ndjson"


class SkillCatalog:
    """In-memory GW2 skills catalog with O(1) id lookup + profession-keyed index.

    Empty-catalog invariant: a catalog with no entries returns None /
    [] for all lookup methods. Callers can rely on this without wrapping
    their access in if/else.
    """

    __slots__ = ("_id_frozenset", "_skills_by_id", "_skills_by_profession")

    def __init__(self) -> None:
        self._skills_by_id: dict[int, SkillEntry] = {}
        self._skills_by_profession: dict[Profession, list[SkillEntry]] = {}
        self._id_frozenset: frozenset[int] = frozenset()

    def load(self, path: Path | str | None = None) -> int:
        """Load NDJSON from ``path`` (defaults to the package-shipped file).

        Returns the number of entries actually loaded (0 if the file
        is missing or empty).

        Silently skips malformed lines (no NDJSON parse error surfaces
        to the caller; the catalog just has fewer entries).
        """
        target = Path(path) if path is not None else _DEFAULT_CATALOG_PATH
        if not target.exists():
            return 0
        loaded = 0
        with target.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                # PLW2901: don't reassign the loop variable.
                # The original ``line = line.strip()`` pattern
                # triggered ruff PLW2901 (redefined-loop-name)
                # because the for-loop target was overwritten
                # inside the loop body. Rebinding to a fresh
                # ``line`` keeps the loop idiom intact without
                # the lint complaint.
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = SkillEntry.model_validate(data)
                except (json.JSONDecodeError, ValueError):
                    # Skip the malformed line rather than
                    # aborting the whole catalog load. The
                    # watchdog re-run on the next
                    # ``load_catalog`` call will surface the
                    # same malformed line (idempotent); the SLA
                    # bars the catalog load from crashing on a
                    # single bad row.
                    continue
                self._add_entry(entry)
                loaded += 1
        self._id_frozenset = frozenset(self._skills_by_id.keys())
        return loaded

    def add(self, entry: SkillEntry) -> None:
        """Add a single entry (rebuilds the membership frozenset)."""
        self._add_entry(entry)
        self._id_frozenset = frozenset(self._skills_by_id.keys())

    def _add_entry(self, entry: SkillEntry) -> None:
        self._skills_by_id[entry.id] = entry
        if entry.profession is not None:
            self._skills_by_profession.setdefault(entry.profession, []).append(entry)

    def find_skill_by_id(self, id: int) -> SkillEntry | None:
        """Lookup by arcdps skill id. O(1)."""
        return self._skills_by_id.get(id)

    def find_skills_by_profession(self, profession: Profession) -> list[SkillEntry]:
        """Lookup by owning profession. Returns a defensive copy."""
        return list(self._skills_by_profession.get(profession, ()))

    def __len__(self) -> int:
        return len(self._skills_by_id)

    def __contains__(self, id: object) -> bool:
        return isinstance(id, int) and id in self._id_frozenset


def find_skill_by_id(catalog: SkillCatalog, id: int) -> SkillEntry | None:
    """Top-level convenience wrapper."""
    return catalog.find_skill_by_id(id)


def find_skills_by_profession(catalog: SkillCatalog, profession: Profession) -> list[SkillEntry]:
    """Top-level convenience wrapper."""
    return catalog.find_skills_by_profession(profession)


__all__ = ["SkillCatalog", "find_skill_by_id", "find_skills_by_profession"]
