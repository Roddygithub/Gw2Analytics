"""In-memory GW2 skills catalog with NDJSON load + lookup methods.

Layer-separation: this module owns the catalog lookup path. It does
NOT import from ``gw2_analytics`` (a foundational-vs-analytics
hierarchy). The catalog may be empty on a fresh install -- callers
must handle None / [] returns gracefully.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Final

from gw2_core import Profession
from gw2_skills.models import SkillEntry

_log = logging.getLogger(__name__)

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

        v0.10.26-pre: malformed rows are now LOGGED at DEBUG level
        (per-row, capped by logged message count) + a final WARNING
        summary at the end of ``load_with_stats``. The ``SLA bars
        the catalog load from crashing on a single bad row`` invariant
        is preserved (logged, not raised). Prefer
        :meth:`load_with_stats` for production observability.
        """
        loaded, _skipped = self.load_with_stats(path)
        return loaded

    def load_with_stats(self, path: Path | str | None = None) -> tuple[int, int]:
        """Same as :meth:`load` but returns ``(loaded, skipped)`` tuple.

        Production smoke-test + observability variant: lets the FastAPI
        lifespan handler log catalog drift (some NDJSON entries may
        be silently skipped due to Pydantic validation errors -- see
        :class:`SkillEntry._accept_profession_aliases` validator).

        Empty-tracker behaviour: per-row skip events log at DEBUG
        level (operator-friendly on stdout, batch-summary below);
        a single WARNING at end of load if any rows were skipped.
        """
        target = Path(path) if path is not None else _DEFAULT_CATALOG_PATH
        if not target.exists():
            return (0, 0)
        loaded = 0
        skipped = 0
        with target.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                # PLW2901: don't reassign the loop variable.
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = SkillEntry.model_validate(data)
                except (json.JSONDecodeError, ValueError) as exc:
                    skipped += 1
                    _log.debug(
                        "skills catalog: skipped malformed line %d in %s (%s): %s",
                        skipped,
                        target.name,
                        type(exc).__name__,
                        exc,
                    )
                    continue
                self._add_entry(entry)
                loaded += 1
        self._id_frozenset = frozenset(self._skills_by_id.keys())
        if skipped > 0:
            _log.warning(
                "skills catalog: loaded %d entries, skipped %d rows "
                "(see DEBUG log for per-row details). Source: %s",
                loaded,
                skipped,
                target,
            )
        return (loaded, skipped)

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


def load_with_stats(path: Path | str | None = None) -> tuple[int, int]:
    """Functional wrapper around :meth:`SkillCatalog.load_with_stats`.

    SDK callers (CLI tools, Jupyter notebooks) who don't want to
    instantiate a catalog just to load can call this directly:

    >>> from gw2_skills.catalog import load_with_stats
    >>> loaded, skipped = load_with_stats("/path/to/catalog.ndjson")

    Returns ``(loaded, skipped)`` tuple -- see
    :meth:`SkillCatalog.load_with_stats` for the contract.
    """
    return SkillCatalog().load_with_stats(path)


__all__ = [
    "SkillCatalog",
    "find_skill_by_id",
    "find_skills_by_profession",
    "load_with_stats",
]
