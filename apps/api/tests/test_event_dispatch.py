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
from gw2analytics_api._event_dispatch import (
    EVENT_TYPE_ADAPTER,
    build_event_iterator,
)
from gw2analytics_api.routes import fights as fights_module
from gw2analytics_api.routes import players as players_module
from gw2analytics_api.routes.fights import blob_loader
from gw2analytics_api.scripts import backfill_player_summaries as backfill
from gw2analytics_api.services import player_service as player_service_module


def _event_line(event: Event) -> bytes:
    # Serialize the concrete subclass, not the ``Event`` adapter:
    # ``WrapValidator`` only intercepts *validation*; the adapter's
    # ``dump_json`` sees the annotated ``BaseEvent`` root and drops
    # the subclass-specific fields (``event_type``, ``damage``, ...).
    return event.model_dump_json().encode("utf-8") + b"\n"


def test_canonical_adapter_is_single_instance_apps_api_wide() -> None:
    """The hub's adapter is the same object used by the helper."""
    assert "EVENT_TYPE_ADAPTER" in build_event_iterator.__globals__
    assert build_event_iterator.__globals__["EVENT_TYPE_ADAPTER"] is EVENT_TYPE_ADAPTER


def test_build_event_iterator_yields_three_subtypes_in_discriminator_order() -> None:
    """A gzipped JSONL with one damage + one healing + one strip event
    yields the matching concrete subclasses in source order.
    """
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
    """``routes/fights`` no longer instantiates its own adapter.

    Post-A2 god-module refactor (plan 021), the ``build_event_iterator``
    import moved from ``routes/fights/__init__.py`` to
    ``routes/fights/blob_loader.py`` (the extracted blob-load helper).
    The test checks the correct module: ``fights/__init__.py`` must NOT
    have a local ``TypeAdapter(Event)`` (the old pattern), and
    ``blob_loader.py`` MUST import ``build_event_iterator`` (the
    canonical hub helper).
    """
    source = inspect.getsource(fights_module)
    assert "TypeAdapter(Event)" not in source
    # The canonical helper now lives in blob_loader (A2 refactor).
    blob_source = inspect.getsource(blob_loader)
    assert "build_event_iterator" in blob_source


def test_players_service_dropped_local_event_type_adapter() -> None:
    """``player_service.py`` imports the canonical adapter (not a local one).

    Post-A2 god-module refactor (plan 021), the ``build_event_iterator``
    import moved from ``routes/players.py`` to ``services/player_service.py``
    (the extracted player-service layer). The route file no longer
    instantiates ``TypeAdapter(Event)`` and the service layer imports
    the canonical ``build_event_iterator`` helper.
    """
    route_source = inspect.getsource(players_module)
    assert "TypeAdapter(Event)" not in route_source
    service_source = inspect.getsource(player_service_module)
    assert "build_event_iterator" in service_source


def test_backfill_drops_local_event_type_adapter() -> None:
    """``backfill.py`` no longer instantiates its own adapter."""
    source = inspect.getsource(backfill)
    assert "TypeAdapter(Event)" not in source
    assert "build_event_iterator" in source


def test_build_event_iterator_does_not_use_gzip_decompress() -> None:
    """v0.10.13 plan 027 regression: the streaming impl MUST NOT contain gzip.decompress.

    inspect.getsource reads the function body as text. The streaming
    implementation uses ``gzip.GzipFile(fileobj=io.BytesIO(...))``
    (line-by-line decompression) and NEVER ``gzip.decompress`` (which
    would materialise the entire decompressed bytes + a ``splitlines()``
    list, defeating the streaming intent).

    A future revert to ``gzip.decompress + splitlines`` (e.g. an
    accidental "minimal import" rewrite that thinks the streaming
    pattern is over-engineered) MUST fail this test. The substring
    check is intentional: pin the absence, not the presence of a
    specific call site -- a future refactor that uses
    ``gzip.decompress`` again for ANY purpose in this helper fails.
    """
    source = inspect.getsource(build_event_iterator)
    assert "gzip.decompress(" not in source, (
        "build_event_iterator contains gzip.decompress( -- the streaming "
        "implementation has been reverted to the legacy materialising "
        "path (gzip.decompress + splitlines). The 200 MB peak RAM on "
        "30 MB gzipped WvW logs is BACK."
    )
    # Cross-check: the streaming implementation MUST use GzipFile.
    assert "gzip.GzipFile" in source, (
        "build_event_iterator does not contain gzip.GzipFile -- the "
        "streaming implementation is missing. The helper either fell "
        "back to gzip.decompress OR was rewritten with a non-gzip "
        "decompressor entirely."
    )
