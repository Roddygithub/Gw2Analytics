"""Contract tests for :func:`gw2analytics_api._event_dispatch.iter_events_from_blob`.

The 3 pinned cases below cover the on-hot-path behaviour of the
canonical gzip + ``TypeAdapter`` dispatch:

1. Single ``DamageEvent`` round-trips through gzip + discriminator
   dispatch.
2. Trailing whitespace lines are dropped (parser emits blank
   separators between events).
3. Mixed-type dispatch (``DamageEvent`` + ``HealingEvent``) returns
   events in source order with the matching subclasses.

Field-shape sanity (locked against ``libs/gw2_core/src/gw2_core/models.py``):
  * EventType discriminator values are UPPERCASE: ``"DAMAGE"`` /
    ``"HEALING"`` / ``"BUFF_REMOVAL"`` (StrEnum members).
  * ``BaseEvent`` carries: ``time_ms`` + ``source_agent_id`` +
    ``target_agent_id`` + ``skill_id`` -- NOT ``src`` / ``dst``.
  * Per-subclass payload fields: ``damage`` / ``healing`` /
    ``buff_removal`` -- NOT a generic ``value``.

Future regressions that break empty-line handling, the discriminator
lookup, OR event ordering will be caught by these tests.

MODULE-PURE-UNIT HYGIENE WARNING
=================================

ALL 3 tests in this module are intentionally pure-unit (NO DB, NO
network, NO filesystem). The module-local ``_isolate_test_state``
autouse fixture is a NO-OP shadow of the conftest's DB-cleanup
autouse (``apps/api/tests/conftest.py``).

If a FUTURE test added to this module DOES need Postgres, you MUST
either REMOVE THIS SHADOW entirely (to let the conftest's autouse
run again) OR scope the shadow to the specific pure-unit tests via
a marker + ``pytest_collection_modifyitems``. Leaving a DB-touching
test running under the no-op shadow produces silent cross-test
contamination (no per-test cleanup).
"""

from __future__ import annotations

import gzip
import importlib
import inspect
import json

import pytest

from gw2_core import BuffRemovalEvent, DamageEvent, HealingEvent
from gw2analytics_api._event_dispatch import iter_events_from_blob, validate_event_line


def _gz_jsonl(lines: list[dict[str, object]]) -> bytes:
    """Build a JSONL byte stream + gzip-compress it.

    The ``separators=(",", ":")`` argument matches the parser's compact
    form (``model_dump_json`` default). Whitespace at line boundaries
    is intentionally absent so the round-trip assertion is about the
    canonical write-side form.
    """
    blob = "\n".join(json.dumps(line, separators=(",", ":")) for line in lines).encode("utf-8")
    return gzip.compress(blob)


# ---------------------------------------------------------------------------
# v0.10.5 polish: skip the conftest's DB-cleanup autouse for the 3 tests
# below. These tests only exercise gzip + parse logic; no Postgres
# session is needed. The shadow-overrides pattern is the pytest idiom:
# a module-scoped fixture with the SAME name as the conftest's
# autouse takes precedence over the conftest fixture for tests in
# this module only.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolate_test_state() -> None:
    """No-op shadow of the conftest's DB-cleanup autouse (``apps/api/tests/conftest.py``).

    The conftest's autouse runs ``db.execute(delete(...))`` + commit
    against the test Postgres; these unit tests don't need DB. The
    shadow is module-scoped, so conftest-level tests elsewhere still
    get the real cleanup.

    v0.10.5 audit followup: ALL 3 tests in this module are pure-unit
    (NO DB). If a future test added here DOES need Postgres, REMOVE
    THIS SHADOW or scope it to the specific pure-unit tests.

    Scope note: this shadow disables ONLY the conftest's
    ``_isolate_test_state`` DB-cleanup autouse. The conftest's
    other autouse ``_disable_arq_for_tests`` still runs (and
    monkeypatches ``arq.create_pool`` + sets
    ``ALLOW_INREQUEST_PARSE_FALLBACK=1``); those don't touch DB so
    they're irrelevant for these pure-gzip tests.
    """


def test_iter_events_from_blob_round_trips_single_damage_event() -> None:
    """A single ``DamageEvent`` line survives gzip + discriminator dispatch."""
    gz = _gz_jsonl(
        [
            {
                "event_type": "DAMAGE",
                "time_ms": 1_000,
                "source_agent_id": 42,
                "target_agent_id": 99,
                "skill_id": 7,
                "damage": 500,
            },
        ],
    )

    events = iter_events_from_blob(gz)

    assert len(events) == 1
    assert isinstance(events[0], DamageEvent)
    assert events[0].event_type == "DAMAGE"
    assert events[0].time_ms == 1_000
    assert events[0].source_agent_id == 42
    assert events[0].target_agent_id == 99
    assert events[0].skill_id == 7
    assert events[0].damage == 500


