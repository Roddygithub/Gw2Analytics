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
import json

import pytest

from gw2_core import DamageEvent, HealingEvent

from gw2analytics_api._event_dispatch import iter_events_from_blob


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
    MUST NOT surface empty-string events. Pins ``if line`` semantics
    in :func:`iter_events_from_blob`'s splitlines comprehension.
    """
    blob = (
        b'{"event_type":"DAMAGE","time_ms":1000,"source_agent_id":42,"target_agent_id":99,"skill_id":7,"damage":500}'
        b"\n\n"
        b"   \n"
        b"\t\n"
    )
    gz = gzip.compress(blob)

    events = iter_events_from_blob(gz)

    assert len(events) == 1
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
