"""Tests for :mod:`gw2analytics_api._event_dispatch`.

Plan 116 consolidates the triplicate ``TypeAdapter(Event)``
instances + the gzipped-JSONL round-trip across
``backfill.py``, ``routes/fights.py``, and ``routes/players.py``
into a single canonical hub. These tests pin the
single-source-of-truth invariant.
"""

from __future__ import annotations

import gzip
import inspect

from gw2_core import BuffRemovalEvent, DamageEvent, Event, HealingEvent
from gw2analytics_api import backfill
from gw2analytics_api._event_dispatch import (
    EVENT_TYPE_ADAPTER,
    build_event_iterator,
)
from gw2analytics_api.routes import fights as fights_module
from gw2analytics_api.routes import players as players_module


def _event_line(event: Event) -> bytes:
    return EVENT_TYPE_ADAPTER.dump_json(event).replace(b"\n", b"") + b"\n"


def test_canonical_adapter_is_single_instance_apps_api_wide() -> None:
    """The hub's adapter is the same object used by the helper."""
    assert "EVENT_TYPE_ADAPTER" in build_event_iterator.__globals__
    assert build_event_iterator.__globals__["EVENT_TYPE_ADAPTER"] is EVENT_TYPE_ADAPTER


def test_build_event_iterator_yields_three_subtypes_in_discriminator_order() -> None:
    """A gzipped JSONL with one damage + one healing + one strip event
    yields the matching concrete subclasses in source order."""
    lines = b"".join(
        [
            _event_line(
                DamageEvent(
                    event_type="DAMAGE",
                    time_ms=1,
                    source_agent_id=1,
                    target_agent_id=2,
                    skill_id=3,
                    damage=100,
                ),
            ),
            _event_line(
                HealingEvent(
                    event_type="HEALING",
                    time_ms=2,
                    source_agent_id=1,
                    target_agent_id=2,
                    skill_id=3,
                    healing=50,
                ),
            ),
            _event_line(
                BuffRemovalEvent(
                    event_type="BUFF_REMOVAL",
                    time_ms=3,
                    source_agent_id=1,
                    target_agent_id=2,
                    skill_id=3,
                    buff_removal=25,
                ),
            ),
        ],
    )
    gz_bytes = gzip.compress(lines)
    events = list(build_event_iterator(gz_bytes=gz_bytes))

    assert len(events) == 3
    assert isinstance(events[0], DamageEvent)
    assert isinstance(events[1], HealingEvent)
    assert isinstance(events[2], BuffRemovalEvent)


def test_routes_fights_drops_local_event_type_adapter() -> None:
    """``routes/fights.py`` no longer instantiates its own adapter."""
    source = inspect.getsource(fights_module)
    assert "TypeAdapter(Event)" not in source
    assert "build_event_iterator" in source


def test_routes_players_drops_local_event_type_adapter() -> None:
    """``routes/players.py`` no longer instantiates its own adapter."""
    source = inspect.getsource(players_module)
    assert "TypeAdapter(Event)" not in source
    assert "build_event_iterator" in source


def test_backfill_drops_local_event_type_adapter() -> None:
    """``backfill.py`` no longer instantiates its own adapter."""
    source = inspect.getsource(backfill)
    assert "TypeAdapter(Event)" not in source
    assert "build_event_iterator" in source
