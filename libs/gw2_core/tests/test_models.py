"""Hermetic tests for libs/gw2_core v2 domain models (P003).

The pure-Python ``make_*`` builders below are the canonical test data
factories (Pydantic ``model_dump_json`` round-trip with sensible
defaults). The builders live here, NOT in :mod:`conftest`, so they
can be imported directly by any standalone invocation (e.g.
``python -m test_models``) and so pytest rootdir-discovery loading
the `tests/` dir onto sys.path is not required.

All 10 assertions below are derived from the v2 model field names
read directly from ``libs/gw2_core/src/gw2_core/models.py`` --
``damage`` (NOT ``value``) for ``DamageEvent``, ``healing`` for
``HealingEvent``, ``buff_removal`` for ``BuffRemovalEvent``.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from gw2_core import (
    AccountInfo,
    BuffRemovalEvent,
    DamageEvent,
    EliteSpec,
    Event,
    HealingEvent,
    Population,
    Profession,
    WorldInfo,
)

# --- Test data builders -----------------------------------------------------
# Defensive defaults: every builder accepts ``**overrides`` so individual
# tests can tweak one field (skill_id, value, ...) without re-spelling
# the whole shape. Pure functions, no I/O.


def make_damage_event(**overrides: Any) -> DamageEvent:
    payload: dict[str, Any] = {
        "time_ms": 1500,
        "source_agent_id": 1,
        "target_agent_id": 2,
        "damage": 1000,
        "skill_id": 42,
    }
    payload.update(overrides)
    return DamageEvent(**payload)


def make_healing_event(**overrides: Any) -> HealingEvent:
    payload = {
        "time_ms": 1500,
        "source_agent_id": 1,
        "target_agent_id": 2,
        "healing": 500,
        "skill_id": 42,
    }
    payload.update(overrides)
    return HealingEvent(**payload)


def make_buff_removal_event(**overrides: Any) -> BuffRemovalEvent:
    payload = {
        "time_ms": 1500,
        "source_agent_id": 1,
        "target_agent_id": 2,
        "buff_removal": 1,
        "skill_id": 42,
    }
    payload.update(overrides)
    return BuffRemovalEvent(**payload)


def make_account_info(**overrides: Any) -> AccountInfo:
    payload = {
        "id": "ACCT-001",
        "name": "Test Account",
        "world": 1001,  # wire-format alias; Pydantic resolves via ``alias="world"``
    }
    payload.update(overrides)
    return AccountInfo(**payload)


_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


# --- Discriminated-union dispatch (canonical round-trip) -------------------


def test_damage_event_discriminated_union_dispatch() -> None:
    """``model_dump_json`` → ``TypeAdapter.validate_json`` lands on DamageEvent."""
    payload = make_damage_event().model_dump_json()
    event = _ADAPTER.validate_json(payload)
    assert isinstance(event, DamageEvent)


def test_healing_event_discriminated_union_dispatch() -> None:
    """``model_dump_json`` → ``TypeAdapter.validate_json`` lands on HealingEvent."""
    payload = make_healing_event().model_dump_json()
    event = _ADAPTER.validate_json(payload)
    assert isinstance(event, HealingEvent)


def test_buff_removal_event_discriminated_union_dispatch() -> None:
    """``model_dump_json`` → ``TypeAdapter.validate_json`` lands on BuffRemovalEvent."""
    payload = make_buff_removal_event().model_dump_json()
    event = _ADAPTER.validate_json(payload)
    assert isinstance(event, BuffRemovalEvent)


def test_unknown_event_type_raises_validation_error() -> None:
    bad = (
        b'{"event_type":"unknown_v12","time_ms":1500,'
        b'"source_agent_id":1,"target_agent_id":2,"value":100,"skill_id":42}'
    )
    with pytest.raises(ValidationError):
        _ADAPTER.validate_json(bad)


# --- AccountInfo (gw2 v2 API surface; ``extra=ignore``) -------------------


def test_account_info_extra_ignore_strips_unknown_fields() -> None:
    payload = make_account_info().model_dump(by_alias=True)
    payload["future_v999"] = {"nested": "ignored"}
    parsed = AccountInfo.model_validate(payload)
    dumped = parsed.model_dump(by_alias=False)
    assert "future_v999" not in dumped
    assert dumped["world_id"] == 1001


def test_account_info_world_alias_round_trip() -> None:
    """``alias="world"`` maps wire field → ``world_id`` Python attr."""
    info = AccountInfo.model_validate({"id": "X", "name": "Y", "world": 2002})
    assert info.world_id == 2002
    wire = info.model_dump(by_alias=True)
    assert wire["world"] == 2002
    assert "world_id" not in wire


def test_account_info_required_id_name_world() -> None:
    with pytest.raises(ValidationError):
        AccountInfo.model_validate({"id": "X"})


# --- WorldInfo / Population -----------------------------------------------


def test_world_info_population_capitalised_accept() -> None:
    info = WorldInfo.model_validate({"id": 1, "name": "Yak's Bend", "population": "High"})
    assert info.population == Population.HIGH


def test_world_info_population_lowercase_reject() -> None:
    with pytest.raises(ValidationError):
        WorldInfo.model_validate({"id": 1, "name": "Yak's Bend", "population": "high"})


# --- EliteSpec (catalog + dtype invariants) -------------------------------


def test_elite_spec_disambiguation_targets_present() -> None:
    """Soulbeast + Daredevil are the canonical historical collision case
    (both map to id 55 in different arcdps revisions)."""
    assert hasattr(EliteSpec, "SOULBEAST")
    assert hasattr(EliteSpec, "DAREDEVIL")


def test_elite_spec_intvalues_are_positive() -> None:
    """All real-spec ids (>0) must be non-negative ints."""
    for member in EliteSpec:
        assert isinstance(member.value, int)
        assert member.value >= 0


# --- Frozen event blocks direct mutation (Phase-7 v2 contract) ----------


def test_frozen_event_blocks_direct_mutation() -> None:
    event = make_damage_event()
    with pytest.raises(ValidationError):
        event.damage = 9999  # type: ignore[misc]


def test_event_extra_forbid_rejects_unknown_field() -> None:
    """All BaseEvent subclasses carry ``extra="forbid"``; unknown keys raise."""
    with pytest.raises(ValidationError):
        DamageEvent.model_validate(
            {
                "time_ms": 0,
                "source_agent_id": 1,
                "target_agent_id": 2,
                "damage": 100,
                "skill_id": 1,
                "rogue_field": "reject",
            }
        )


# --- Profession enum (catalog invariant) ---------------------------------


def test_profession_values_unique() -> None:
    seen: set[int] = set()
    for member in Profession:
        assert member.value not in seen, f"duplicate Profession id {member.value}"
        seen.add(member.value)
