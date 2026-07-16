"""Unit tests for the in-memory GW2 skills catalog."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from gw2_core import Profession

from gw2_skills.catalog import SkillCatalog, find_skill_by_id, find_skills_by_profession
from gw2_skills.models import SkillEntry


def test_find_skill_by_id_empty_catalog_returns_none() -> None:
    """Empty catalog: find_by_id returns None, not an exception."""
    catalog = SkillCatalog()
    assert catalog.find_skill_by_id(12345) is None


def test_find_skills_by_profession_empty_catalog_returns_empty_list() -> None:
    """Empty catalog: profession lookup returns empty list."""
    catalog = SkillCatalog()
    assert catalog.find_skills_by_profession(Profession.GUARDIAN) == []


def test_len_returns_skill_count() -> None:
    """len() returns the entry count."""
    catalog = SkillCatalog()
    catalog.add(SkillEntry(id=1, name="Fireball", profession=Profession.ELEMENTALIST))
    catalog.add(SkillEntry(id=2, name="Healing Spring", profession=Profession.ELEMENTALIST))
    catalog.add(SkillEntry(id=3, name="Whirlwind", profession=Profession.WARRIOR))
    assert len(catalog) == 3


def test_contains_supports_membership() -> None:
    """``id in catalog`` returns True/False correctly via frozenset-backed membership."""
    catalog = SkillCatalog()
    catalog.add(SkillEntry(id=12345, name="Test Skill"))
    assert 12345 in catalog
    assert 99999 not in catalog


def test_load_catalog_from_ndjson_with_three_entries(tmp_path: Path) -> None:
    """End-to-end: write 3-line NDJSON, load, verify lookups."""
    catalog = SkillCatalog()
    rows = [
        {"id": 10, "name": "Test Skill A", "profession": Profession.GUARDIAN.value, "is_elite": False},
        {"id": 20, "name": "Test Skill B", "profession": Profession.WARRIOR.value, "is_elite": True},
        {"id": 30, "name": "Test Skill C", "profession": None, "is_elite": False},
    ]
    ndjson_path = tmp_path / "skills.ndjson"
    ndjson_path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    loaded = catalog.load(ndjson_path)
    assert loaded == 3
    assert catalog.find_skill_by_id(10) is not None
    assert catalog.find_skill_by_id(10).name == "Test Skill A"
    assert catalog.find_skills_by_profession(Profession.GUARDIAN)[0].id == 10
    assert catalog.find_skills_by_profession(Profession.MESMER) == []


def test_find_skill_by_id_returns_none_for_missing_id() -> None:
    """Rename of the old `test_malformed_ndjson_line_skipped`; this test now
    correctly describes what it actually exercises (the missing-id path,
    NOT the malformed-NDJSON path -- that coverage lives in the next test).
    """
    catalog = SkillCatalog()
    catalog.add(SkillEntry(id=1, name="Good", profession=Profession.RANGER))
    assert catalog.find_skill_by_id(1) is not None
    assert catalog.find_skill_by_id(99999) is None


def test_load_ndjson_skips_malformed_lines_silently(tmp_path: Path) -> None:
    """NDJSON lines that fail JSON parsing or Pydantic validation are silently
    skipped -- no exception surfaces. The catalog is still queryable for the
    valid entries.
    """
    catalog = SkillCatalog()
    ndjson_path = tmp_path / "skills.ndjson"
    ndjson_path.write_text(
        # Line 1: valid. Line 2: garbage JSON -- skipped. Line 3: valid with null profession.
        '{"id": 10, "name": "Valid Skill A", "profession": 1}\n'
        "{ this is not valid json}\n"
        '{"id": 30, "name": "Valid Skill B", "profession": null}\n',
        encoding="utf-8",
    )
    loaded = catalog.load(ndjson_path)
    assert loaded == 2  # only the 2 valid lines counted
    assert catalog.find_skill_by_id(10) is not None
    assert catalog.find_skill_by_id(10).name == "Valid Skill A"
    assert catalog.find_skill_by_id(30) is not None
    assert catalog.find_skill_by_id(30).profession is None