def test_iter_events_from_blob_drops_whitespace_only_lines() -> None:
    """Trailing empty + whitespace-only lines are dropped, not parsed.

    The parser can emit trailing blank separators between events; the
    helper must NOT raise ``ValidationError`` on an empty line AND
    MUST NOT surface empty-string events. Pins ``if line.strip()``
    semantics in :func:`iter_events_from_blob`'s splitlines
    comprehension.

    All seven whitespace classes the parser may encounter are pinned:

    * ``b""`` -- fully empty line (was caught by the prior ``if line``
      filter; the round-2 ``if line.strip()`` keeps the behaviour).
    * ``b"   "`` -- ASCII space-only (the original surfaced bug).
    * ``b"\t"`` -- tab-only (the original surfaced bug).
    * ``b"\r\n"`` -- Windows line ending split by ``splitlines()``
      produces a ``b"\r"`` line that ``.strip()`` truncates to ``b""``.
    * ``b"\r"`` -- legacy Mac carriage-return alone.
    * ``b"\f"`` -- form feed (rare but valid JSON separator).
    * ``b"\v"`` -- vertical tab.

    Python's ``bytes.strip()`` covers all of them per the stdlib docs;
    this test pins the cross-platform correctness so a future
    "optimization" to a non-stripping filter regresses loudly.
    """
    valid = (
        b'{"event_type":"DAMAGE","time_ms":1000,'
        b'"source_agent_id":42,"target_agent_id":99,"skill_id":7,"damage":500}'
    )
    # Every whitespace class Python's ``.strip()`` strips: space, tab,
    # newline, carriage return, form feed, vertical tab. Each is padded
    # around the valid JSON to assert the dispatch still surfaces the
    # single valid event.
    blob = (
        valid
        + b"\n"  # plain newline
        + b"\r"  # carriage return alone (legacy Mac)
        + b"\r\n"  # Windows line ending
        + b"\n\n"  # two consecutive newlines
        + b"   \n"  # ASCII space separator
        + b"\t\n"  # tab separator
        + b"\f\n"  # form feed separator
        + b"\v\n"  # vertical tab separator
        + b"   \r\n"  # mixed whitespace + Windows line ending
    )
    gz = gzip.compress(blob)

    events = iter_events_from_blob(gz)

    assert len(events) == 1
    assert isinstance(events[0], DamageEvent)
    assert events[0].damage == 500


def test_iter_events_from_blob_returns_mixed_damage_healing_in_order() -> None:
    """DamageEvent + HealingEvent dispatch returns in source order.

    Pins two contracts:

    * ``TypeAdapter.validate_json(line)`` surfaces the matching
      subclass (not just the base ``Event``) via the ``event_type``
      discriminator.
    * The splitter preserves source order -- a future ``set``-based
      dedup would break this test.
    """
    gz = _gz_jsonl(
        [
            {
                "event_type": "DAMAGE",
                "time_ms": 1_000,
                "source_agent_id": 42,
                "target_agent_id": 99,
                "skill_id": 7,
                "damage": 500,
            },
            {
                "event_type": "HEALING",
                "time_ms": 1_500,
                "source_agent_id": 42,
                "target_agent_id": 99,
                "skill_id": 7,
                "healing": 300,
            },
        ],
    )

    events = iter_events_from_blob(gz)

    assert len(events) == 2
    assert isinstance(events[0], DamageEvent)
    assert isinstance(events[1], HealingEvent)
    assert [e.event_type for e in events] == ["DAMAGE", "HEALING"]


# ---------------------------------------------------------------------------
# v0.9.38 plan 116: single-source-of-truth adapter across the apps/api
# surface. The per-line ``validate_event_line`` primitive backs the
# streaming caller (routes/players); the route modules no longer define
# their own ``TypeAdapter(Event)`` (the duplication the plan removed).
# ---------------------------------------------------------------------------
def test_validate_event_line_dispatches_each_subtype() -> None:
    """The per-line primitive materialises the matching Event subclass."""
    dmg = validate_event_line(
        b'{"event_type":"DAMAGE","time_ms":1,"source_agent_id":1,'
        b'"target_agent_id":2,"skill_id":3,"damage":10}'
    )
    heal = validate_event_line(
        b'{"event_type":"HEALING","time_ms":1,"source_agent_id":1,'
        b'"target_agent_id":2,"skill_id":3,"healing":10}'
    )
    strip = validate_event_line(
        b'{"event_type":"BUFF_REMOVAL","time_ms":1,"source_agent_id":1,'
        b'"target_agent_id":2,"skill_id":3,"buff_removal":10}'
    )
    assert isinstance(dmg, DamageEvent)
    assert isinstance(heal, HealingEvent)
    assert isinstance(strip, BuffRemovalEvent)


def test_iter_events_from_blob_builds_on_validate_event_line() -> None:
    """The list helper and the per-line helper agree on one line."""
    line = (
        b'{"event_type":"DAMAGE","time_ms":1,"source_agent_id":1,'
        b'"target_agent_id":2,"skill_id":3,"damage":10}'
    )
    (via_list,) = iter_events_from_blob(gzip.compress(line))
    via_line = validate_event_line(line)
    assert via_list == via_line


@pytest.mark.parametrize("module_name", ["routes.fights", "routes.players"])
def test_route_modules_no_longer_define_local_adapter(module_name: str) -> None:
    """Regression guard: the route modules delegate to the dispatch hub.

    A re-introduced local ``TypeAdapter(Event)`` in either route module
    would resurrect the triplicate-adapter drift plan 116 removed.
    """
    module = importlib.import_module(f"gw2analytics_api.{module_name}")
    source = inspect.getsource(module)
    assert "TypeAdapter(Event)" not in source
    assert "_event_dispatch import" in source
