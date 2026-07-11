"""Hermetic tests for :mod:`gw2_analytics.sidecar` (v0.10.5 plan 136).

The 3 plan-spec tests (inline sidecar, sibling sidecar, no sidecar).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from gw2_analytics.sidecar import (
    merge_sidecar_into_summary,
    probe,
)


class _FakeSummary:
    """Minimal stand-in for OrmFightPlayerSummary."""

    def __init__(self, account_name: str) -> None:
        self.account_name = account_name
        self.healing_by_skill: dict[str, int] | None = None
        self.barrier_by_skill: dict[str, int] | None = None


def _make_zevtc_with_inline(tmp_path: Path, sidecar: dict[str, Any]) -> Path:
    """Create a .zevtc zip containing an sidecar JSON entry."""
    path = tmp_path / "fight.zevtc"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("fight.evtc", b"EVTC")
        zf.writestr("fight.healing.json", json.dumps(sidecar))
    return path


def test_probe_finds_inline_sidecar(tmp_path: Path) -> None:
    """Plan 136 spec test 1: inline JSON inside .zevtc is found."""
    sidecar = {
        "players": {
            ":account.1234": {
                "healingBySkill": {"12345": 1500, "12346": 300},
            }
        }
    }
    path = _make_zevtc_with_inline(tmp_path, sidecar)
    result = probe(path)
    assert result == sidecar


def test_probe_finds_sibling_sidecar(tmp_path: Path) -> None:
    """Plan 136 spec test 2: sibling .healing.json file is found."""
    sidecar = {
        "players": {
            ":account.1234": {
                "healingBySkill": {"12345": 2000},
            }
        }
    }
    zevtc = tmp_path / "fight.zevtc"
    with zipfile.ZipFile(zevtc, "w") as zf:
        zf.writestr("fight.evtc", b"EVTC")
    (tmp_path / "fight.healing.json").write_text(json.dumps(sidecar))
    result = probe(zevtc)
    assert result == sidecar


def test_probe_returns_none_when_no_sidecar(tmp_path: Path) -> None:
    """Plan 136 spec test 3: missing sidecar returns None cleanly."""
    zevtc = tmp_path / "fight.zevtc"
    with zipfile.ZipFile(zevtc, "w") as zf:
        zf.writestr("fight.evtc", b"EVTC")
    result = probe(zevtc)
    assert result is None


def test_merge_sidecar_into_summary_updates_healing_by_skill() -> None:
    """Merge contract updates summary.healing_by_skill by skill id."""
    sidecar = {
        "players": {
            ":account.1234": {
                "healingBySkill": {"12345": 1500, "12346": 300},
            }
        }
    }
    summary = _FakeSummary(":account.1234")
    merge_sidecar_into_summary(summary, sidecar)
    assert summary.healing_by_skill == {"12345": 1500, "12346": 300}


def test_merge_sidecar_is_case_insensitive_for_account_name() -> None:
    """Merge contract matches account names case-insensitively."""
    sidecar = {
        "players": {
            ":Account.1234": {
                "healingBySkill": {"12345": 800},
            }
        }
    }
    summary = _FakeSummary(":account.1234")
    merge_sidecar_into_summary(summary, sidecar)
    assert summary.healing_by_skill == {"12345": 800}


def test_merge_sidecar_accumulates_with_existing_healing_by_skill() -> None:
    """Merge contract accumulates new sidecar values with existing ones."""
    sidecar = {
        "players": {
            ":account.1234": {
                "healingBySkill": {"12345": 500},
            }
        }
    }
    summary = _FakeSummary(":account.1234")
    summary.healing_by_skill = {"12345": 1000, "12347": 200}
    merge_sidecar_into_summary(summary, sidecar)
    assert summary.healing_by_skill == {"12345": 1500, "12347": 200}


def test_merge_sidecar_updates_barrier_by_skill() -> None:
    """Merge contract also populates summary.barrier_by_skill."""
    sidecar = {
        "players": {
            ":account.1234": {
                "healingBySkill": {"12345": 1500},
                "barrierBySkill": {"12345": 800, "12348": 400},
            }
        }
    }
    summary = _FakeSummary(":account.1234")
    merge_sidecar_into_summary(summary, sidecar)
    assert summary.healing_by_skill == {"12345": 1500}
    assert summary.barrier_by_skill == {"12345": 800, "12348": 400}


def test_merge_sidecar_accumulates_barrier_with_existing() -> None:
    """Merge contract accumulates barrier values with existing barrier_by_skill."""
    sidecar = {
        "players": {
            ":account.1234": {
                "barrierBySkill": {"12345": 500},
            }
        }
    }
    summary = _FakeSummary(":account.1234")
    summary.barrier_by_skill = {"12345": 1000}
    merge_sidecar_into_summary(summary, sidecar)
    assert summary.barrier_by_skill == {"12345": 1500}


def test_merge_sidecar_skips_invalid_skill_amounts() -> None:
    """Merge contract skips non-numeric skill amounts without crashing."""
    sidecar = {
        "players": {
            ":account.1234": {
                "healingBySkill": {"12345": 1500, "12346": "not-a-number"},
            }
        }
    }
    summary = _FakeSummary(":account.1234")
    merge_sidecar_into_summary(summary, sidecar)
    assert summary.healing_by_skill == {"12345": 1500}


def test_merge_sidecar_skips_non_dict_skill_maps() -> None:
    """Merge contract skips non-dict skill maps without crashing."""
    sidecar = {
        "players": {
            ":account.1234": {
                "healingBySkill": ["not", "a", "dict"],
                "barrierBySkill": "also-not-a-dict",
            }
        }
    }
    summary = _FakeSummary(":account.1234")
    merge_sidecar_into_summary(summary, sidecar)
    assert summary.healing_by_skill is None
    assert summary.barrier_by_skill is None
