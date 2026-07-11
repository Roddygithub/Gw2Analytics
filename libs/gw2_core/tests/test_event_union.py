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

from typing import Literal, cast

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


def _round_trip[T: Event](cls: type[T], event: T) -> T:
    """Encode via ``model_dump_json()`` + decode via the typed Event adapter.

    Uses Python 3.12 PEP 695 generic syntax so the return type is
    narrowed to ``T`` -- the bare ``Event`` union widens to the
    discriminated union which triggers mypy's ``union-attr``
    warnings on subsequent ``.damage`` / ``.healing`` / ``.kind``
    field access. This helper is THE single admit point for both
    ``_round_trip`` (used by the round-trip equality checks) AND
    ``_validate_subclass`` (used by the determinism check), so the
    round-1 cleanup disappeared the TypeVar-bound mirror helper.
    """
    return TypeAdapter(cls).validate_json(event.model_dump_json())


def test_damage_event_roundtrip() -> None:
    event = DamageEvent(
        time_ms=1_500,
        source_agent_id=10,
        target_agent_id=20,
        skill_id=1_000,
        damage=1_234,
    )
    assert _round_trip(DamageEvent, event) == event


def test_healing_event_roundtrip() -> None:
    event = HealingEvent(
        time_ms=2_500,
        source_agent_id=10,
        target_agent_id=20,
        skill_id=1_001,
        healing=800,
    )
    assert _round_trip(HealingEvent, event) == event


def test_buff_removal_event_roundtrip() -> None:
    event = BuffRemovalEvent(
        time_ms=3_500,
        source_agent_id=10,
        target_agent_id=20,
        skill_id=1_002,
        buff_removal=300,
    )
    assert _round_trip(BuffRemovalEvent, event) == event


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
    assert _round_trip(BoonApplyEvent, event) == event


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
    assert _round_trip(BoonApplyEvent, event) == event


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
    assert _round_trip(BoonApplyEvent, event) == event


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
    assert _round_trip(BoonApplyEvent, event) == event


def test_cc_event_roundtrip() -> None:
    event = CCEvent(
        time_ms=8_500,
        source_agent_id=10,
        target_agent_id=20,
        skill_id=3_000,
        cc_value=100,
    )
    assert _round_trip(CCEvent, event) == event


@pytest.mark.parametrize(
    "kind",
    ["apply", "remove_single", "remove_all"],
)
def test_boon_apply_event_kind_literal_validation(
    kind: Literal["apply", "remove_single", "remove_all"],
) -> None:
    """Every valid ``kind`` literal round-trips; invalid literals raise.

    Typing the parametrize as ``Literal[...]`` (instead of ``str``)
    eliminates the previous ``# type: ignore[arg-type]`` directive --
    mypy now sees the literal-string assignment as matching the
    field's Literal type expression.
    """
    event = BoonApplyEvent(
        time_ms=0,
        source_agent_id=0,
        target_agent_id=0,
        skill_id=0,
        duration_ms=0,
        stacks=0,
        kind=kind,
    )
    assert _round_trip(BoonApplyEvent, event).kind == kind


def test_boon_apply_event_invalid_kind_raises() -> None:
    """Unknown ``kind`` literals (driver bytes we haven't classified yet)
    MUST fail validation rather than silently defaulting to ``"apply"`` --
    the silent default would mask parser regressions.

    ``typing.cast`` carries the value through unchanged at runtime
    AND signals mypy to treat it as a ``Literal[...]`` match at the
    static type level. Pydantic sees the underlying ``"unknown_kind"``
    string at validation time and rejects it -- the cast is purely a
    static-type-narrowing aid, no runtime effect on the payload.
    """
    with pytest.raises(ValueError, match="kind"):
        BoonApplyEvent(
            time_ms=0,
            source_agent_id=0,
            target_agent_id=0,
            skill_id=0,
            duration_ms=0,
            stacks=0,
            kind=cast(Literal["apply", "remove_single", "remove_all"], "unknown_kind"),
        )


def test_event_adapter_is_deterministic() -> None:
    """The same Event validates to the same instance on re-validation
    (no race / no random id injection across the dispatcher).

    The narrowed ``_round_trip`` helper returns ``DamageEvent``
    strictly (not the bare Event union), so subsequent equality
    comparisons do not trigger mypy's ``union-attr`` warning.
    """
    event = DamageEvent(
        time_ms=1_000,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=100,
        damage=100,
    )
    first = _round_trip(DamageEvent, event)
    second = _round_trip(DamageEvent, first)
    assert first == second == event
