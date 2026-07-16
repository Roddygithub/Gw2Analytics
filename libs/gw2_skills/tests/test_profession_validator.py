"""v0.10.26-pre: profession-name validator + load_with_stats coverage."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from gw2_skills.catalog import SkillCatalog
from gw2_skills.models import SkillEntry
from pydantic import ValidationError

from gw2_core import Profession


def test_profession_accepts_canonical_enum() -> None:
    e = SkillEntry(id=1, name="X", profession=Profession.ELEMENTALIST)
    assert e.profession is Profession.ELEMENTALIST


def test_profession_accepts_int() -> None:
    e = SkillEntry(id=1, name="X", profession=6)
    assert e.profession is Profession.ELEMENTALIST


def test_profession_accepts_str_uppercase() -> None:
    e = SkillEntry(id=1, name="X", profession="ELEMENTALIST")
    assert e.profession is Profession.ELEMENTALIST


def test_profession_accepts_str_mixed_case() -> None:
    """``Elementalist`` -> ``ELEMENTALIST`` member via validator.upper()."""
    e = SkillEntry(id=1, name="X", profession="Elementalist")
    assert e.profession is Profession.ELEMENTALIST


def test_profession_unknown_str_raises() -> None:
    with pytest.raises(ValidationError):
        SkillEntry(id=1, name="X", profession="NotAProfession")


def test_profession_unknown_int_raises() -> None:
    with pytest.raises(ValidationError):
        SkillEntry(id=1, name="X", profession=999)


def test_profession_none_is_allowed() -> None:
    e = SkillEntry(id=1, name="X")
    assert e.profession is None


def test_profession_bool_is_rejected() -> None:
    """Python quirk: ``True`` is ``isinstance(True, int)``; deny explicitly."""
    with pytest.raises(ValidationError):
        SkillEntry(id=1, name="X", profession=True)


def test_load_with_stats_returns_tuple() -> None:
    bad_data = (
        '{"id": 99999, "name": "BadProf", "profession": "NotAProf",'
        ' "is_elite": false, "skill_type": "boon"}\n'
        '{"id": 99998, "name": "GoodStr", "profession": "Elementalist",'
        ' "is_elite": false, "skill_type": "utility"}\n'
        '{"id": 99997, "name": "GoodInt", "profession": 6,'
        ' "is_elite": false, "skill_type": "utility"}\n'
        '{"id": 99996, "name": "GoodNone", "is_elite": false,'
        ' "skill_type": "boon"}\n'
    )
    with tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False) as f:
        f.write(bad_data)
        path = Path(f.name)
    c = SkillCatalog()
    loaded, skipped = c.load_with_stats(path)
    assert loaded == 3
    assert skipped == 1
    # ``find_skill_by_id`` returns ``SkillEntry | None``; assert non-None
    # before the .profession access (mypy type-safety + future-proof
    # against an empty catalog dropping IDs).
    skill = c.find_skill_by_id(99998)
    assert skill is not None
    assert skill.profession is Profession.ELEMENTALIST
    path.unlink()


def test_load_with_stats_empty_file() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False) as f:
        f.write("")
        path = Path(f.name)
    c = SkillCatalog()
    assert c.load_with_stats(path) == (0, 0)
    path.unlink()
