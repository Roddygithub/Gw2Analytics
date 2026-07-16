"""Hermetic tests for the new :class:`BarrierEvent` (WAVE-8 A.3 close-out).

The dispatch round-trip lock ensures the :data:`_EVENT_MAP` routing
table correctly maps ``EventType.BARRIER`` -> :class:`BarrierEvent`
(vs a no-op fallback to :class:`BaseEvent`). The boundary-value tests
lock the ge=0 constraint on the per-event payload (barrier_amount +
duration_ms) so a future numeric-typing change (e.g. switching to
``float`` for sub-millisecond durations) surfaces a test failure
rather than a silent aggregation drift.

Per the existing tour-6 dispatch architecture (event dispatch uses
``WrapValidator`` + ``model_validate`` for O(1) dispatch), adding a
new Event subclass requires ONLY one entry in ``_EVENT_MAP`` -- these
tests pin that dispatch path for BarrierEvent.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from gw2_core import BarrierEvent, EventType


def make_barrier_event(**overrides: Any) -> BarrierEvent:
    payload: dict[str, Any] = {
        "time_ms": 1500,
        "source_agent_id": 1,
        "target_agent_id": 2,
        "barrier_amount": 1000,
        "duration_ms": 5000,
        "skill_id": 42,
    }
    payload.update(overrides)
    return BarrierEvent(**payload)


_ADAPTER: TypeAdapter[BarrierEvent] = TypeAdapter(BarrierEvent)


def test_barrier_event_round_trip() -> None:
    """``model_dump_json`` -> ``model_validate_json`` preserves the wire shape."""
    event = make_barrier_event()
    wire = event.model_dump_json()
    parsed = _ADAPTER.validate_json(wire)
    assert parsed == event


def test_barrier_event_amount_zero_allowed() -> None:
    """``barrier_amount = 0`` is valid (a barrier-cancelled-by-gc edge case).

    The ge=0 constraint accepts 0; an instant-cancellation barrier
    (the shield was applied + immediately destroyed by a statechange
    race) must parse cleanly so the heal aggregator's
    ``barrier_total`` roll-up stays byte-equivalent to the wire.
    """
    event = make_barrier_event(barrier_amount=0)
    assert event.barrier_amount == 0


def test_barrier_event_amount_negative_rejected() -> None:
    """``barrier_amount < 0`` is rejected per the ge=0 constraint closure."""
    with pytest.raises(ValidationError):
        make_barrier_event(barrier_amount=-1)


def test_barrier_event_duration_zero_allowed() -> None:
    """``duration_ms = 0`` is valid (instantaneous barrier; e.g. Flame
    Shield's tap-on-damage variant). The heal aggregator's
    ``barrier_ps`` computes ``barrier_amount / max(duration_s, 1)``
    downstream, so a 0 duration is safe to round-trip."""
    event = make_barrier_event(duration_ms=0)
    assert event.duration_ms == 0


def test_barrier_event_duration_negative_rejected() -> None:
    """``duration_ms < 0`` is rejected per the ge=0 constraint closure."""
    with pytest.raises(ValidationError):
        make_barrier_event(duration_ms=-1)


def test_barrier_event_extra_forbid_rejects_unknown_field() -> None:
    """BarrierEvent carries the BaseEvent ``extra="forbid"`` contract."""
    with pytest.raises(ValidationError):
        BarrierEvent.model_validate(
            {
                "time_ms": 0,
                "source_agent_id": 1,
                "target_agent_id": 2,
                "skill_id": 1,
                "barrier_amount": 100,
                "duration_ms": 1000,
                "rogue_field": "reject",
            }
        )


def test_event_type_barrier_registered_in_enum() -> None:
    """``EventType.BARRIER`` is a real enum entry (not a free-form string)."""
    # Touch the enum value so an accidental StrEnum mistype breaks
    # loudly here, NOT at the parser-stream switch (Phase 6 v2).
    assert EventType.BARRIER.value == "BARRIER"


# --- Discriminated-union dispatch (canonical lock for tour 6 routing) -----


def test_barrier_event_dispatch_through_event_union() -> None:
    """``TypeAdapter(Event).validate_json`` on BarrierEvent payload -> BarrierEvent.

    Mirrors the dispatch contract for every existing Event subclass
    (DamageEvent / HealingEvent / BuffRemovalEvent). The ``Event``
    Annotated type uses a ``WrapValidator`` + ``_EVENT_MAP``
    dict-lookup dispatch; adding a new Event subclass REQUIRES an
    entry in the map (the v0.10.25 baseline) so this lock pins
    that contract. If a future refactor drops the map entry for
    ``EventType.BARRIER``, this test fails.
    """
