"""Round-trip tests for the 5-member :class:`Event` discriminated union.

Verifies that every event subclass (DamageEvent, HealingEvent,
BuffRemovalEvent, BoonApplyEvent, CCEvent) round-trips through the
Pydantic v2 ``TypeAdapter(Event).validate_json(...)`` / ``model_dump_json()``
helpers. Phase 9 / advisor-plan 026 ran the discriminated union to 5
members (Phase 7 v1 was 2; Phase 8 added BuffRemovalEvent; the Plan
024 spike prototyped BoonApplyEvent + CCEvent; Phase 9 keeps the
spike prototypes + adds the ``kind`` discriminator).

The tests are HERMETIC: pure Pydantic + stdlib, no DB or EvtcParser;
they guard against regressions in the Event discriminated union --
specifically the Phase 9 BoonApplyEvent ``kind`` default (must
backward-compat with pre-Phase-9 wire payloads).
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from gw2_core import (
    BoonApplyEvent,
    BuffRemovalEvent,
    CCEvent,
    DamageEvent,
    Event,
    HealingEvent,
)

_EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


def _round_trip(event: Event) -> Event:
    """Encode via ``model_dump_json()`` + decode via the Event adapter."""
    return _EVENT_ADAPTER.validate_json(event.model_dump_json())


def test_damage_event_roundtrip() -> None:
    event = DamageEvent(
        time_ms=1_500,
        source_agent_id=10,
        target_agent_id=20,
        skill_id=1_000,
        damage=1_234,
    )
    assert _round_trip(event) == event


def test_healing_event_roundtrip() -> None:
    event = HealingEvent(
        time_ms=2_500,
        source_agent_id=10,
        target_agent_id=20,
        skill_id=1_001,
        healing=800,
    )
    assert _round_trip(event) == event


def test_buff_removal_event_roundtrip() -> None:
    event = BuffRemovalEvent(
        time_ms=3_500,
        source_agent_id=10,
        target_agent_id=20,
        skill_id=1_002,
        buff_removal=300,
    )
    assert _round_trip(event) == event


def test_boon_apply_event_roundtrip_apply_kind() -> None:
    """``kind='apply'`` is the default; round-trips cleanly."""
    event = BoonApplyEvent(
        time_ms=4_500,
        source_agent_id=10,
        target_agent_id=20,
        skill_id=2_000,
        duration_ms=5_000,
        stacks=1,
        kind="apply",
    )
    assert _round_trip(event) == event


def test_boon_apply_event_default_kind_is_apply() -> None:
    """Pre-Phase-9 wire payloads omit ``kind``; default to ``"apply"``.

    Without the default, the validated Pydantic model would raise a
    ``ValidationError`` on missing ``kind`` and the production event-
    blob walk (apps/api/services/event_blob.py::_persist_event_blob)
    would crash on every pre-Phase-9 .zevtc that the user re-uploads.
    That's the explicit backward-compat invariant pinned by this test.
    """
    event = BoonApplyEvent(
        time_ms=5_500,
        source_agent_id=10,
        target_agent_id=20,
        skill_id=2_001,
        duration_ms=3_000,
        stacks=1,
    )
    assert event.kind == "apply"
    assert _round_trip(event) == event


def test_boon_apply_event_remove_single_kind() -> None:
    """``kind='remove_single'`` is the arcdps ``is_buffremove == 1`` case."""
    event = BoonApplyEvent(
        time_ms=6_500,
        source_agent_id=10,
        target_agent_id=20,
        skill_id=2_002,
        duration_ms=0,
        stacks=1,
        kind="remove_single",
    )
    assert _round_trip(event) == event


def test_boon_apply_event_remove_all_kind() -> None:
    """``kind='remove_all'`` is the arcdps ``is_buffremove == 2`` case
    (a condi cleanse wipes every stack at once; up to GW2's 25-stack cap).
    """
    event = BoonApplyEvent(
        time_ms=7_500,
        source_agent_id=10,
        target_agent_id=20,
        skill_id=2_003,
        duration_ms=0,
        stacks=25,
        kind="remove_all",
    )
    assert _round_trip(event) == event


def test_cc_event_roundtrip() -> None:
    event = CCEvent(
        time_ms=8_500,
        source_agent_id=10,
        target_agent_id=20,
        skill_id=3_000,
        cc_value=100,
    )
    assert _round_trip(event) == event


@pytest.mark.parametrize(
    "kind",
    ["apply", "remove_single", "remove_all"],
)
def test_boon_apply_event_kind_literal_validation(kind: str) -> None:
    """Every valid ``kind`` literal round-trips; invalid literals raise."""
    if kind not in {"apply", "remove_single", "remove_all"}:
        pytest.fail(f"unexpected literal {kind!r}; update the test parametrize")
    event = BoonApplyEvent(
        time_ms=0,
        source_agent_id=0,
        target_agent_id=0,
        skill_id=0,
        duration_ms=0,
        stacks=0,
        kind=kind,  # type: ignore[arg-type]
    )
    assert _round_trip(event).kind == kind


def test_boon_apply_event_invalid_kind_raises() -> None:
    """Unknown ``kind`` literals (driver bytes we haven't classified yet)
    MUST fail validation rather than silently defaulting to ``"apply"`` --
    the silent default would mask parser regressions."""
    with pytest.raises(ValueError, match="kind"):
        BoonApplyEvent(
            time_ms=0,
            source_agent_id=0,
            target_agent_id=0,
            skill_id=0,
            duration_ms=0,
            stacks=0,
            kind="unknown_kind",  # type: ignore[arg-type]
        )


def test_event_adapter_is_deterministic() -> None:
    """The same Event validates to the same instance on re-validation
    (no race / no random id injection across the dispatcher)."""
    event = DamageEvent(
        time_ms=1_000,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=100,
        damage=100,
    )
    first = _EVENT_ADAPTER.validate_json(event.model_dump_json())
    second = _EVENT_ADAPTER.validate_json(first.model_dump_json())
    assert first == second == event
