"""Hermetic SCAFFOLD-zero contract tests for WAVE-8 v0.11.0 Blocker A.4.2.

The A.4.2 sub-slice ships the SCAFFOLD for the arcdps in-game overlay
log parser. The reverse-engineering of the overlay log format is NOT
IN SCOPE for this commit (per ``plans/WAVE-8-parser-side.md`` §A.4.2);
the SCAFFOLD-zero yield-on-zero-events contract IS in scope.

The tests in this file lock the SCAFFOLD-zero boundary so a future
refactor that prematurely yields events for an under-specified
overlay log format (e.g. producing phantom ``Block`` records that
pollute the ``defense.blocks`` column) fires at the unit-test boundary
BEFORE the regression propagates to the F1 calibration pilot or
downstream
:class:`~apps.gw2analytics_api.routes.fights.aggregators.PlayerDefenseAggregator`.

Backward-compat rationale:

The SCAFFOLD-zero contract preserves the Wave 5 SCAFFOLD posture for
the 3 §1 SCAFFOLD-zero columns (``defense.dodges`` + ``defense.blocks``
+ ``defense.interrupts``). Pre-A.4.2 callers see IDENTICAL downstream
counters (all zero) -- the SCAFFOLD-zero stub is a SEMANTIC NOP for
existing wire streams. The format-spec deliverable will flip the stub
to a real implementation, but the wire contract is unchanged
(depth-zero preserves the count=0 surface; format-realistic gives the
real count).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from gw2_evtc_parser.overlay_log import (
    OverlayLogAction,
    OverlayLogEvent,
    parse_overlay_events,
)

# ---------------------------------------------------------------------------
# SCAFFOLD-zero contract: parse_overlay_events yields zero events on any input
# ---------------------------------------------------------------------------


def test_parse_overlay_events_no_path_yields_nothing() -> None:
    """SCAFFOLD-zero: ``parse_overlay_events(None)`` yields zero events.

    The no-path surface is the canonical pre-A.4.2 invocation: existing
    CLI / API callers (without the future ``--overlay-log`` flag)
    iterate without try/except, get zero events back, and the SCAFFOLD
    contract holds.
    """
    events = list(parse_overlay_events(None))
    assert events == []


def test_parse_overlay_events_with_nonexistent_path_yields_nothing() -> None:
    """SCAFFOLD-zero: a Path that points to nothing yields zero events.

    The function does NOT file-not-found raise -- the SCAFFOLD-zero
    contract holds across the union of {None, real Path, non-existent
    Path, empty Path}. Future format-realistic implementations will
    raise for non-existent paths; SCAFFOLD-zero does not (Phase 6 v2
    yield-realism trade).
    """
    events = list(parse_overlay_events(Path("/tmp/does-not-exist-overlay-log.bin")))  # noqa: S108
    assert events == []


def test_parse_overlay_events_with_string_path_yields_nothing() -> None:
    """SCAFFOLD-zero: a string path accepts (ergonomic for CLI callers), yields zero.

    The string-path overload exists so a CLI handler can pass
    ``args.overlay_log`` (a ``str`` from argparse) directly without
    wrapping in :class:`Path`. The SCAFFOLD-zero contract holds.
    """
    events = list(parse_overlay_events("/tmp/any-overlay-log.zevtc"))  # noqa: S108
    assert events == []


def test_parse_overlay_events_iterator_returns_iterator_not_list() -> None:
    """The function returns an Iterator (lazy), not a list.

    SCAFFOLD-zero yields nothing, but the type signature must be
    ``Iterator[OverlayLogEvent]`` (NOT ``list[OverlayLogEvent]``).
    A future format-realistic implementation will lazily stream
    records from disk; the Iterator contract lets the Stream Merger
    consume the records without materialising the full overlay log
    in memory.
    """
    result = parse_overlay_events(None)
    # Iterator protocol: has __iter__ + __next__, no __len__.
    assert hasattr(result, "__iter__")
    assert hasattr(result, "__next__")
    assert not hasattr(result, "__len__")


# ---------------------------------------------------------------------------
# OverlayLogAction enum: the 3 §1 SCAFFOLD-zero columns shape lock
# ---------------------------------------------------------------------------


def test_overlay_log_action_enum_has_three_canonical_kinds() -> None:
    """The 3 canonical kinds awaited by the §1 SCAFFOLD-zero columns are present.

    Per ``plans/WAVE-8-parser-side.md`` §1:

    - ``defense.dodges`` -> :attr:`OverlayLogAction.DODGE`
    - ``defense.blocks`` -> :attr:`OverlayLogAction.BLOCK`
    - ``defense.interrupts`` -> :attr:`OverlayLogAction.INTERRUPT`

    The reverse-engineered arcdps overlay log will likely yield more
    kinds (e.g. :attr:`RESURRECT`, :attr:`MOUNT`); those are NOT in
    scope for the §1 SCAFFOLD-zero columns, so they are not in this
    enum. A future format-spec deliverable may extend the enum without
    breaking the SCAFFOLD-zero contract (new kinds = zero-yield-of-new-kinds).
    """
    assert {e.value for e in OverlayLogAction} == {"DODGE", "BLOCK", "INTERRUPT"}
    assert len(OverlayLogAction) == 3


# ---------------------------------------------------------------------------
# OverlayLogEvent Pydantic shape: deterministic forward-compat landing pad
# ---------------------------------------------------------------------------


def test_overlay_log_event_dodge_actor_only_shape() -> None:
    """A DODGE :class:`OverlayLogEvent` is actor-only (target + skill default to None).

    The :class:`~gw2_core.DodgeEvent` model + the Wave 5 SCAFFOLD docstring
    say dodge is a player-action with no target / skill attribution
    from the arcdps logger. The overlay log SCAFFOLD event preserves
    that contract.
    """
    e = OverlayLogEvent(
        time_ms=10_000,
        source_agent_id=42,
        action=OverlayLogAction.DODGE,
    )
    assert e.time_ms == 10_000
    assert e.source_agent_id == 42
    assert e.action == OverlayLogAction.DODGE
    # Actor-only shape: target + skill default to None.
    assert e.target_agent_id is None
    assert e.skill_id is None


def test_overlay_log_event_block_actor_only_shape() -> None:
    """A BLOCK :class:`OverlayLogEvent` is actor-only (mirrors DODGE contract).

    :class:`~gw2_core.BlockEvent` docstring says block is a player-action
    with no target / skill attribution. The overlay log SCAFFOLD event
    preserves that contract (block carries the per-block damage-absorbed
    attribute in the future format-spec, but the SCAFFOLD shape is
    actor-only to match the gw2_core model).
    """
    e = OverlayLogEvent(
        time_ms=20_000,
        source_agent_id=42,
        action=OverlayLogAction.BLOCK,
    )
    assert e.action == OverlayLogAction.BLOCK
    assert e.target_agent_id is None
    assert e.skill_id is None


def test_overlay_log_event_interrupt_carries_target_and_skill() -> None:
    """An INTERRUPT :class:`OverlayLogEvent` carries target + skill (full BaseEvent shape).

    Per :class:`~gw2_core.InterruptEvent` docstring: interrupt is NOT
    actor-only -- it carries the target agent (the casted spell owner)
    + the interrupting skill_id for the per-interrupt forensic
    attribution. The overlay log SCAFFOLD event preserves that contract.
    """
    e = OverlayLogEvent(
        time_ms=30_000,
        source_agent_id=42,
        target_agent_id=99,
        skill_id=777,
        action=OverlayLogAction.INTERRUPT,
    )
    assert e.action == OverlayLogAction.INTERRUPT
    assert e.target_agent_id == 99
    assert e.skill_id == 777


def test_overlay_log_event_is_frozen_after_construction() -> None:
    """A constructed :class:`OverlayLogEvent` cannot be mutated (frozen=True).

    Mirrors :class:`~gw2_core.BaseEvent`'s ``ConfigDict(frozen=True, ...)``
    so a future predicate in the Stream Merger / the JSONL round-trip
    reads the model with the same Pydantic-v2 contract. Pydantic v2
    raises ``ValidationError`` (which subclasses ``ValueError``) on
    assignment to a frozen field, so the assertion tuple catches all
    three exception shapes via the ``ValueError`` parent class. We
    intentionally do NOT add ``ValidationError`` to the tuple --
    the ``ValueError`` inheritance handles it (a future maintainer
    adding it back would re-merge the previous combined-assertion
    test that this commit split apart).
    """
    e = OverlayLogEvent(
        time_ms=10_000,
        source_agent_id=42,
        action=OverlayLogAction.DODGE,
    )
    # ``# type: ignore[misc]`` is needed: mypy strict correctly flags the
    # assignment as writing to a read-only Pydantic v2 frozen field.
    # The ``pytest.raises`` catches the runtime PydanticValidationError
    # (a :class:`ValueError` subclass) instead -- see the docstring above.
    with pytest.raises((ValueError, TypeError)):
        e.time_ms = 99_999  # type: ignore[misc]


def test_overlay_log_event_rejects_extra_fields() -> None:
    """``OverlayLogEvent.model_validate`` rejects unknown keys (extra="forbid").

    Mirrors :class:`~gw2_core.BaseEvent`'s ``ConfigDict(extra="forbid", ...)``.
    A future JSONL round-trip that adds an unknown field (e.g. a
    forward-compat attribute landed in a downstream consumer but not
    yet in the SCAFFOLD schema) raises ``ValidationError`` at the
    Pydantic boundary -- the error propagates to the consumer's
    error handler, not silently into the wire stream.
    """
    with pytest.raises(ValidationError):
        OverlayLogEvent.model_validate(
            {
                "time_ms": 10_000,
                "source_agent_id": 42,
                "action": "DODGE",
                "extra_unknown_field": "should-fail",
            },
        )
