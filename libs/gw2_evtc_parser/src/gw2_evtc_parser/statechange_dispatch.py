"""Statechange event dispatch table (WAVE-8 v0.11.0 Blocker A.4.1).

This module maps arcdps ``is_statechange`` bytes (the CBTS kinds, per
:file:`docs/statechange-ids.md`) to Pydantic domain event constructors.
It mirrors the dict-dispatch pattern from
:data:`gw2_core.models._EVENT_MAP` to decouple the parser decode loop
from the exact event signatures.

The dispatch table is **additive** -- future sub-slices (A.4.2 + A.4.3)
extend the table with more ``byte -> emit_function`` entries WITHOUT
any consumer-side change. The ``STATECHANGE_MAP`` dict is exposed at
module level so the F1 calibration pilot can inspect the wired kinds.

Backward compat: A.4 ships 5 entries (StunBreakEvent +
BarrierEvent + DeathEvent + DownEvent + CCEvent); unmapped
statechange kinds return ``None`` from :func:`dispatch_statechange`
so the parser's upstream filter (``if is_statechange != 0: continue``)
still suppresses them at the byte boundary.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Final

from gw2_core import BarrierEvent, CCEvent, DeathEvent, DownEvent, Event, StunBreakEvent

logger = logging.getLogger(__name__)

#: arcdps statechange byte for StunBreak events (per statechange-ids.md).
#: The Tour 6 v0.10.24-pre shipped the StunBreaks column end-to-end via
#: :class:`~apps.gw2analytics_api.routes.fights.aggregators.PlayerHealAggregator`;
#: A.4.1 wires the parser-side emit so the Pydantic instance is also
#: available via :meth:`PythonEvtcParser.parse_events` for downstream
#: consumers that read the event stream directly.
STATE_CHANGE_STUN_BREAK: Final[int] = 56

#: arcdps statechange byte for BarrierUpdate events (per
#: statechange-ids.md -- CBTS_BARRIERUPDATE = 38). The BarrierEvent
#: carries ``barrier_amount`` + ``duration_ms`` fields that the
#: pre-Phase-6-v2 parser-stream surfaces as ``0`` defaults (the
#: production-realistic yield awaits the parser-stream switch).
STATE_CHANGE_BARRIER_UPDATE: Final[int] = 38

#: arcdps statechange byte for ChangeDead events (per statechange-ids.md).
#: The player who died is source_agent_id; target_agent_id and skill_id
#: are 0 because the statechange record does not carry kill attribution.
#: The ``killed_by_agent_id`` and ``killing_skill_id`` fields default to
#: None (Phase 6 v2 forward-compat).
STATE_CHANGE_DEATH: Final[int] = 4

#: arcdps statechange byte for ChangeDown events (per statechange-ids.md).
#: The player who went down is source_agent_id; target_agent_id and
#: skill_id are 0 because the statechange record does not carry a target
#: or skill attribution. ``downtime_ms`` defaults to 0 (Phase 6 v2
#: forward-compat).
STATE_CHANGE_DOWN: Final[int] = 5

#: arcdps statechange byte for BreakbarPercent (per statechange-ids.md).
#: Byte 35 carries the defiance-bar percentage (0-100) in the cbtevent
#: ``value`` field. Byte 34 (BreakbarState) is the phase indicator
#: (active/recovering/immune) and is NOT dispatched separately -- the
#: percentage alone is sufficient for the CC-magnitude aggregator.
#: Dual-byte tracking (34+35) is deferred to Phase 6 v2 parser-stream.
STATE_CHANGE_BREAKBAR_PERCENT: Final[int] = 35


def _emit_stun_break(
    time_ms: int,
    src_agent: int,
    _dst_agent: int,
    _value: int,
    _skill_id: int,
) -> Event:
    """Emit a :class:`StunBreakEvent` for arcdps byte 56.

    The StunBreak statechange is actor-only: the player who broke the
    stun is ``source_agent_id``; ``target_agent_id`` and ``skill_id``
    are both ``0`` because arcdps StunBreak records don't carry a
    target or skill attribution (mirrors the
    :class:`~gw2_core.StunBreakEvent` docstring).
    """
    del _dst_agent, _value, _skill_id  # actor-only fields not used
    return StunBreakEvent(
        time_ms=time_ms,
        source_agent_id=src_agent,
        target_agent_id=0,
        skill_id=0,
    )


def _emit_barrier_update(
    time_ms: int,
    src_agent: int,
    dst_agent: int,
    _value: int,
    skill_id: int,
) -> Event:
    """Emit a :class:`BarrierEvent` for arcdps byte 38.

    The BarrierEvent carries ``barrier_amount`` + ``duration_ms``
    fields that the pre-Phase-6-v2 parser-stream surfaces as ``0``
    defaults (the per-skill barrier table is the Phase 6 v2 yield;
    pre-Phase-6-v2 streams parse cleanly because both fields default
    to ``0``).
    """
    del _value  # value field is not a barrier magnitude in this cbtevent path
    return BarrierEvent(
        time_ms=time_ms,
        source_agent_id=src_agent,
        target_agent_id=dst_agent,
        skill_id=skill_id,
        barrier_amount=0,
        duration_ms=0,
    )


def _emit_death(
    time_ms: int,
    src_agent: int,
    _dst_agent: int,
    _value: int,
    _skill_id: int,
) -> Event:
    """Emit a :class:`DeathEvent` for arcdps byte 4 (ChangeDead).

    Actor-only shape: the player who died is ``source_agent_id``;
    ``target_agent_id`` and ``skill_id`` are ``0``. The
    ``killed_by_agent_id`` and ``killing_skill_id`` fields default
    to ``None`` (the statechange record does not carry kill
    attribution -- Phase 6 v2 forward-compat).
    """
    del _dst_agent, _value, _skill_id
    return DeathEvent(
        time_ms=time_ms,
        source_agent_id=src_agent,
        target_agent_id=0,
        skill_id=0,
    )


def _emit_down(
    time_ms: int,
    src_agent: int,
    _dst_agent: int,
    _value: int,
    _skill_id: int,
) -> Event:
    """Emit a :class:`DownEvent` for arcdps byte 5 (ChangeDown).

    Actor-only shape: the player who went down is ``source_agent_id``;
    ``target_agent_id`` and ``skill_id`` are ``0``. ``downtime_ms``
    defaults to ``0`` (Phase 6 v2 forward-compat).
    """
    del _dst_agent, _value, _skill_id
    return DownEvent(
        time_ms=time_ms,
        source_agent_id=src_agent,
        target_agent_id=0,
        skill_id=0,
    )


def _emit_cc(
    time_ms: int,
    src_agent: int,
    dst_agent: int,
    value: int,
    skill_id: int,
) -> Event:
    """Emit a :class:`CCEvent` for arcdps byte 35 (BreakbarPercent).

    The breakbar percent (0-100) from the cbtevent ``value`` field is
    mapped to ``cc_value``. Byte 34 (BreakbarState -- phase indicator)
    is NOT dispatched separately; the percentage alone is sufficient
    for the CC-magnitude aggregator. Dual-byte tracking (34+35 for
    phase-aware CC attribution) is deferred to Phase 6 v2.

    ``target_agent_id`` carries the NPC whose breakbar was affected;
    ``source_agent_id`` is the player who applied the CC.
    """
    return CCEvent(
        time_ms=time_ms,
        source_agent_id=src_agent,
        target_agent_id=dst_agent,
        skill_id=skill_id,
        cc_value=value,
    )


#: Dispatch table mapping arcdps ``is_statechange`` byte -> emit constructor.
#:
#: The constructor signature is uniform across all emit functions::
#:
#:     (time_ms: int, src_agent: int, dst_agent: int, value: int, skill_id: int) -> Event
#:
#: so the :func:`dispatch_statechange` wrapper can pass through the
#: unpacked cbtevent tuple fields 1:1. Future A.4.3 emit functions
#: (DEATH + DOWN + CONDITION_REMOVE + CC) extend this table without
#: any change to the dispatch wrapper.
#:
#: v0.11.0 A.4: DEATH (byte 4), DOWN (byte 5), and CC (byte 35)
#: BreakbarPercent shipped. ConditionRemoveEvent remains deferred
#: (non-statechange source).
#:
#: Exposed at module level (NOT underscored) so the F1 calibration
#: pilot + the parser emit-side diagnostic logger can introspect the
#: wired kinds via ``statechange_dispatch.STATECHANGE_MAP.keys()``.
STATECHANGE_MAP: Final[dict[int, Callable[[int, int, int, int, int], Event]]] = {
    STATE_CHANGE_STUN_BREAK: _emit_stun_break,
    STATE_CHANGE_BARRIER_UPDATE: _emit_barrier_update,
    STATE_CHANGE_DEATH: _emit_death,
    STATE_CHANGE_DOWN: _emit_down,
    STATE_CHANGE_BREAKBAR_PERCENT: _emit_cc,
}


def dispatch_statechange(
    is_statechange: int,
    time_ms: int,
    src_agent: int,
    dst_agent: int,
    value: int,
    skill_id: int,
) -> Event | None:
    """Dispatch an arcdps statechange record to a domain event instance.

    Returns ``None`` for unmapped statechange kinds so the caller can
    decide whether to emit (None means "this kind isn't modelled yet";
    the parser's upstream filter continues to skip it).

    Returns the Pydantic :class:`Event` instance for mapped kinds so
    the caller can ``yield`` it inline.
    """
    handler = STATECHANGE_MAP.get(is_statechange)
    if handler is None:
        return None
    # mypy narrows the Callable[[int, int, int, int, int], Event]
    # return type straight through: no redundant cast needed.
    result = handler(time_ms, src_agent, dst_agent, value, skill_id)
    # F1-calibration pilot instrumentation: surface the byte -> Event
    # dispatch via DEBUG so a maintainer running the pilot at
    # ``logging.DEBUG`` can see which kinds are mapped vs unmapped
    # without rerunning the hermetic tests. The 84 unmapped kinds are
    # silent (their handler is None and short-circuits above).
    logger.debug(
        "statechange dispatch: byte=%s -> %s",
        is_statechange,
        type(result).__name__,
    )
    return result


__all__ = [
    "STATECHANGE_MAP",
    "STATE_CHANGE_BARRIER_UPDATE",
    "STATE_CHANGE_BREAKBAR_PERCENT",
    "STATE_CHANGE_DEATH",
    "STATE_CHANGE_DOWN",
    "STATE_CHANGE_STUN_BREAK",
    "dispatch_statechange",
]
